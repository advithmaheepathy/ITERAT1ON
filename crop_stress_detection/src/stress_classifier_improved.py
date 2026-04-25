"""
stress_classifier_improved.py
==============================
PRODUCTION-READY stress classification with vegetation filtering.

IMPROVEMENTS:
1. Vegetation filtering (NDVI > 0.2)
2. Fixed thresholds based on remote sensing standards
3. Tile-level filtering (skip tiles with <30% vegetation)
4. Accurate stressed pixel fraction calculation

THRESHOLDS (Production-Ready):
- NDVI < 0.2:        Non-vegetation (bare soil, rock, water remnants)
- 0.2 - 0.4:         Moderate stress
- 0.4 - 0.6:         Mild stress  
- NDVI > 0.6:        Healthy vegetation

Only vegetation pixels (NDVI > 0.2) are analyzed for stress.
"""

import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# PRODUCTION-READY THRESHOLDS
THRESHOLDS = {
    "vegetation_min": 0.2,      # Minimum NDVI for vegetation
    "moderate_stress_max": 0.4, # NDVI < 0.4 = moderate stress
    "mild_stress_max": 0.6,     # 0.4 <= NDVI < 0.6 = mild stress
    # NDVI >= 0.6 = healthy
}

# Stress class definitions
STRESS_CLASSES = {
    "non_vegetation": {"severity": 0, "label": "Non-Vegetation", "alert": False},
    "moderate_stress": {"severity": 2, "label": "Moderate Stress", "alert": True},
    "mild_stress": {"severity": 1, "label": "Mild Stress", "alert": False},
    "healthy": {"severity": 0, "label": "Healthy", "alert": False},
}


def classify_tile_improved(
    tile: dict,
    ndvi_array: np.ndarray,
    thresholds: Optional[dict] = None,
    min_vegetation_fraction: float = 0.3,
) -> dict:
    """
    Classify a tile with vegetation filtering and accurate stress calculation.
    
    IMPROVEMENTS:
    1. Extract actual NDVI pixels from tile bounds
    2. Filter vegetation pixels (NDVI > 0.2)
    3. Skip tiles with insufficient vegetation (<30%)
    4. Calculate accurate stressed pixel fraction
    
    Args:
        tile: Tile dict with bounds (row_start, row_end, col_start, col_end)
        ndvi_array: Full NDVI array (H, W)
        thresholds: Classification thresholds
        min_vegetation_fraction: Minimum vegetation fraction to process tile
    
    Returns:
        tile: Updated tile dict with classification results
    """
    
    if thresholds is None:
        thresholds = THRESHOLDS
    
    # Extract tile NDVI values
    row_start = tile["row_start"]
    row_end = tile["row_end"]
    col_start = tile["col_start"]
    col_end = tile["col_end"]
    
    tile_ndvi = ndvi_array[row_start:row_end, col_start:col_end]
    
    # Get valid (non-NaN) pixels
    valid_pixels = ~np.isnan(tile_ndvi)
    valid_ndvi = tile_ndvi[valid_pixels]
    
    total_pixels = tile_ndvi.size
    valid_count = valid_ndvi.size
    
    if valid_count == 0:
        return {
            **tile,
            "classification": {
                "error": "no_valid_pixels",
                "skip_reason": "All pixels are NaN (cloud/water/nodata)"
            }
        }
    
    # CRITICAL: Filter vegetation pixels (NDVI > threshold)
    veg_threshold = thresholds["vegetation_min"]
    vegetation_mask = valid_ndvi > veg_threshold
    vegetation_pixels = valid_ndvi[vegetation_mask]
    vegetation_count = vegetation_pixels.size
    vegetation_fraction = vegetation_count / total_pixels
    
    # Skip tiles with insufficient vegetation
    if vegetation_fraction < min_vegetation_fraction:
        return {
            **tile,
            "classification": {
                "skip": True,
                "skip_reason": f"Insufficient vegetation ({vegetation_fraction*100:.1f}% < {min_vegetation_fraction*100:.0f}%)",
                "vegetation_fraction": round(vegetation_fraction, 4),
            }
        }
    
    # Classify vegetation pixels
    moderate_stress = (vegetation_pixels >= veg_threshold) & (vegetation_pixels < thresholds["moderate_stress_max"])
    mild_stress = (vegetation_pixels >= thresholds["moderate_stress_max"]) & (vegetation_pixels < thresholds["mild_stress_max"])
    healthy = vegetation_pixels >= thresholds["mild_stress_max"]
    
    moderate_count = moderate_stress.sum()
    mild_count = mild_stress.sum()
    healthy_count = healthy.sum()
    
    # Calculate stressed fraction (moderate stress only, as per requirements)
    stressed_fraction = moderate_count / vegetation_count if vegetation_count > 0 else 0.0
    
    # Determine primary class based on mean NDVI of vegetation pixels
    mean_veg_ndvi = vegetation_pixels.mean()
    
    if mean_veg_ndvi < thresholds["moderate_stress_max"]:
        primary_class = "moderate_stress"
    elif mean_veg_ndvi < thresholds["mild_stress_max"]:
        primary_class = "mild_stress"
    else:
        primary_class = "healthy"
    
    class_info = STRESS_CLASSES[primary_class]
    
    classification = {
        "primary_class": primary_class,
        "label": class_info["label"],
        "severity": class_info["severity"],
        "is_alert_class": class_info["alert"],
        
        # NDVI statistics (vegetation pixels only)
        "ndvi_mean": round(float(mean_veg_ndvi), 4),
        "ndvi_median": round(float(np.median(vegetation_pixels)), 4),
        "ndvi_std": round(float(vegetation_pixels.std()), 4),
        "ndvi_min": round(float(vegetation_pixels.min()), 4),
        "ndvi_max": round(float(vegetation_pixels.max()), 4),
        
        # Pixel counts
        "total_pixels": int(total_pixels),
        "valid_pixels": int(valid_count),
        "vegetation_pixels": int(vegetation_count),
        "vegetation_fraction": round(vegetation_fraction, 4),
        
        # Stress distribution (within vegetation pixels)
        "moderate_stress_pixels": int(moderate_count),
        "mild_stress_pixels": int(mild_count),
        "healthy_pixels": int(healthy_count),
        "stressed_fraction": round(stressed_fraction, 4),  # Moderate stress only
        
        # Thresholds used
        "thresholds": thresholds,
    }
    
    return {**tile, "classification": classification}


