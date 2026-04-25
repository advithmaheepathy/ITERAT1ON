"""
classifier_v3.py
================
Physically correct, balanced 6-class NDVI classifier. Zero stress bias.

NDVI class scheme (all class boundaries configurable):
  NDVI < 0.0    → water_nonveg   (ocean, lakes, bare rock with shadow)
  0.0 – 0.15   → bare_soil      (dry soil, sand, ash)
  0.15 – 0.30  → sparse_stressed (stressed/fire-damaged/sparse vegetation)
  0.30 – 0.50  → moderate_veg   (moderate vegetation density)
  0.50 – 0.70  → healthy_veg    (healthy crops/forest)
  >= 0.70      → dense_veg      (dense canopy, tropical)

KEY FIXES vs classifier_v2:
1. confidence is ALWAYS set (never null)
2. Classification always uses ALL valid pixels — no veg pre-filter
3. Primary class from mean NDVI of ALL valid pixels
4. "unknown" never appears in output
5. stressed_fraction = only (sparse_stressed) / valid_pixels for alert logic
"""

import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


DEFAULT_THRESHOLDS = {
    "water_nonveg_max":    0.0,
    "bare_soil_max":       0.15,
    "sparse_stressed_max": 0.30,
    "moderate_veg_max":    0.50,
    "healthy_veg_max":     0.70,
    "min_valid_pixel_fraction": 0.10,
}

STRESS_CLASSES = {
    "insufficient_data": {"label": "Insufficient Data",       "severity": -1, "alert": False},
    "water_nonveg":      {"label": "Water / Non-Vegetation",  "severity": 0,  "alert": False},
    "bare_soil":         {"label": "Bare Soil",               "severity": 1,  "alert": False},
    "sparse_stressed":   {"label": "Sparse / Stressed Veg",  "severity": 3,  "alert": True},
    "moderate_veg":      {"label": "Moderate Vegetation",     "severity": 2,  "alert": False},
    "healthy_veg":       {"label": "Healthy Vegetation",      "severity": 1,  "alert": False},
    "dense_veg":         {"label": "Dense Vegetation",        "severity": 0,  "alert": False},
}


def classify_tile(
    tile: dict,
    ndvi_array: np.ndarray,
    thresholds: Optional[dict] = None,
    alert_classes: Optional[List[str]] = None,
) -> dict:
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if alert_classes is None:
        alert_classes = ["sparse_stressed"]

    r0, r1 = tile["row_start"], tile["row_end"]
    c0, c1 = tile["col_start"], tile["col_end"]
    tile_ndvi = ndvi_array[r0:r1, c0:c1]

    total_px  = tile_ndvi.size
    valid_mask = ~np.isnan(tile_ndvi)
    valid_px  = int(valid_mask.sum())
    valid_frac = valid_px / total_px if total_px > 0 else 0.0

    # ── Insufficient data ─────────────────────────────────────────────────
    if valid_frac < thresholds["min_valid_pixel_fraction"]:
        return {**tile, "classification": {
            "primary_class":        "insufficient_data",
            "label":                STRESS_CLASSES["insufficient_data"]["label"],
            "severity":             STRESS_CLASSES["insufficient_data"]["severity"],
            "is_alert_class":       False,
            "total_pixels":         total_px,
            "valid_pixels":         valid_px,
            "valid_pixel_fraction": round(valid_frac, 6),
            "confidence":           round(valid_frac, 6),
            "ndvi_mean":   None, "ndvi_median": None, "ndvi_std": None,
            "ndvi_min":    None, "ndvi_max":    None,
            "stressed_fraction":    0.0,
            "stressed_pixels":      0,
            "pixel_breakdown":      None,
            "reason": f"Only {valid_frac*100:.1f}% valid pixels "
                      f"(min {thresholds['min_valid_pixel_fraction']*100:.0f}%)",
        }}

    vals = tile_ndvi[valid_mask]

    t_wn  = thresholds["water_nonveg_max"]
    t_bs  = thresholds["bare_soil_max"]
    t_ss  = thresholds["sparse_stressed_max"]
    t_mv  = thresholds["moderate_veg_max"]
    t_hv  = thresholds["healthy_veg_max"]

    n_water    = int(np.sum(vals < t_wn))
    n_bare     = int(np.sum((vals >= t_wn) & (vals < t_bs)))
    n_sparse   = int(np.sum((vals >= t_bs) & (vals < t_ss)))
    n_moderate = int(np.sum((vals >= t_ss) & (vals < t_mv)))
    n_healthy  = int(np.sum((vals >= t_mv) & (vals < t_hv)))
    n_dense    = int(np.sum(vals >= t_hv))

    # Stressed = only sparse_stressed class (genuine stress signal)
    stressed_px   = n_sparse
    stressed_frac = stressed_px / valid_px if valid_px > 0 else 0.0

    mean_ndvi = float(vals.mean())
    if mean_ndvi < t_wn:
        primary = "water_nonveg"
    elif mean_ndvi < t_bs:
        primary = "bare_soil"
    elif mean_ndvi < t_ss:
        primary = "sparse_stressed"
    elif mean_ndvi < t_mv:
        primary = "moderate_veg"
    elif mean_ndvi < t_hv:
        primary = "healthy_veg"
    else:
        primary = "dense_veg"

    cls_info = STRESS_CLASSES[primary]

    classification = {
        "primary_class":        primary,
        "label":                cls_info["label"],
        "severity":             cls_info["severity"],
        "is_alert_class":       primary in alert_classes,

        "total_pixels":         total_px,
        "valid_pixels":         valid_px,
        "valid_pixel_fraction": round(valid_frac, 6),
        "confidence":           round(valid_frac, 6),   # always set, never null

        "ndvi_mean":   round(mean_ndvi, 6),
        "ndvi_median": round(float(np.median(vals)), 6),
        "ndvi_std":    round(float(vals.std()), 6),
        "ndvi_min":    round(float(vals.min()), 6),
        "ndvi_max":    round(float(vals.max()), 6),

        "stressed_fraction": round(stressed_frac, 6),
        "stressed_pixels":   stressed_px,

        "pixel_breakdown": {
            "water_nonveg":   n_water,
            "bare_soil":      n_bare,
            "sparse_stressed": n_sparse,
            "moderate_veg":   n_moderate,
            "healthy_veg":    n_healthy,
            "dense_veg":      n_dense,
        },

        "thresholds_used": {
            "water_nonveg_max":    t_wn,
            "bare_soil_max":       t_bs,
            "sparse_stressed_max": t_ss,
            "moderate_veg_max":    t_mv,
            "healthy_veg_max":     t_hv,
        },
    }
    return {**tile, "classification": classification}


