"""
tiling.py
=========
Divide an Area of Interest into a regular grid of tiles.
Each tile has real geographic coordinates derived from the raster transform.

Tile size is specified in kilometers. Pixel coverage is computed from the
actual raster resolution (from GeoTIFF metadata), not assumed.

No coordinates are invented. All lat/lon values come from rasterio transforms.
"""

import logging
from typing import List, Dict, Tuple, Optional

import numpy as np
import rasterio
from rasterio.transform import AffineTransformer, rowcol
from rasterio.crs import CRS
from pyproj import Transformer

logger = logging.getLogger(__name__)


def meters_to_pixels(meters: float, pixel_size_m: float) -> int:
    """Convert distance in meters to pixel count given pixel size."""
    return max(1, int(round(meters / pixel_size_m)))


def get_pixel_size_meters(transform, crs) -> float:
    """
    Get pixel size in meters from raster transform and CRS.
    For UTM projections (Sentinel-2), this is straightforward.
    For geographic CRS (EPSG:4326), we convert degrees to meters.
    """
    pixel_size_x = abs(transform.a)  # x pixel size in CRS units
    
    if crs.is_geographic:
        # Degrees → approximate meters at equator (~111km per degree)
        # More accurate: use the centroid latitude
        pixel_size_m = pixel_size_x * 111_320
        logger.warning(
            f"Geographic CRS detected. Pixel size ~{pixel_size_m:.1f}m "
            f"(approximate, latitude-dependent)"
        )
    else:
        # Projected CRS (UTM, etc.) — units are already in meters
        pixel_size_m = pixel_size_x
    
    return pixel_size_m


def pixel_to_latlon(row: int, col: int, transform, crs) -> Tuple[float, float]:
    """
    Convert pixel (row, col) to geographic (lat, lon) WGS84 coordinates.
    Uses rasterio affine transform + pyproj reprojection.
    """
    # Get map coordinates in the raster's CRS
    transformer = AffineTransformer(transform)
    x, y = transformer.xy(row, col)
    
    if str(crs) == "EPSG:4326":
        return y, x  # already lat/lon
    
    # Reproject from raster CRS to WGS84
    proj = Transformer.from_crs(str(crs), "EPSG:4326", always_xy=True)
    lon, lat = proj.transform(x, y)
    return lat, lon


