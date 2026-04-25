"""
preprocess.py
=============
Extract B04 (Red), B08 (NIR), and SCL (Scene Classification Layer)
from a Sentinel-2 L2A .SAFE product folder.

Handles:
  - Locating band files within .SAFE directory structure
  - Reading actual DN values via rasterio
  - Cloud masking using SCL band
  - Resampling SCL (20m) to match B04/B08 (10m)
  - Clipping to AOI bounding box
  - Writing processed GeoTIFFs

SENTINEL-2 L2A .SAFE STRUCTURE (Baseline 04.00+):
  S2A_MSIL2A_<date>_<orbit>.SAFE/
    GRANULE/
      L2A_T<tile>_<date>_<orbit>/
        IMG_DATA/
          R10m/
            *_B02_10m.tif   (Blue)
            *_B03_10m.tif   (Green)
            *_B04_10m.tif   (Red)   ← we use this
            *_B08_10m.tif   (NIR)   ← we use this
          R20m/
            *_SCL_20m.tif   (Scene Classification Layer) ← cloud mask
"""

import logging
from pathlib import Path
from typing import Optional, Tuple, Dict

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask as rio_mask
from rasterio.warp import reproject, Resampling as WarpResampling
from rasterio.crs import CRS
from shapely.geometry import box, mapping
import pyproj

logger = logging.getLogger(__name__)


# SCL class values that indicate unusable pixels
# Full SCL legend: https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview
SCL_UNUSABLE_CLASSES = {
    0: "NO_DATA",
    1: "SATURATED_OR_DEFECTIVE",
    3: "CLOUD_SHADOWS",
    8: "CLOUD_MEDIUM_PROBABILITY",
    9: "CLOUD_HIGH_PROBABILITY",
    10: "THIN_CIRRUS",
    11: "SNOW_ICE",
}

# SCL class 4 = Vegetation, 5 = Not vegetated, 6 = Water, 7 = Unclassified
# We keep 4, 5, 6, 7 as valid (usable non-cloud pixels)


def find_safe_bands(safe_dir: str) -> Dict[str, Path]:
    """
    Locate band files within a .SAFE directory.
    Returns dict: {"B04": Path, "B08": Path, "SCL": Path}
    
    Handles both older (.jp2) and newer (.tif) product formats.
    """
    safe_path = Path(safe_dir)
    if not safe_path.exists():
        raise FileNotFoundError(f".SAFE directory not found: {safe_path}")
    
    band_files = {}
    
    # Search for each band
    band_patterns = {
        "B04": ["*_B04_10m.tif", "*_B04_10m.jp2", "*_B04.tif", "*_B04.jp2"],
        "B08": ["*_B08_10m.tif", "*_B08_10m.jp2", "*_B08.tif", "*_B08.jp2"],
        "SCL": ["*_SCL_20m.tif", "*_SCL_20m.jp2", "*_SCL.tif", "*_SCL.jp2"],
    }
    
    for band_name, patterns in band_patterns.items():
        found = None
        for pattern in patterns:
            matches = list(safe_path.rglob(pattern))
            if matches:
                found = matches[0]
                break
        
        if found is None:
            raise FileNotFoundError(
                f"Band {band_name} not found in {safe_path}. "
                f"Tried patterns: {patterns}. "
                f"Check that this is a valid L2A product (not L1C)."
            )
        
        logger.info(f"Found {band_name}: {found.relative_to(safe_path)}")
        band_files[band_name] = found
    
    return band_files


def read_band_as_float32(
    band_path: Path,
    aoi_geometry: Optional[dict] = None
) -> Tuple[np.ndarray, dict]:
    """
    Read a single band GeoTIFF/JP2 as float32.
    
    Returns:
        data: np.ndarray shape (H, W), float32, surface reflectance [0,1]
        meta: rasterio metadata dict
    
    If aoi_geometry provided, clips to that bounding box.
    """
    with rasterio.open(band_path) as src:
        logger.debug(
            f"Reading {band_path.name}: "
            f"CRS={src.crs}, shape={src.shape}, "
            f"bounds={src.bounds}, dtype={src.dtypes[0]}"
        )
        
        if aoi_geometry is not None:
            # Reproject AOI geometry to band's CRS if needed
            aoi_geom_reprojected = _reproject_geometry(aoi_geometry, src.crs)
            data, transform = rio_mask(
                src, [aoi_geom_reprojected], crop=True, nodata=0
            )
            data = data[0]  # Remove band dimension
            meta = src.meta.copy()
            meta.update({
                "height": data.shape[0],
                "width": data.shape[1],
                "transform": transform
            })
        else:
            data = src.read(1)  # Band 1
            meta = src.meta.copy()
    
    # Convert DN to surface reflectance
    # Sentinel-2 L2A DNs are stored as integer, divide by 10000
    # Valid range after conversion: 0.0 to ~1.0 (some values slightly above 1.0 are possible)
    if data.dtype in (np.uint16, np.int16, np.uint32, np.int32):
        data = data.astype(np.float32) / 10000.0
        logger.debug(f"Converted DN→SR: range [{data.min():.4f}, {data.max():.4f}]")
    elif data.dtype == np.float32 or data.dtype == np.float64:
        logger.debug(f"Already float: range [{data.min():.4f}, {data.max():.4f}]")
    
    # Clamp to [0, 1] — values outside indicate clouds/snow/saturation
    # but we handle those via SCL, not clamping
    # DO NOT clamp here; preserve actual values for diagnostics
    
    return data.astype(np.float32), meta


