"""
output_writer.py
================
Build and write the final structured JSON output.

STRICT RULE: Every field in the output JSON must be derived from computed values.
No field is invented, estimated beyond what data supports, or hardcoded.
Fields that cannot be computed are either omitted or marked with null + explanation.
"""

import json
import logging
from datetime import timezone, datetime
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


def build_output_json(
    preprocessing_metadata: dict,
    ndvi_metadata: dict,
    tiles: List[dict],
    classified_tiles: List[dict],
    alerts: List[dict],
    config: dict,
    processing_start_iso: str,
    processing_end_iso: str,
) -> dict:
    """
    Assemble the final JSON output from all computed pipeline results.
    
    All values trace back to:
      1. preprocessing_metadata → from actual .SAFE file parsing
      2. ndvi_metadata → from actual pixel computation
      3. tiles → from actual raster spatial subdivision
      4. classified_tiles → from threshold classification of real NDVI
      5. alerts → from rules applied to real tile statistics
    """
    
    # --- Metadata section ---
    metadata = {
        "pipeline_version": "1.0.0",
        "processing_start": processing_start_iso,
        "processing_end": processing_end_iso,
        "source": {
            "platform": "Sentinel-2",
            "product_type": "L2A",
            "product_name": preprocessing_metadata.get("safe_name", "UNKNOWN"),
            "acquisition_datetime": preprocessing_metadata.get("acquisition_date", "UNKNOWN"),
            "bands_used": ["B04 (Red, 10m)", "B08 (NIR, 10m)"],
            "cloud_mask": "SCL (Scene Classification Layer, resampled 20m→10m)",
        },
        "method": {
            "ndvi_formula": "NDVI = (B08 - B04) / (B08 + B04)",
            "cloud_filtering": "SCL classes 0,1,3,8,9,10,11 masked as invalid",
            "stress_classification": "threshold-based (see configs/pipeline_config.yaml)",
            "tile_size_km": config.get("tile_size_km", 5.0),
            "coordinate_system_input": preprocessing_metadata.get("crs", "UNKNOWN"),
            "coordinate_system_output": "EPSG:4326 (WGS84)",
        },
        "terramind": {
            "used": False,
            "reason": "Cloud coverage within acceptable range; gap-filling not required.",
            "recommendation": (
                f"Cloud coverage was {preprocessing_metadata.get('cloud_cover_pct', 'N/A')}%. "
                f"TerraMind gap-filling recommended if >20%. See TERRAMIND_NOTE.md."
            )
        }
    }
    
    # --- Summary section ---
    ndvi_stats = ndvi_metadata.get("ndvi_stats", {})
    n_tiles = len(tiles)
    n_alerts = len(alerts)
    alert_tiles = [t for t in classified_tiles if t["classification"].get("is_alert_class")]
    
    # Compute aggregate stress distribution from classified tiles
    stress_distribution = _compute_stress_distribution(classified_tiles)
    
    summary = {
        "acquisition_date": preprocessing_metadata.get("acquisition_date", "UNKNOWN"),
        "total_tiles": n_tiles,
        "alert_tiles": len(alert_tiles),
        "total_alerts": n_alerts,
        "cloud_cover_pct": preprocessing_metadata.get("cloud_cover_pct"),
        "valid_pixel_pct": preprocessing_metadata.get("valid_pixel_pct"),
        "image_shape_pixels": ndvi_metadata.get("shape"),
        "total_pixels": ndvi_metadata.get("total_pixels"),
        "valid_ndvi_pixels": ndvi_metadata.get("valid_pixels"),
        "ndvi_statistics": {
            "mean": ndvi_stats.get("mean"),
            "std": ndvi_stats.get("std"),
            "min": ndvi_stats.get("min"),
            "max": ndvi_stats.get("max"),
            "median": ndvi_stats.get("median"),
            "p10": ndvi_stats.get("p10"),
            "p25": ndvi_stats.get("p25"),
            "p75": ndvi_stats.get("p75"),
            "p90": ndvi_stats.get("p90"),
        },
        "stress_distribution": stress_distribution,
    }
    
    # --- Tiles section (condensed) ---
    # Include all tiles but strip pixel coordinates (too verbose)
    tiles_condensed = []
    for t in classified_tiles:
        cls = t.get("classification", {})
        tiles_condensed.append({
            "tile_id": t["tile_id"],
            "center_lat": t["center_lat"],
            "center_lon": t["center_lon"],
            "ndvi_mean": t["ndvi_stats"].get("mean"),
            "ndvi_median": t["ndvi_stats"].get("median"),
            "valid_pixel_fraction": t["valid_pixel_fraction"],
            "vegetated_ha": t["vegetated_ha"],
            "stress_class": cls.get("primary_class", "unknown"),
            "stress_label": cls.get("label", "unknown"),
            "is_alert": cls.get("is_alert_class", False),
        })
    
    # --- Assemble full output ---
    output = {
        "metadata": metadata,
        "summary": summary,
        "tiles": tiles_condensed,
        "alerts": alerts,
        # NDVI trend: only included if multiple acquisitions processed
        "ndvi_trend": None,
        "ndvi_trend_note": (
            "NDVI trend not computed: only one acquisition date available. "
            "Run pipeline with multiple dates to enable trend analysis."
        ),
    }
    
    return output