def generate_tiles(
    ndvi: np.ndarray,
    transform,
    crs,
    tile_size_km: float,
    valid_mask: Optional[np.ndarray] = None,
) -> List[Dict]:
    """
    Divide the NDVI raster into a regular grid of tiles.
    
    Args:
        ndvi: float32 array (H, W), NaN = invalid
        transform: rasterio Affine transform
        crs: rasterio CRS
        tile_size_km: tile side length in kilometers
        valid_mask: bool array (H, W), True=valid pixel
    
    Returns:
        List of tile dicts, each containing:
          - tile_id: str
          - row_start, col_start, row_end, col_end: pixel bounds
          - lat_min, lat_max, lon_min, lon_max: geographic bounds (WGS84)
          - center_lat, center_lon: tile center
          - ndvi_stats: computed from valid pixels in this tile
          - valid_pixel_fraction: fraction of non-NaN pixels
          - total_pixels: int
          - valid_pixels: int
    """
    height, width = ndvi.shape
    pixel_size_m = get_pixel_size_meters(transform, crs)
    tile_pixels = meters_to_pixels(tile_size_km * 1000, pixel_size_m)
    
    n_tiles_row = int(np.ceil(height / tile_pixels))
    n_tiles_col = int(np.ceil(width / tile_pixels))
    total_tiles = n_tiles_row * n_tiles_col
    
    logger.info(
        f"Generating {total_tiles} tiles ({n_tiles_row}×{n_tiles_col}) "
        f"of ~{tile_pixels}×{tile_pixels} pixels "
        f"({tile_size_km}km at {pixel_size_m:.1f}m/pixel)"
    )
    
    tiles = []
    skipped_empty = 0
    
    for r in range(n_tiles_row):
        for c in range(n_tiles_col):
            row_start = r * tile_pixels
            col_start = c * tile_pixels
            row_end = min(row_start + tile_pixels, height)
            col_end = min(col_start + tile_pixels, width)
            
            # Extract tile NDVI values
            tile_ndvi = ndvi[row_start:row_end, col_start:col_end]
            
            # Get valid pixels from the tile
            valid_in_tile = ~np.isnan(tile_ndvi)
            total_px = tile_ndvi.size
            valid_px = valid_in_tile.sum()
            valid_frac = valid_px / total_px if total_px > 0 else 0.0
            
            # Skip tiles with no valid data
            if valid_px == 0:
                skipped_empty += 1
                continue
            
            # Compute geographic bounds (using pixel corners → lat/lon)
            # Top-left corner
            lat_tl, lon_tl = pixel_to_latlon(row_start, col_start, transform, crs)
            # Bottom-right corner
            lat_br, lon_br = pixel_to_latlon(row_end - 1, col_end - 1, transform, crs)
            # Center
            lat_c, lon_c = pixel_to_latlon(
                (row_start + row_end) // 2,
                (col_start + col_end) // 2,
                transform, crs
            )
            
            lat_min = min(lat_tl, lat_br)
            lat_max = max(lat_tl, lat_br)
            lon_min = min(lon_tl, lon_br)
            lon_max = max(lon_tl, lon_br)
            
            # Compute NDVI statistics for this tile (valid pixels only)
            tile_valid_values = tile_ndvi[valid_in_tile]
            tile_stats = _tile_ndvi_stats(tile_valid_values)
            
            # Compute vegetated area in hectares
            # 1 pixel = pixel_size_m × pixel_size_m square meters
            pixel_area_ha = (pixel_size_m ** 2) / 10_000
            vegetated_pixels = np.sum(tile_valid_values >= 0.15)  # NDVI ≥ 0.15 = some vegetation
            vegetated_ha = vegetated_pixels * pixel_area_ha
            total_valid_ha = valid_px * pixel_area_ha
            
            tile_id = f"T{r:03d}_{c:03d}"
            
            tiles.append({
                "tile_id": tile_id,
                "row_start": int(row_start),
                "col_start": int(col_start),
                "row_end": int(row_end),
                "col_end": int(col_end),
                "pixel_size_m": round(pixel_size_m, 2),
                "total_pixels": int(total_px),
                "valid_pixels": int(valid_px),
                "valid_pixel_fraction": round(float(valid_frac), 4),
                "lat_min": round(float(lat_min), 6),
                "lat_max": round(float(lat_max), 6),
                "lon_min": round(float(lon_min), 6),
                "lon_max": round(float(lon_max), 6),
                "center_lat": round(float(lat_c), 6),
                "center_lon": round(float(lon_c), 6),
                "vegetated_ha": round(float(vegetated_ha), 2),
                "total_valid_ha": round(float(total_valid_ha), 2),
                "ndvi_stats": tile_stats,
            })
    
    logger.info(
        f"Generated {len(tiles)} tiles with valid data "
        f"(skipped {skipped_empty} fully empty tiles)"
    )
    
    return tiles


def _tile_ndvi_stats(valid_values: np.ndarray) -> dict:
    """
    Compute per-tile NDVI statistics.
    Input: 1D array of valid (non-NaN) NDVI values from one tile.
    All values come from actual pixel data.
    """
    if valid_values.size == 0:
        return {"error": "no_valid_pixels"}
    
    return {
        "mean": round(float(valid_values.mean()), 6),
        "std": round(float(valid_values.std()), 6),
        "min": round(float(valid_values.min()), 6),
        "max": round(float(valid_values.max()), 6),
        "median": round(float(np.median(valid_values)), 6),
        "p10": round(float(np.percentile(valid_values, 10)), 6),
        "p25": round(float(np.percentile(valid_values, 25)), 6),
        "p75": round(float(np.percentile(valid_values, 75)), 6),
        "p90": round(float(np.percentile(valid_values, 90)), 6),
        "n": int(valid_values.size),
    }