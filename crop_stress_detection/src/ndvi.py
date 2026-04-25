"""
ndvi.py
=======
Compute NDVI from real Sentinel-2 B04 (Red) and B08 (NIR) surface reflectance arrays.

Formula:
    NDVI = (NIR - Red) / (NIR + Red)
    NDVI = (B08 - B04) / (B08 + B04)

Range: [-1, 1]

Implementation Notes:
- Division by zero when (NIR + Red) == 0 → set NDVI to NaN, flagged separately
- Cloud/shadow pixels (valid_mask=False) → set NDVI to NaN, not included in stats
- No values are imputed or estimated here — NaN means "no data"
- All statistics are computed ONLY from valid, non-NaN pixels

Reference:
    Rouse, J.W. et al. (1974). "Monitoring Vegetation Systems in the Great Plains
    with ERTS." Third ERTS Symposium, NASA SP-351 I, 309-317.
"""

import logging
from typing import Optional, Tuple, Dict

import numpy as np
import rasterio
from rasterio.transform import AffineTransformer

logger = logging.getLogger(__name__)


def compute_ndvi(
    b04: np.ndarray,
    b08: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Compute per-pixel NDVI from surface reflectance arrays.
    
    Args:
        b04: Red band, float32, shape (H, W), range [0,1]
        b08: NIR band, float32, shape (H, W), range [0,1]
        valid_mask: bool array, True=valid pixel, False=cloud/nodata
                    If None, all pixels assumed valid.
    
    Returns:
        ndvi: float32 array, shape (H, W)
              Values in [-1, 1] for valid pixels
              NaN for cloud/nodata/zero-denominator pixels
    
    CRITICAL: No values are filled, interpolated, or fabricated.
    NaN pixels are excluded from all downstream statistics.
    """
    if b04.shape != b08.shape:
        raise ValueError(f"Shape mismatch: B04={b04.shape}, B08={b08.shape}")
    
    if b04.dtype != np.float32 or b08.dtype != np.float32:
        logger.warning("Input arrays are not float32. Converting.")
        b04 = b04.astype(np.float32)
        b08 = b08.astype(np.float32)
    
    # --- Compute denominator ---
    denominator = b08 + b04
    
    # --- Identify zero denominator pixels ---
    # (NIR + Red) == 0 can occur at nodata pixels or fully dark surfaces
    zero_denom_mask = (denominator == 0)
    zero_denom_count = zero_denom_mask.sum()
    
    if zero_denom_count > 0:
        logger.debug(
            f"Zero denominator at {zero_denom_count:,} pixels "
            f"({zero_denom_count / b04.size * 100:.2f}%) → set to NaN"
        )
    
    # --- Compute NDVI ---
    # Use np.errstate to suppress division-by-zero warnings (we handle it explicitly)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(
            zero_denom_mask,
            np.nan,
            (b08 - b04) / denominator
        )
    
    ndvi = ndvi.astype(np.float32)
    
    # --- Apply cloud/nodata mask ---
    if valid_mask is not None:
        if valid_mask.shape != ndvi.shape:
            raise ValueError(f"Mask shape {valid_mask.shape} != NDVI shape {ndvi.shape}")
        
        invalid_count = (~valid_mask).sum()
        ndvi[~valid_mask] = np.nan
        logger.debug(f"Masked {invalid_count:,} cloud/nodata pixels → NaN")
    
    # --- Log summary statistics (from valid pixels only) ---
    valid = ndvi[~np.isnan(ndvi)]
    
    if valid.size == 0:
        logger.warning("ALL PIXELS ARE NaN. No valid NDVI can be computed.")
        logger.warning("Check cloud mask and input band files.")
        return ndvi
    
    logger.info(
        f"NDVI computed: {valid.size:,} valid pixels "
        f"({valid.size / ndvi.size * 100:.1f}% of total)"
    )
    logger.info(
        f"NDVI stats: "
        f"mean={valid.mean():.4f}, "
        f"std={valid.std():.4f}, "
        f"min={valid.min():.4f}, "
        f"max={valid.max():.4f}, "
        f"median={np.median(valid):.4f}"
    )
    
    # Log percentile distribution (useful for validating against known land cover)
    pcts = np.percentile(valid, [5, 10, 25, 50, 75, 90, 95])
    logger.info(
        f"NDVI percentiles: "
        f"p5={pcts[0]:.3f}, p10={pcts[1]:.3f}, p25={pcts[2]:.3f}, "
        f"p50={pcts[3]:.3f}, p75={pcts[4]:.3f}, p90={pcts[5]:.3f}, p95={pcts[6]:.3f}"
    )
    
    return ndvi


def compute_ndvi_from_files(
    b04_path: str,
    b08_path: str,
    valid_mask_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Tuple[np.ndarray, dict]:
    """
    Compute NDVI from GeoTIFF files on disk.
    
    Returns:
        ndvi_array: float32 np.ndarray
        metadata: dict with spatial reference, stats, input sources
    """
    logger.info(f"Loading B04: {b04_path}")
    with rasterio.open(b04_path) as src:
        b04 = src.read(1).astype(np.float32)
        raster_meta = src.meta.copy()
        transform = src.transform
        crs = src.crs
    
    logger.info(f"Loading B08: {b08_path}")
    with rasterio.open(b08_path) as src:
        b08 = src.read(1).astype(np.float32)
    
    valid_mask = None
    if valid_mask_path is not None:
        logger.info(f"Loading valid mask: {valid_mask_path}")
        with rasterio.open(valid_mask_path) as src:
            valid_mask = src.read(1).astype(bool)
    
    # Validate input ranges
    _validate_reflectance(b04, "B04")
    _validate_reflectance(b08, "B08")
    
    # Compute NDVI
    ndvi = compute_ndvi(b04, b08, valid_mask)
    
    # Build metadata
    metadata = {
        "b04_source": b04_path,
        "b08_source": b08_path,
        "valid_mask_source": valid_mask_path,
        "crs": str(crs),
        "transform": list(transform),
        "shape": list(ndvi.shape),
        "total_pixels": int(ndvi.size),
        "valid_pixels": int(np.sum(~np.isnan(ndvi))),
        "nan_pixels": int(np.sum(np.isnan(ndvi))),
        "ndvi_stats": _compute_stats(ndvi),
    }
    
    # Optionally write NDVI raster to disk
    if output_path is not None:
        _write_ndvi_tif(ndvi, raster_meta, output_path)
        metadata["ndvi_raster_path"] = output_path
    
    return ndvi, metadata


def _validate_reflectance(arr: np.ndarray, band_name: str):
    """
    Sanity-check that reflectance values are in expected range.
    Warn (not fail) if suspicious — data may still be usable.
    """
    nonzero = arr[arr > 0]
    if nonzero.size == 0:
        logger.error(f"{band_name}: ALL PIXEL VALUES ARE ZERO. Check band file.")
        return
    
    p1, p99 = np.percentile(nonzero, [1, 99])
    
    if p99 > 1.5:
        logger.warning(
            f"{band_name}: p99 reflectance = {p99:.3f} (expected ≤1.0). "
            f"May not be divided by 10000 yet, or contains snow/cloud."
        )
    elif p99 < 0.01:
        logger.warning(
            f"{band_name}: p99 reflectance = {p99:.4f} (very low). "
            f"Check if image is nighttime or corrupted."
        )
    else:
        logger.debug(f"{band_name}: reflectance p1={p1:.4f}, p99={p99:.4f} ✓")


def _compute_stats(ndvi: np.ndarray) -> dict:
    """Compute summary statistics from valid (non-NaN) NDVI pixels."""
    valid = ndvi[~np.isnan(ndvi)]
    
    if valid.size == 0:
        return {"error": "no_valid_pixels"}
    
    percentiles = np.percentile(valid, [5, 10, 25, 50, 75, 90, 95])
    
    return {
        "mean": round(float(valid.mean()), 6),
        "std": round(float(valid.std()), 6),
        "min": round(float(valid.min()), 6),
        "max": round(float(valid.max()), 6),
        "median": round(float(np.median(valid)), 6),
        "p5": round(float(percentiles[0]), 6),
        "p10": round(float(percentiles[1]), 6),
        "p25": round(float(percentiles[2]), 6),
        "p75": round(float(percentiles[4]), 6),
        "p90": round(float(percentiles[5]), 6),
        "p95": round(float(percentiles[6]), 6),
        "n_valid": int(valid.size),
        "n_total": int(ndvi.size),
        "valid_fraction": round(float(valid.size / ndvi.size), 6),
    }


def _write_ndvi_tif(ndvi: np.ndarray, base_meta: dict, output_path: str):
    """Write NDVI float32 GeoTIFF. NaN values stored as nodata=-9999."""
    out_meta = base_meta.copy()
    out_meta.update({
        "dtype": "float32",
        "count": 1,
        "nodata": -9999.0,
        "compress": "lzw",
    })
    
    # Replace NaN with nodata before writing
    ndvi_out = ndvi.copy()
    ndvi_out[np.isnan(ndvi_out)] = -9999.0
    
    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(ndvi_out, 1)
    
    logger.info(f"NDVI raster saved: {output_path}")