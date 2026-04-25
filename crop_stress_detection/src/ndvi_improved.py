"""
ndvi_improved.py
================
PRODUCTION-READY NDVI computation with robust preprocessing filters.

IMPROVEMENTS:
1. Safe division handling (zero denominator → NaN)
2. Outlier removal (NDVI outside [-0.2, 1.0])
3. Gaussian smoothing (sigma=1) for noise reduction
4. Proper masking of invalid pixels (clouds, water, nodata)
5. Vegetation filtering (NDVI > 0.2)

Author: Senior Remote Sensing Engineer
"""

import logging
from typing import Optional, Tuple, Dict

import numpy as np
import rasterio
from scipy.ndimage import gaussian_filter

logger = logging.getLogger(__name__)


def compute_ndvi_robust(
    b04: np.ndarray,
    b08: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
    apply_smoothing: bool = True,
    remove_outliers: bool = True,
    vegetation_threshold: float = 0.2,
) -> Tuple[np.ndarray, dict]:
    """
    Compute NDVI with production-ready preprocessing filters.
    
    Args:
        b04: Red band, float32, shape (H, W), surface reflectance [0,1]
        b08: NIR band, float32, shape (H, W), surface reflectance [0,1]
        valid_mask: bool array, True=valid (not cloud/water/nodata)
        apply_smoothing: Apply Gaussian filter (sigma=1) for noise reduction
        remove_outliers: Mask NDVI outside [-0.2, 1.0]
        vegetation_threshold: Minimum NDVI for vegetation (default 0.2)
    
    Returns:
        ndvi: float32 array with NaN for invalid pixels
        metadata: dict with processing statistics
    
    PROCESSING STEPS:
    1. Safe division (handle B08 + B04 = 0)
    2. Apply cloud/water/nodata mask
    3. Remove outliers (NDVI < -0.2 or > 1.0)
    4. Gaussian smoothing (optional, sigma=1)
    5. Compute statistics on valid vegetation pixels
    """
    
    if b04.shape != b08.shape:
        raise ValueError(f"Shape mismatch: B04={b04.shape}, B08={b08.shape}")
    
    logger.info("="*60)
    logger.info("STEP 1: NDVI COMPUTATION (ROBUST)")
    logger.info("="*60)
    
    # Convert to float32 if needed
    b04 = b04.astype(np.float32)
    b08 = b08.astype(np.float32)
    
    # --- STEP 1: Safe Division ---
    logger.info("Step 1.1: Computing NDVI with safe division...")
    denominator = b08 + b04
    zero_denom = (denominator == 0)
    
    with np.errstate(divide='ignore', invalid='ignore'):
        ndvi = np.where(zero_denom, np.nan, (b08 - b04) / denominator)
    
    ndvi = ndvi.astype(np.float32)
    
    zero_count = zero_denom.sum()
    logger.info(f"  Zero denominator pixels: {zero_count:,} ({zero_count/ndvi.size*100:.2f}%)")
    
    # --- STEP 2: Apply Cloud/Water/Nodata Mask ---
    if valid_mask is not None:
        logger.info("Step 1.2: Applying cloud/water/nodata mask...")
        if valid_mask.shape != ndvi.shape:
            raise ValueError(f"Mask shape {valid_mask.shape} != NDVI shape {ndvi.shape}")
        
        invalid_count = (~valid_mask).sum()
        ndvi[~valid_mask] = np.nan
        logger.info(f"  Masked pixels: {invalid_count:,} ({invalid_count/ndvi.size*100:.2f}%)")
    
    # --- STEP 3: Remove Outliers ---
    if remove_outliers:
        logger.info("Step 1.3: Removing outliers (NDVI outside [-0.2, 1.0])...")
        outlier_mask = (ndvi < -0.2) | (ndvi > 1.0)
        outlier_count = np.sum(outlier_mask & ~np.isnan(ndvi))
        
        if outlier_count > 0:
            ndvi[outlier_mask] = np.nan
            logger.info(f"  Outliers removed: {outlier_count:,} ({outlier_count/ndvi.size*100:.2f}%)")
        else:
            logger.info(f"  No outliers found")
    
    # --- STEP 4: Gaussian Smoothing (Noise Reduction) ---
    if apply_smoothing:
        logger.info("Step 1.4: Applying Gaussian smoothing (sigma=1.0)...")
        
        # Create mask of valid pixels for smoothing
        valid_for_smooth = ~np.isnan(ndvi)
        
        if valid_for_smooth.sum() > 100:  # Only smooth if enough valid pixels
            # Replace NaN with 0 temporarily for filtering
            ndvi_smooth = ndvi.copy()
            ndvi_smooth[~valid_for_smooth] = 0
            
            # Apply Gaussian filter
            ndvi_smooth = gaussian_filter(ndvi_smooth, sigma=1.0)
            
            # Restore NaN locations
            ndvi_smooth[~valid_for_smooth] = np.nan
            ndvi = ndvi_smooth.astype(np.float32)
            
            logger.info(f"  Smoothing applied successfully")
        else:
            logger.warning(f"  Insufficient valid pixels for smoothing (need >100, have {valid_for_smooth.sum()})")
    
    # --- STEP 5: Compute Statistics ---
    valid_ndvi = ndvi[~np.isnan(ndvi)]
    
    if valid_ndvi.size == 0:
        logger.error("ERROR: All pixels are NaN after processing!")
        metadata = {
            "error": "no_valid_pixels",
            "total_pixels": int(ndvi.size),
            "valid_pixels": 0,
        }
        return ndvi, metadata
    
    # Compute vegetation pixels (NDVI > threshold)
    vegetation_pixels = valid_ndvi[valid_ndvi > vegetation_threshold]
    vegetation_fraction = vegetation_pixels.size / ndvi.size
    
    logger.info("="*60)
    logger.info("NDVI STATISTICS")
    logger.info("="*60)
    logger.info(f"Total pixels:       {ndvi.size:,}")
    logger.info(f"Valid pixels:       {valid_ndvi.size:,} ({valid_ndvi.size/ndvi.size*100:.1f}%)")
    logger.info(f"Vegetation pixels:  {vegetation_pixels.size:,} ({vegetation_fraction*100:.1f}%)")
    logger.info(f"")
    logger.info(f"NDVI range:         [{valid_ndvi.min():.4f}, {valid_ndvi.max():.4f}]")
    logger.info(f"NDVI mean:          {valid_ndvi.mean():.4f}")
    logger.info(f"NDVI median:        {np.median(valid_ndvi):.4f}")
    logger.info(f"NDVI std:           {valid_ndvi.std():.4f}")
    
    # Percentiles
    pcts = np.percentile(valid_ndvi, [5, 10, 25, 50, 75, 90, 95])
    logger.info(f"")
    logger.info(f"Percentiles: p5={pcts[0]:.3f}, p25={pcts[2]:.3f}, p50={pcts[3]:.3f}, p75={pcts[4]:.3f}, p95={pcts[6]:.3f}")
    logger.info("="*60)
    
    # Build metadata
    metadata = {
        "total_pixels": int(ndvi.size),
        "valid_pixels": int(valid_ndvi.size),
        "vegetation_pixels": int(vegetation_pixels.size),
        "vegetation_fraction": round(float(vegetation_fraction), 4),
        "ndvi_stats": {
            "mean": round(float(valid_ndvi.mean()), 6),
            "median": round(float(np.median(valid_ndvi)), 6),
            "std": round(float(valid_ndvi.std()), 6),
            "min": round(float(valid_ndvi.min()), 6),
            "max": round(float(valid_ndvi.max()), 6),
            "p5": round(float(pcts[0]), 6),
            "p10": round(float(pcts[1]), 6),
            "p25": round(float(pcts[2]), 6),
            "p75": round(float(pcts[4]), 6),
            "p90": round(float(pcts[5]), 6),
            "p95": round(float(pcts[6]), 6),
        },
        "preprocessing": {
            "smoothing_applied": apply_smoothing,
            "outliers_removed": remove_outliers,
            "vegetation_threshold": vegetation_threshold,
        }
    }
    
    return ndvi, metadata


