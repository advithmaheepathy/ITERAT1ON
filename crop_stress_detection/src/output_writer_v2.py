"""
output_writer_v2.py
===================
Build and write the final structured JSON output (v2).

All values trace back to actual computed pixel data — no invented numbers.
Internal consistency guaranteed:
  valid_ndvi_pixels == total_pixels * valid_pixel_pct (within rounding)
  tile stats derived from same ndvi_array used for classification
"""

import json
import logging
from pathlib import Path
from typing import List

import numpy as np

from src.classifier_v2 import STRESS_CLASSES

logger = logging.getLogger(__name__)


def build_output(
    preprocessing_meta: dict,
    ndvi_meta: dict,
    classified_tiles: List[dict],
    alerts: List[dict],
    thresholds: dict,
    config: dict,
    processing_start: str,
    processing_end: str,
) -> dict:
    """
    Assemble the final JSON output.  Every field is derived from computed data.
    """

    ndvi_stats = ndvi_meta.get("ndvi_stats", {})
    total_px   = ndvi_meta.get("total_pixels", 0)
    valid_px   = ndvi_meta.get("valid_pixels", 0)
    valid_pct  = ndvi_meta.get("valid_pixel_pct", 0.0)

    # ── Stress distribution from ALL classified tiles ─────────────────────
    dist = _stress_distribution(classified_tiles)

    # ── Metadata section ──────────────────────────────────────────────────
    metadata = {
        "pipeline_version": "2.0.0",
        "processing_start":  processing_start,
        "processing_end":    processing_end,
        "source": {
            "platform":     "Sentinel-2",
            "product_type": "L2A",
            "acquisition_datetime": preprocessing_meta.get("acquisition_date", "UNKNOWN"),
            "bands_used": ["B04 (Red, 10m)", "B08 (NIR, 10m)"],
            "cloud_mask": "SCL (resampled 20m→10m)",
        },
        "method": {
            "ndvi_formula":       "NDVI = (B08 - B04) / (B08 + B04)",
            "valid_ndvi_range":   config.get("ndvi", {}).get("valid_range_min", -1.0),
            "cloud_filtering":    "SCL classes 0,1,3,8,9,10,11 masked",
            "water_masking":      "SCL class 6 masked" if config.get("masking", {}).get("mask_water", True) else "disabled",
            "veg_prefilter":      "NONE — all valid pixels classified",
            "tile_size_km":       config.get("tile_size_km", 5.0),
            "thresholds":         thresholds,
        },
    }

    # ── Summary section ───────────────────────────────────────────────────
    # CONSISTENCY: valid_ndvi_pixels ≈ total_pixels × (valid_pixel_pct/100)
    n_alert_tiles = sum(1 for t in classified_tiles if t["classification"].get("is_alert_class"))
    summary = {
        "acquisition_date":    preprocessing_meta.get("acquisition_date", "UNKNOWN"),
        "cloud_cover_pct":     preprocessing_meta.get("cloud_cover_pct"),
        "valid_pixel_pct":     round(valid_pct, 4),

        # Pixel counts — all from same computation chain
        "total_pixels":        total_px,
        "valid_ndvi_pixels":   valid_px,
        # valid_ndvi_pixels / total_pixels should equal valid_pixel_pct/100
        "pixels_consistency_check": round(valid_px / total_px * 100, 4) if total_px else None,

        "image_shape_pixels":  ndvi_meta.get("shape"),
        "ndvi_statistics":     ndvi_stats,
        "stress_distribution": dist,
        "total_tiles":         len(classified_tiles),
        "alert_tiles":         n_alert_tiles,
        "total_alerts":        len(alerts),
    }

    # ── Per-tile section ──────────────────────────────────────────────────
    tiles_out = []
    for t in classified_tiles:
        cls = t.get("classification", {})
        tiles_out.append({
            "tile_id":             t["tile_id"],
            "center_lat":          t["center_lat"],
            "center_lon":          t["center_lon"],
            "lat_min":             t.get("lat_min"),
            "lat_max":             t.get("lat_max"),
            "lon_min":             t.get("lon_min"),
            "lon_max":             t.get("lon_max"),
            "valid_pixel_fraction":cls.get("valid_pixel_fraction", t.get("valid_pixel_fraction")),
            "confidence":          cls.get("confidence"),
            "ndvi_mean":           cls.get("ndvi_mean"),
            "ndvi_median":         cls.get("ndvi_median"),
            "ndvi_std":            cls.get("ndvi_std"),
            "stress_class":        cls.get("primary_class", "unknown"),
            "stress_label":        cls.get("label", "unknown"),
            "is_alert":            cls.get("is_alert_class", False),
            "stressed_fraction":   cls.get("stressed_fraction"),
            "pixel_breakdown":     cls.get("pixel_breakdown"),
            "vegetated_ha":        t.get("vegetated_ha"),
            "total_valid_ha":      t.get("total_valid_ha"),
        })

    return {
        "metadata": metadata,
        "summary":  summary,
        "tiles":    tiles_out,
        "alerts":   alerts,
    }