def classify_tiles_improved(
    tiles: List[dict],
    ndvi_array: np.ndarray,
    thresholds: Optional[dict] = None,
    min_vegetation_fraction: float = 0.3,
) -> List[dict]:
    """
    Classify all tiles with vegetation filtering.
    
    Args:
        tiles: List of tile dicts from tiling.py
        ndvi_array: Full NDVI array
        thresholds: Classification thresholds
        min_vegetation_fraction: Minimum vegetation to process tile
    
    Returns:
        classified_tiles: List of tiles with classification results
    """
    
    if thresholds is None:
        thresholds = THRESHOLDS
    
    logger.info("="*60)
    logger.info("STEP 3: STRESS CLASSIFICATION (IMPROVED)")
    logger.info("="*60)
    logger.info(f"Thresholds:")
    logger.info(f"  Vegetation minimum:  NDVI > {thresholds['vegetation_min']}")
    logger.info(f"  Moderate stress:     NDVI < {thresholds['moderate_stress_max']}")
    logger.info(f"  Mild stress:         NDVI < {thresholds['mild_stress_max']}")
    logger.info(f"  Healthy:             NDVI >= {thresholds['mild_stress_max']}")
    logger.info(f"")
    logger.info(f"Minimum vegetation fraction: {min_vegetation_fraction*100:.0f}%")
    logger.info("="*60)
    
    classified = []
    skipped = 0
    
    for tile in tiles:
        classified_tile = classify_tile_improved(
            tile, ndvi_array, thresholds, min_vegetation_fraction
        )
        
        # Check if tile was skipped
        if "skip" in classified_tile.get("classification", {}):
            skipped += 1
        
        classified.append(classified_tile)
    
    # Log classification summary
    valid_tiles = [t for t in classified if "skip" not in t.get("classification", {})]
    
    if len(valid_tiles) == 0:
        logger.warning("No tiles with sufficient vegetation!")
        return classified
    
    class_counts = {}
    for t in valid_tiles:
        cls = t["classification"].get("primary_class", "unknown")
        class_counts[cls] = class_counts.get(cls, 0) + 1
    
    logger.info("")
    logger.info("Classification Summary:")
    logger.info(f"  Total tiles:        {len(tiles)}")
    logger.info(f"  Skipped (low veg):  {skipped}")
    logger.info(f"  Classified:         {len(valid_tiles)}")
    logger.info("")
    
    for cls, count in sorted(class_counts.items()):
        label = STRESS_CLASSES.get(cls, {}).get("label", cls)
        pct = count / len(valid_tiles) * 100
        logger.info(f"  {label:20s}: {count:3d} tiles ({pct:5.1f}%)")
    
    logger.info("="*60)
    
    return classified