def compute_ndvi_from_files(
    b04_path: str,
    b08_path: str,
    valid_mask_path: Optional[str] = None,
    output_path: Optional[str] = None,
    apply_smoothing: bool = True,
) -> Tuple[np.ndarray, dict]:
    """
    Compute NDVI from GeoTIFF files with robust preprocessing.
    
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
    
    # Compute NDVI with robust preprocessing
    ndvi, ndvi_metadata = compute_ndvi_robust(
        b04, b08, valid_mask,
        apply_smoothing=apply_smoothing,
        remove_outliers=True,
        vegetation_threshold=0.2
    )
    
    # Add spatial metadata
    ndvi_metadata.update({
        "b04_source": b04_path,
        "b08_source": b08_path,
        "valid_mask_source": valid_mask_path,
        "crs": str(crs),
        "transform": list(transform),
        "shape": list(ndvi.shape),
    })
    
    # Write NDVI raster if output path provided
    if output_path is not None:
        _write_ndvi_tif(ndvi, raster_meta, output_path)
        ndvi_metadata["ndvi_raster_path"] = output_path
    
    return ndvi, ndvi_metadata


def _write_ndvi_tif(ndvi: np.ndarray, base_meta: dict, output_path: str):
    """Write NDVI float32 GeoTIFF. NaN values stored as nodata=-9999."""
    out_meta = base_meta.copy()
    out_meta.update({
        "dtype": "float32",
        "count": 1,
        "nodata": -9999.0,
        "compress": "lzw",
        "driver": "GTiff",
    })
    
    # Replace NaN with nodata before writing
    ndvi_out = ndvi.copy()
    ndvi_out[np.isnan(ndvi_out)] = -9999.0
    
    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(ndvi_out, 1)
    
    logger.info(f"NDVI raster saved: {output_path}")