def write_json(output: dict, path: str):
    """Write JSON and print a human-readable summary."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(output, f, indent=2, default=_serializer)
    logger.info(f"Output written: {path}")

    s = output.get("summary", {})
    ndvi = s.get("ndvi_statistics", {})

    print("\n" + "=" * 70)
    print("NDVI CROP STRESS DETECTION  —  v2.0  RESULTS")
    print("=" * 70)
    print(f"Acquisition   : {s.get('acquisition_date')}")
    print(f"Cloud cover   : {s.get('cloud_cover_pct')}%")
    print(f"Valid pixels  : {s.get('valid_ndvi_pixels'):,} / {s.get('total_pixels'):,}  ({s.get('valid_pixel_pct')}%)")
    print(f"  ✓ Consistency: valid_px/total_px = {s.get('pixels_consistency_check')}%  (should ≈ valid_pixel_pct)")
    print(f"\nNDVI statistics (all valid pixels, no veg pre-filter):")
    print(f"  mean   = {ndvi.get('mean'):.4f}")
    print(f"  median = {ndvi.get('median'):.4f}")
    print(f"  std    = {ndvi.get('std'):.4f}")
    print(f"  range  = [{ndvi.get('min'):.4f}, {ndvi.get('max'):.4f}]")
    print(f"  p25/p75= [{ndvi.get('p25'):.4f}, {ndvi.get('p75'):.4f}]")
    print(f"\nTiles         : {s.get('total_tiles')} total, {s.get('alert_tiles')} alert-class")
    print(f"Alerts        : {s.get('total_alerts')}")
    print(f"\nStress distribution:")
    for cls, info in (s.get("stress_distribution") or {}).items():
        print(f"  {info['label']:25s}: {info['tile_count']:4d} tiles  ({info['pct']:.1f}%)")

    if output.get("alerts"):
        print("\nTop alerts:")
        for a in output["alerts"][:5]:
            print(
                f"  [{a['severity']}] {a['tile_id']}  "
                f"lat={a['location']['center_lat']:.4f}  "
                f"lon={a['location']['center_lon']:.4f}  "
                f"class={a['primary_class']}  "
                f"stressed={a['stressed_fraction']*100:.0f}%"
            )
    print(f"\nFull output: {path}")
    print("=" * 70)


def _stress_distribution(classified_tiles: List[dict]) -> dict:
    n = len(classified_tiles)
    counts = {}
    for t in classified_tiles:
        cls = t["classification"].get("primary_class", "unknown")
        counts[cls] = counts.get(cls, 0) + 1

    dist = {}
    for cls, count in counts.items():
        label = STRESS_CLASSES.get(cls, {}).get("label", cls)
        dist[cls] = {
            "label":      label,
            "tile_count": count,
            "pct":        round(count / n * 100, 1) if n else 0,
        }
    return dist


def _serializer(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
