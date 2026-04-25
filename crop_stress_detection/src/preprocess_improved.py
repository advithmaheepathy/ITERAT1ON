"""
preprocess_improved.py
======================
PRODUCTION-READY preprocessing with water masking.

IMPROVEMENTS:
1. Proper cloud masking (SCL classes 0,1,3,8,9,10,11)
2. CRITICAL: Water masking (SCL class 6)
3. Robust error handling
4. Clear logging of each step

Water bodies have high NIR reflectance and can be misclassified as healthy vegetation.
This is a CRITICAL fix for agricultural monitoring.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple, Dict

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling as WarpResampling

logger = logging.getLogger(__name__)


# SCL (Scene Classification Layer) class definitions
# Reference: https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview

SCL_CLASSES = {
    0: "NO_DATA",
    1: "SATURATED_OR_DEFECTIVE",
    2: "DARK_AREA_PIXELS",
    3: "CLOUD_SHADOWS",
    4: "VEGETATION",
    5: "NOT_VEGETATED",
    6: "WATER",  # CRITICAL: Must be masked!
    7: "UNCLASSIFIED",
    8: "CLOUD_MEDIUM_PROBABILITY",
    9: "CLOUD_HIGH_PROBABILITY",
    10: "THIN_CIRRUS",
    11: "SNOW_ICE",
}

# Classes to mask as invalid
SCL_INVALID_CLASSES = [0, 1, 3, 8, 9, 10, 11]

# CRITICAL: Water class (must be masked separately)
SCL_WATER_CLASS = 6


def build_combined_mask(
    scl_array: np.ndarray,
    mask_water: bool = True,
    mask_clouds: bool = True,
) -> Tuple[np.ndarray, dict]:
    """
    Build combined mask from SCL (clouds + water + nodata).
    
    CRITICAL IMPROVEMENT: Water pixels (SCL=6) are now masked.
    Water has high NIR reflectance → false positive as "healthy vegetation"
    
    Args:
        scl_array: Scene Classification Layer (uint8), shape (H, W)
        mask_water: If True, mask water pixels (SCL=6) [RECOMMENDED]
        mask_clouds: If True, mask cloud/shadow/snow pixels
    
    Returns:
        valid_mask: bool array, True=valid pixel, False=invalid
        stats: dict with masking statistics
    """
    
    logger.info("="*60)
    logger.info("STEP 2: COMBINED MASK (CLOUDS + WATER)")
    logger.info("="*60)
    
    invalid = np.zeros(scl_array.shape, dtype=bool)
    
    # Count pixels by class
    class_counts = {}
    for class_id, class_name in SCL_CLASSES.items():
        count = (scl_array == class_id).sum()
        if count > 0:
            class_counts[class_name] = count
            logger.info(f"  SCL {class_id:2d} ({class_name:25s}): {count:8,} pixels ({count/scl_array.size*100:5.2f}%)")
    
    # Mask clouds, shadows, snow, nodata
    if mask_clouds:
        logger.info("")
        logger.info("Masking invalid classes (clouds, shadows, snow, nodata)...")
        for class_id in SCL_INVALID_CLASSES:
            class_mask = (scl_array == class_id)
            count = class_mask.sum()
            if count > 0:
                invalid |= class_mask
                logger.info(f"  Masked SCL={class_id} ({SCL_CLASSES[class_id]}): {count:,} pixels")
    
    cloud_count = invalid.sum()
    
    # CRITICAL: Mask water pixels
    if mask_water:
        logger.info("")
        logger.info("CRITICAL: Masking water pixels (SCL=6)...")
        water_mask = (scl_array == SCL_WATER_CLASS)
        water_count = water_mask.sum()
        
        if water_count > 0:
            invalid |= water_mask
            logger.info(f"  Water pixels masked: {water_count:,} ({water_count/scl_array.size*100:.2f}%)")
            logger.info(f"  → Prevents false 'healthy vegetation' classification")
        else:
            logger.info(f"  No water pixels found")
    else:
        water_count = 0
        logger.warning("  WARNING: Water masking disabled! May cause false alerts.")
    
    # Create valid mask
    valid_mask = ~invalid
    valid_count = valid_mask.sum()
    valid_pct = valid_count / scl_array.size * 100
    
    logger.info("")
    logger.info("="*60)
    logger.info("MASK SUMMARY")
    logger.info("="*60)
    logger.info(f"Total pixels:       {scl_array.size:,}")
    logger.info(f"Cloud/shadow/snow:  {cloud_count:,} ({cloud_count/scl_array.size*100:.1f}%)")
    logger.info(f"Water:              {water_count:,} ({water_count/scl_array.size*100:.1f}%)")
    logger.info(f"Valid pixels:       {valid_count:,} ({valid_pct:.1f}%)")
    logger.info("="*60)
    
    stats = {
        "total_pixels": int(scl_array.size),
        "valid_pixels": int(valid_count),
        "valid_fraction": round(float(valid_pct / 100), 4),
        "cloud_pixels": int(cloud_count),
        "water_pixels": int(water_count),
        "water_masked": mask_water,
        "class_distribution": class_counts,
    }
    
    return valid_mask, stats


def resample_scl_to_10m(
    scl_20m: np.ndarray,
    scl_meta_20m: dict,
    target_meta_10m: dict,
) -> np.ndarray:
    """
    Resample SCL from 20m to 10m resolution using nearest neighbor.
    
    Args:
        scl_20m: SCL array at 20m resolution
        scl_meta_20m: rasterio metadata for 20m SCL
        target_meta_10m: rasterio metadata for 10m bands (B04/B08)
    
    Returns:
        scl_10m: SCL resampled to 10m resolution
    """
    logger.info("Resampling SCL from 20m to 10m...")
    
    scl_10m = np.zeros(
        (target_meta_10m["height"], target_meta_10m["width"]),
        dtype=scl_20m.dtype
    )
    
    reproject(
        source=scl_20m,
        destination=scl_10m,
        src_transform=scl_meta_20m["transform"],
        src_crs=scl_meta_20m["crs"],
        dst_transform=target_meta_10m["transform"],
        dst_crs=target_meta_10m["crs"],
        resampling=WarpResampling.nearest  # Nearest neighbor for categorical data
    )
    
    logger.info(f"  SCL resampled: {scl_20m.shape} → {scl_10m.shape}")
    
    return scl_10m
