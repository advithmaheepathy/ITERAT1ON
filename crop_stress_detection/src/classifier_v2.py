"""
classifier_v2.py
================
Scientifically correct, unbiased per-tile NDVI stress classification.

KEY CHANGES from stress_classifier_improved.py:
1. NO global vegetation pre-filter before classification
   - Old code: skip tile if < 30% pixels have NDVI > 0.2 → "unknown"
   - New code: classify ALL valid pixels into 5 classes (bare soil through healthy)
2. Tile marked "insufficient_data" ONLY if valid_pixel_fraction < config threshold
   - e.g. < 10% valid pixels (heavily clouded tile)
3. Stressed fraction = (bare_soil + severe_stress + moderate_stress) / valid_pixels
   - Old code: stressed fraction was only within veg pixels → inflated
4. Consistent pixel counts throughout
5. Alert classes are configurable, not hardcoded

NDVI CLASS BOUNDARIES (from config):
  < bare_soil_max       → "bare_soil"        (non-vegetated)
  < severe_stress_max   → "severe_stress"
  < moderate_stress_max → "moderate_stress"
  < mild_stress_max     → "mild_stress"
  >= mild_stress_max    → "healthy"
"""

import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# Default thresholds — overridden by config at runtime
DEFAULT_THRESHOLDS = {
    "bare_soil_max":       0.15,
    "severe_stress_max":   0.30,
    "moderate_stress_max": 0.45,
    "mild_stress_max":     0.60,
    "min_valid_pixel_fraction": 0.10,
}

# Class definitions (label, severity 0–4, alert?)
STRESS_CLASSES = {
    "insufficient_data": {"label": "Insufficient Data",   "severity": -1, "alert": False},
    "bare_soil":         {"label": "Bare Soil",           "severity": 0,  "alert": False},
    "severe_stress":     {"label": "Severe Stress",       "severity": 4,  "alert": True},
    "moderate_stress":   {"label": "Moderate Stress",     "severity": 3,  "alert": True},
    "mild_stress":       {"label": "Mild Stress",         "severity": 2,  "alert": False},
    "healthy":           {"label": "Healthy Vegetation",  "severity": 1,  "alert": False},
}