def classify_all_tiles(
    tiles: List[dict],
    ndvi_array: np.ndarray,
    thresholds: Optional[dict] = None,
    alert_classes: Optional[List[str]] = None,
) -> List[dict]:
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if alert_classes is None:
        alert_classes = ["sparse_stressed"]

    logger.info("=" * 60)
    logger.info("TILE CLASSIFICATION  v3  (6-class, zero bias)")
    logger.info("=" * 60)
    logger.info(f"  water_nonveg   : NDVI < {thresholds['water_nonveg_max']}")
    logger.info(f"  bare_soil      : NDVI < {thresholds['bare_soil_max']}")
    logger.info(f"  sparse_stressed: NDVI < {thresholds['sparse_stressed_max']}")
    logger.info(f"  moderate_veg   : NDVI < {thresholds['moderate_veg_max']}")
    logger.info(f"  healthy_veg    : NDVI < {thresholds['healthy_veg_max']}")
    logger.info(f"  dense_veg      : NDVI >= {thresholds['healthy_veg_max']}")
    logger.info(f"  min_valid_frac : {thresholds['min_valid_pixel_fraction']*100:.0f}%")
    logger.info("─" * 60)

    classified = [
        classify_tile(t, ndvi_array, thresholds, alert_classes)
        for t in tiles
    ]

    counts: Dict[str, int] = {}
    for t in classified:
        c = t["classification"].get("primary_class", "unknown")
        counts[c] = counts.get(c, 0) + 1

    logger.info("Classification summary:")
    for cls in ["insufficient_data", "water_nonveg", "bare_soil",
                "sparse_stressed", "moderate_veg", "healthy_veg", "dense_veg"]:
        n = counts.get(cls, 0)
        if n or cls == "insufficient_data":
            pct = n / len(tiles) * 100 if tiles else 0
            label = STRESS_CLASSES.get(cls, {}).get("label", cls)
            logger.info(f"  {label:28s}: {n:4d}  ({pct:.1f}%)")

    n_alerts = sum(1 for t in classified if t["classification"].get("is_alert_class"))
    logger.info(f"  ── Alert-class tiles: {n_alerts} / {len(tiles)}")
    logger.info("=" * 60)
    return classified