def resample_to_match(
    source_array: np.ndarray,
    source_meta: dict,
    target_meta: dict,
) -> np.ndarray:
    """
    Resample source array to match target spatial resolution and extent.
    Used to upsample SCL from 20m to 10m.
    """
    resampled = np.zeros(
        (target_meta["height"], target_meta["width"]),
        dtype=source_array.dtype
    )
    
    reproject(
        source=source_array,
        destination=resampled,
        src_transform=source_meta["transform"],
        src_crs=source_meta["crs"],
        dst_transform=target_meta["transform"],
        dst_crs=target_meta["crs"],
        resampling=WarpResampling.nearest  # nearest neighbor for categorical SCL
    )
    
    return resampled


def build_cloud_mask(
    scl_array: np.ndarray,
    unusable_classes: Optional[dict] = None,
) -> np.ndarray:
    """
    Build boolean cloud mask from SCL.
    
    Returns:
        mask: np.ndarray bool, shape (H, W)
              True  = pixel is VALID (not cloud/shadow/nodata)
              False = pixel is INVALID (cloud/shadow/nodata)
    """
    if unusable_classes is None:
        unusable_classes = SCL_UNUSABLE_CLASSES
    
    invalid = np.zeros(scl_array.shape, dtype=bool)
    for class_val in unusable_classes.keys():
        invalid |= (scl_array == class_val)
    
    valid_mask = ~invalid
    
    valid_pct = valid_mask.mean() * 100
    logger.info(
        f"Cloud mask: {valid_pct:.1f}% valid pixels "
        f"({valid_mask.sum():,} of {valid_mask.size:,})"
    )
    
    return valid_mask