def classify_tile(
    tile: dict,
    ndvi_array: np.ndarray,
    thresholds: Optional[dict] = None,
    alert_classes: Optional[List[str]] = None,
) -> dict:
    """
    Classify a single tile.

    Algorithm:
      1. Extract NDVI values from tile pixel bounds
      2. Count valid (non-NaN) pixels
      3. If valid_pixel_fraction < min_valid_pixel_fraction → insufficient_data
      4. Classify EVERY valid pixel into one of 5 NDVI classes
      5. Determine primary class from mean NDVI of ALL valid pixels
      6. Compute stressed_fraction = (stressed pixels) / (valid pixels)

    Args:
        tile        : dict with row_start/end, col_start/end, valid_pixel_fraction
        ndvi_array  : full scene NDVI (H, W), float32, NaN = invalid
        thresholds  : from config (or DEFAULT_THRESHOLDS)
        alert_classes: which classes trigger alerts

    Returns:
        tile dict updated with 'classification' key
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if alert_classes is None:
        alert_classes = ["severe_stress", "moderate_stress"]

    r0, r1 = tile["row_start"], tile["row_end"]
    c0, c1 = tile["col_start"], tile["col_end"]

    tile_ndvi = ndvi_array[r0:r1, c0:c1]
    total_px = tile_ndvi.size
    valid_mask = ~np.isnan(tile_ndvi)
    valid_px = int(valid_mask.sum())
    valid_frac = valid_px / total_px if total_px > 0 else 0.0

    # ── Insufficient data ──────────────────────────────────────────────────
    if valid_frac < thresholds["min_valid_pixel_fraction"]:
        cls_info = STRESS_CLASSES["insufficient_data"]
        classification = {
            "primary_class":      "insufficient_data",
            "label":              cls_info["label"],
            "severity":           cls_info["severity"],
            "is_alert_class":     cls_info["alert"],
            "total_pixels":       int(total_px),
            "valid_pixels":       valid_px,
            "valid_pixel_fraction": round(valid_frac, 4),
            "reason": f"Only {valid_frac*100:.1f}% valid pixels "
                      f"(threshold {thresholds['min_valid_pixel_fraction']*100:.0f}%)",
        }
        return {**tile, "classification": classification}

    # ── Pixel-level classification ────────────────────────────────────────
    vals = tile_ndvi[valid_mask]

    t_bs  = thresholds["bare_soil_max"]
    t_ss  = thresholds["severe_stress_max"]
    t_ms  = thresholds["moderate_stress_max"]
    t_mld = thresholds["mild_stress_max"]

    n_bare     = int(np.sum(vals < t_bs))
    n_severe   = int(np.sum((vals >= t_bs)  & (vals < t_ss)))
    n_moderate = int(np.sum((vals >= t_ss)  & (vals < t_ms)))
    n_mild     = int(np.sum((vals >= t_ms)  & (vals < t_mld)))
    n_healthy  = int(np.sum(vals >= t_mld))

    # Stressed pixels = bare_soil + severe + moderate (anything ≤ moderate_stress_max)
    n_stressed = n_bare + n_severe + n_moderate
    stressed_frac = n_stressed / valid_px if valid_px > 0 else 0.0

    # Primary class from mean NDVI of valid pixels
    mean_ndvi = float(vals.mean())
    if mean_ndvi < t_bs:
        primary = "bare_soil"
    elif mean_ndvi < t_ss:
        primary = "severe_stress"
    elif mean_ndvi < t_ms:
        primary = "moderate_stress"
    elif mean_ndvi < t_mld:
        primary = "mild_stress"
    else:
        primary = "healthy"

    cls_info = STRESS_CLASSES[primary]

    # Confidence = valid_pixel_fraction
    confidence = round(valid_frac, 4)

    classification = {
        "primary_class":   primary,
        "label":           cls_info["label"],
        "severity":        cls_info["severity"],
        "is_alert_class":  primary in alert_classes,

        # Core stats (ALL valid pixels — no veg filter)
        "ndvi_mean":   round(mean_ndvi, 6),
        "ndvi_median": round(float(np.median(vals)), 6),
        "ndvi_std":    round(float(vals.std()), 6),
        "ndvi_min":    round(float(vals.min()), 6),
        "ndvi_max":    round(float(vals.max()), 6),

        # Pixel counts (add to total_pixels → consistent)
        "total_pixels":   int(total_px),
        "valid_pixels":   valid_px,
        "valid_pixel_fraction": round(valid_frac, 4),
        "confidence":     confidence,

        # Class breakdown (all 5 classes, always present)
        "pixel_breakdown": {
            "bare_soil":       n_bare,
            "severe_stress":   n_severe,
            "moderate_stress": n_moderate,
            "mild_stress":     n_mild,
            "healthy":         n_healthy,
        },

        # Stressed fraction computed from ALL valid pixels (not just veg pixels)
        "stressed_fraction": round(stressed_frac, 4),
        "stressed_pixels":   n_stressed,

        # Thresholds used (for traceability)
        "thresholds_used": {
            "bare_soil_max":       t_bs,
            "severe_stress_max":   t_ss,
            "moderate_stress_max": t_ms,
            "mild_stress_max":     t_mld,
        },
    }
    return {**tile, "classification": classification}


def classify_all_tiles(
    tiles: List[dict],
    ndvi_array: np.ndarray,
    thresholds: Optional[dict] = None,
    alert_classes: Optional[List[str]] = None,
) -> List[dict]:
    """
    Classify all tiles. Returns list with classification on every tile.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if alert_classes is None:
        alert_classes = ["severe_stress", "moderate_stress"]

    logger.info("=" * 60)
    logger.info("TILE CLASSIFICATION  (v2 — all valid pixels)")
    logger.info("=" * 60)
    logger.info("Thresholds:")
    logger.info(f"  bare_soil       : NDVI < {thresholds['bare_soil_max']}")
    logger.info(f"  severe_stress   : NDVI < {thresholds['severe_stress_max']}")
    logger.info(f"  moderate_stress : NDVI < {thresholds['moderate_stress_max']}")
    logger.info(f"  mild_stress     : NDVI < {thresholds['mild_stress_max']}")
    logger.info(f"  healthy         : NDVI ≥ {thresholds['mild_stress_max']}")
    logger.info(f"  insufficient_data threshold: {thresholds['min_valid_pixel_fraction']*100:.0f}%")
    logger.info("─" * 60)

    classified = [
        classify_tile(t, ndvi_array, thresholds, alert_classes)
        for t in tiles
    ]

    # ── Summary ─────────────────────────────────────────────────────────────
    counts: Dict[str, int] = {}
    for t in classified:
        cls = t["classification"].get("primary_class", "unknown")
        counts[cls] = counts.get(cls, 0) + 1

    logger.info("Classification summary:")
    for cls, n in sorted(counts.items(), key=lambda x: -x[1]):
        label = STRESS_CLASSES.get(cls, {}).get("label", cls)
        pct = n / len(tiles) * 100
        logger.info(f"  {label:25s}: {n:4d} tiles  ({pct:.1f}%)")

    n_alerts = sum(
        1 for t in classified
        if t["classification"].get("is_alert_class", False)
    )
    logger.info(f"  ── Alert-class tiles: {n_alerts}")
    logger.info("=" * 60)
    return classified