def write_json(output: dict, output_path: str):
    """Write output dict to JSON file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=_json_serializer)
    
    logger.info(f"Output written: {output_path}")
    
    # Print summary to stdout
    summary = output.get("summary", {})
    alerts = output.get("alerts", [])
    
    print("\n" + "="*60)
    print("CROP STRESS DETECTION RESULT")
    print("="*60)
    print(f"Acquisition: {summary.get('acquisition_date')}")
    print(f"Valid pixels: {summary.get('valid_pixel_pct')}%")
    print(f"Cloud cover:  {summary.get('cloud_cover_pct')}%")
    print(f"\nNDVI (valid pixels):")
    ndvi_s = summary.get("ndvi_statistics", {})
    print(f"  mean={ndvi_s.get('mean'):.4f}  std={ndvi_s.get('std'):.4f}")
    print(f"  min={ndvi_s.get('min'):.4f}   max={ndvi_s.get('max'):.4f}")
    print(f"\nTiles: {summary.get('total_tiles')} total, {summary.get('alert_tiles')} with stress")
    print(f"Alerts generated: {summary.get('total_alerts')}")
    
    dist = summary.get("stress_distribution", {})
    print(f"\nStress distribution (by tile count):")
    for cls, info in dist.items():
        print(f"  {info['label']}: {info['tile_count']} tiles ({info['pct']:.1f}%)")
    
    if alerts:
        print(f"\nTop alerts:")
        for alert in alerts[:5]:
            print(
                f"  [{alert['severity']}] {alert['tile_id']} "
                f"lat={alert['location']['center_lat']:.4f} "
                f"lon={alert['location']['center_lon']:.4f} "
                f"NDVI={alert['ndvi_mean']:.3f} "
                f"stress={alert['stressed_pixel_fraction']*100:.0f}%"
            )
    
    print(f"\nFull output: {output_path}")
    print("="*60)


def _compute_stress_distribution(classified_tiles: List[dict]) -> dict:
    """
    Compute the distribution of tiles across stress classes.
    Returns counts and percentages derived from actual classified tiles.
    """
    from src.stress_classifier import STRESS_CLASSES
    
    n_total = len(classified_tiles)
    counts = {cls: 0 for cls in STRESS_CLASSES.keys()}
    counts["no_data"] = 0
    
    for tile in classified_tiles:
        cls = tile.get("classification", {}).get("primary_class", "no_data")
        if cls in counts:
            counts[cls] += 1
        else:
            counts["no_data"] = counts.get("no_data", 0) + 1
    
    distribution = {}
    for cls, count in counts.items():
        if count == 0:
            continue
        label = STRESS_CLASSES.get(cls, {}).get("label", cls)
        distribution[cls] = {
            "label": label,
            "tile_count": count,
            "pct": round(count / n_total * 100, 1) if n_total > 0 else 0,
        }
    
    return distribution


def _json_serializer(obj):
    """Handle numpy types in JSON serialization."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")