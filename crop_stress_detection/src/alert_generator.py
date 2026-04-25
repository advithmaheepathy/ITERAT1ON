"""
alert_generator.py
==================
Generate crop stress alerts from classified tiles.

Alert rules (from pipeline_config.yaml):
  1. Tile must have sufficient valid data (min_valid_pixel_fraction)
  2. Tile must contain enough vegetated area (min_vegetated_fraction)
  3. Estimated stressed fraction must exceed threshold (stress_fraction_threshold)
  4. Classification must be an alert-level class (severe or moderate stress)

Alert fields are derived ONLY from computed tile data.
No fields are fabricated.
"""

import logging
from datetime import timezone, datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


DEFAULT_ALERT_CONFIG = {
    "min_valid_pixel_fraction": 0.70,
    "min_vegetated_fraction": 0.30,
    "stress_fraction_threshold": 0.40,
}


def generate_alerts(
    classified_tiles: List[dict],
    alert_config: Optional[dict] = None,
    processing_timestamp: Optional[str] = None,
) -> List[dict]:
    """
    Generate alerts from classified tiles.
    
    Args:
        classified_tiles: output of stress_classifier.classify_tiles()
        alert_config: dict with alert thresholds (or None for defaults)
        processing_timestamp: ISO 8601 timestamp of when processing ran
    
    Returns:
        List of alert dicts, one per qualifying tile.
    """
    if alert_config is None:
        alert_config = DEFAULT_ALERT_CONFIG
    
    if processing_timestamp is None:
        processing_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    alerts = []
    skipped_reasons = {}
    
    for tile in classified_tiles:
        cls = tile.get("classification", {})
        
        if "error" in cls:
            _count_skip(skipped_reasons, "no_valid_pixels")
            continue
        
        # Rule 1: Sufficient valid data
        valid_frac = tile.get("valid_pixel_fraction", 0)
        if valid_frac < alert_config["min_valid_pixel_fraction"]:
            _count_skip(skipped_reasons, f"insufficient_valid_pixels ({valid_frac:.2f})")
            continue
        
        # Rule 2: Sufficient vegetated area
        total_ha = tile.get("total_valid_ha", 0)
        vegetated_ha = tile.get("vegetated_ha", 0)
        vegetated_frac = vegetated_ha / total_ha if total_ha > 0 else 0
        if vegetated_frac < alert_config["min_vegetated_fraction"]:
            _count_skip(skipped_reasons, "insufficient_vegetation")
            continue
        
        # Rule 3: Stress fraction above threshold
        stressed_frac = cls.get("stressed_fraction_estimate", 0)
        if stressed_frac < alert_config["stress_fraction_threshold"]:
            _count_skip(skipped_reasons, "stress_below_threshold")
            continue
        
        # Rule 4: Alert-level class
        if not cls.get("is_alert_class", False):
            _count_skip(skipped_reasons, "not_alert_class")
            continue
        
        # All conditions met → generate alert
        severity = cls["severity"]
        severity_label = {3: "CRITICAL", 2: "WARNING", 1: "WATCH"}.get(severity, "INFO")
        
        alert = {
            "alert_id": f"ALERT_{tile['tile_id']}",
            "severity": severity_label,
            "severity_score": severity,  # 1-3, derived from classification
            "tile_id": tile["tile_id"],
            
            # Geographic location — from rasterio transform, not invented
            "location": {
                "center_lat": tile["center_lat"],
                "center_lon": tile["center_lon"],
                "bbox": {
                    "lat_min": tile["lat_min"],
                    "lat_max": tile["lat_max"],
                    "lon_min": tile["lon_min"],
                    "lon_max": tile["lon_max"],
                }
            },
            
            # Stress metrics — all derived from actual NDVI computation
            "ndvi_mean": cls["mean_ndvi"],
            "ndvi_median": tile["ndvi_stats"]["median"],
            "ndvi_std": tile["ndvi_stats"]["std"],
            "stressed_pixel_fraction": cls["stressed_fraction_estimate"],
            "stress_class": cls["primary_class"],
            "stress_label": cls["label"],
            
            # Data quality info
            "valid_pixel_fraction": round(valid_frac, 4),
            "vegetated_fraction": round(vegetated_frac, 4),
            "vegetated_ha": tile["vegetated_ha"],
            
            # Reasoning — generated from actual computed values
            "reason": _build_reason(cls, tile, vegetated_ha),
            
            # Metadata
            "detected_at": processing_timestamp,
            "alert_rules_applied": {
                "min_valid_pixel_fraction": alert_config["min_valid_pixel_fraction"],
                "min_vegetated_fraction": alert_config["min_vegetated_fraction"],
                "stress_fraction_threshold": alert_config["stress_fraction_threshold"],
            }
        }
        
        alerts.append(alert)
    
    # Log summary
    logger.info(f"Generated {len(alerts)} alerts from {len(classified_tiles)} tiles")
    if skipped_reasons:
        logger.info("Tiles skipped (no alert):")
        for reason, count in sorted(skipped_reasons.items()):
            logger.info(f"  {reason}: {count}")
    
    # Sort by severity (highest first), then by stressed fraction
    alerts.sort(key=lambda a: (-a["severity_score"], -a["stressed_pixel_fraction"]))
    
    return alerts


def _build_reason(cls: dict, tile: dict, vegetated_ha: float) -> str:
    """
    Build a human-readable alert reason from computed values.
    No fabrication — all numbers are from computed results.
    """
    mean_ndvi = cls["mean_ndvi"]
    stressed_frac = cls["stressed_fraction_estimate"]
    label = cls["label"]
    
    return (
        f"{label} detected. "
        f"Mean NDVI={mean_ndvi:.3f}. "
        f"Approximately {stressed_frac*100:.0f}% of vegetated pixels fall below "
        f"moderate-stress threshold (NDVI<{cls['thresholds_used']['moderate_stress_max']}). "
        f"Vegetated area: {vegetated_ha:.1f} ha."
    )


def _count_skip(reasons: dict, reason: str):
    reasons[reason] = reasons.get(reason, 0) + 1