def preprocess_safe(
    safe_dir: str,
    output_dir: str,
    aoi_geometry: Optional[dict] = None,
) -> Dict[str, str]:
    """
    Full preprocessing of one .SAFE product.
    
    Steps:
    1. Locate B04, B08, SCL band files
    2. Read B04 and B08 as float32 surface reflectance
    3. Read SCL, resample to 10m
    4. Build cloud mask
    5. Write processed arrays to output_dir
    
    Returns:
        dict with paths to: b04_path, b08_path, scl_path, cloud_mask_path
        and metadata: acquisition_date, cloud_cover_pct, valid_pixel_pct
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    safe_name = Path(safe_dir).name
    logger.info(f"Preprocessing: {safe_name}")
    
    # --- Step 1: Find band files ---
    band_files = find_safe_bands(safe_dir)
    
    # --- Step 2: Read B04 and B08 ---
    b04_array, b04_meta = read_band_as_float32(band_files["B04"], aoi_geometry)
    b08_array, b08_meta = read_band_as_float32(band_files["B08"], aoi_geometry)
    
    # Verify spatial consistency
    if b04_array.shape != b08_array.shape:
        raise ValueError(
            f"B04 shape {b04_array.shape} != B08 shape {b08_array.shape}. "
            f"This indicates a data integrity issue."
        )
    
    logger.info(f"Band shapes: B04={b04_array.shape}, B08={b08_array.shape}")
    logger.info(f"B04 reflectance range: [{b04_array.min():.4f}, {b04_array.max():.4f}]")
    logger.info(f"B08 reflectance range: [{b08_array.min():.4f}, {b08_array.max():.4f}]")
    
    # --- Step 3: Read and resample SCL ---
    scl_raw, scl_meta = _read_scl_raw(band_files["SCL"], aoi_geometry)
    scl_resampled = resample_to_match(scl_raw, scl_meta, b04_meta)
    
    # --- Step 4: Build cloud mask ---
    valid_mask = build_cloud_mask(scl_resampled)
    cloud_cover_pct = (1.0 - valid_mask.mean()) * 100
    
    # --- Step 5: Write outputs ---
    product_prefix = _parse_product_prefix(safe_name)
    
    b04_out = output_path / f"{product_prefix}_B04.tif"
    b08_out = output_path / f"{product_prefix}_B08.tif"
    scl_out = output_path / f"{product_prefix}_SCL_10m.tif"
    mask_out = output_path / f"{product_prefix}_valid_mask.tif"
    
    _write_float32_tif(b04_array, b04_meta, b04_out)
    _write_float32_tif(b08_array, b08_meta, b08_out)
    _write_uint8_tif(scl_resampled.astype(np.uint8), b04_meta, scl_out)
    _write_uint8_tif(valid_mask.astype(np.uint8), b04_meta, mask_out)
    
    acquisition_date = _parse_acquisition_date(safe_name)
    
    result = {
        "b04_path": str(b04_out),
        "b08_path": str(b08_out),
        "scl_path": str(scl_out),
        "cloud_mask_path": str(mask_out),
        "acquisition_date": acquisition_date,
        "cloud_cover_pct": round(cloud_cover_pct, 2),
        "valid_pixel_pct": round(valid_mask.mean() * 100, 2),
        "shape_pixels": list(b04_array.shape),
        "crs": str(b04_meta["crs"]),
        "transform": list(b04_meta["transform"]),
    }
    
    logger.info(f"Preprocessing complete: {product_prefix}")
    logger.info(f"  Acquisition: {acquisition_date}")
    logger.info(f"  Cloud cover: {cloud_cover_pct:.1f}%")
    logger.info(f"  Valid pixels: {valid_mask.mean()*100:.1f}%")
    
    return result


# --- Private helpers ---

def _read_scl_raw(scl_path: Path, aoi_geometry: Optional[dict]) -> Tuple[np.ndarray, dict]:
    """Read SCL band without DN conversion (it's categorical, not reflectance)."""
    with rasterio.open(scl_path) as src:
        if aoi_geometry is not None:
            aoi_geom = _reproject_geometry(aoi_geometry, src.crs)
            data, transform = rio_mask(src, [aoi_geom], crop=True, nodata=0)
            data = data[0]
            meta = src.meta.copy()
            meta.update({"height": data.shape[0], "width": data.shape[1], "transform": transform})
        else:
            data = src.read(1)
            meta = src.meta.copy()
    return data, meta


def _reproject_geometry(geometry: dict, target_crs) -> dict:
    """Reproject a GeoJSON geometry from WGS84 to target CRS."""
    from pyproj import Transformer
    from shapely.geometry import shape, mapping
    
    transformer = Transformer.from_crs("EPSG:4326", str(target_crs), always_xy=True)
    geom = shape(geometry)
    
    if hasattr(geom, "exterior"):  # Polygon
        coords = [
            transformer.transform(x, y)
            for x, y in geom.exterior.coords
        ]
        from shapely.geometry import Polygon
        reprojected = Polygon(coords)
    else:
        raise ValueError(f"Unsupported geometry type: {geom.geom_type}")
    
    return mapping(reprojected)


def _write_float32_tif(array: np.ndarray, meta: dict, output_path: Path):
    out_meta = meta.copy()
    out_meta.update({
        "dtype": "float32",
        "count": 1,
        "compress": "lzw",
        "driver": "GTiff"  # Force GeoTIFF format
    })
    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(array, 1)
    logger.debug(f"Wrote: {output_path}")


def _write_uint8_tif(array: np.ndarray, meta: dict, output_path: Path):
    out_meta = meta.copy()
    out_meta.update({
        "dtype": "uint8",
        "count": 1,
        "compress": "lzw",
        "driver": "GTiff"  # Force GeoTIFF format
    })
    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(array, 1)
    logger.debug(f"Wrote: {output_path}")


def _parse_product_prefix(safe_name: str) -> str:
    """Extract date+tile from SAFE folder name."""
    # S2A_MSIL2A_20240615T053639_N0510_R005_T43PGN_20240615T085512.SAFE
    # → S2A_20240615_T43PGN
    parts = safe_name.replace(".SAFE", "").split("_")
    try:
        platform = parts[0]           # S2A or S2B
        date_part = parts[2][:8]      # 20240615
        tile = parts[5]               # T43PGN
        return f"{platform}_{date_part}_{tile}"
    except (IndexError, ValueError):
        return safe_name.replace(".SAFE", "").replace(".", "_")[:40]


def _parse_acquisition_date(safe_name: str) -> str:
    """Extract ISO 8601 acquisition datetime from SAFE folder name."""
    # S2A_MSIL2A_20240615T053639_... → 2024-06-15T05:36:39Z
    try:
        parts = safe_name.split("_")
        dt_str = parts[2]  # 20240615T053639
        return f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}T{dt_str[9:11]}:{dt_str[11:13]}:{dt_str[13:15]}Z"
    except (IndexError, ValueError):
        logger.warning(f"Could not parse acquisition date from: {safe_name}")
        return "UNKNOWN"