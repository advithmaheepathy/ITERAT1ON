"""
alert_generator_improved.py
============================
PRODUCTION-READY alert generation with strict filtering.

IMPROVEMENTS:
1. Strict vegetation filtering (>= 30%)
2. Strict stress threshold (>= 40% stressed pixels)
3. Only moderate stress triggers alerts (not mild)
4. Clear severity mapping (CRITICAL vs WARNING)
5. Detailed alert reasoning

ALERT RULES:
- vegetated_fraction >= 0.3 (30% of tile must be vegetation)
- stressed_fraction >= 0.4 (40% of vegetation must be stressed)
- Only moderate stress class triggers alerts

SEVERITY:
- Moderate stress → WARNING
- (Severe stress would be CRITICAL, but we don't have that class with current thresholds)
"""

import logging
from datetime import timezone, datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# Alert configuration
ALERT_CONFIG = {
    "min_vegetation_fraction": 0.3,   # 30% of tile must be vegetation
    "min_stressed_fraction": 0.4,     # 40% of vegetation must be stressed
}


def generate_alerts_improved(
    classified_tiles: List[dict],
    alert_config: Optional[dict] = None,
    processing_timestamp: Optional[str] = None,
) -> List[dict]:
    """
    Generate alerts with strict filtering rules.
    
    ALERT CRITERIA (ALL must be met):
    1. Tile has >= 30% vegetation
    2. Tile has >= 40% stressed pixels (within vegetation)
    3. Primary class is "moderate_stress" (alert-level)
    
    Args:
        classified_tiles: Output from stress_classifier_improved
        alert_config: Alert thresholds
        processing_timestamp: ISO 8601 timestamp
    
    Returns:
        alerts: List of alert dicts
    """
    
    if alert_config is None:
        alert_config = ALERT_CONFIG
    
    if processing_timestamp is None:
        processing_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    logger.info("="*60)
    logger.info("STEP 4: ALERT GENERATION (IMPROVED)")
    logger.info("="*60)
    logger.info(f"Alert rules:")
    logger.info(f"  Min vegetation fraction:  {alert_config['min_vegetation_fraction']*100:.0f}%")
    logger.info(f"  Min stressed fraction:    {alert_config['min_stressed_fraction']*100:.0f}%")
    logger.info(f"  Alert classes:            moderate_stress")
    logger.info("="*60)
    
    alerts = []
    skip_reasons = {}
    
    for tile in classified_tiles:
        cls = tile.get("classification", {})
        
        # Skip tiles with errors or insufficient data
        if "error" in cls or "skip" in cls:
            reason = cls.get("skip_reason", cls.get("error", "unknown"))
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        
        # Rule 1: Check vegetation fraction
        veg_fraction = cls.get("vegetation_fraction", 0)
        if veg_fraction < alert_config["min_vegetation_fraction"]:
            skip_reasons["insufficient_vegetation"] = skip_reasons.get("insufficient_vegetation", 0) + 1
            continue
        
        # Rule 2: Check stressed fraction
        stressed_fraction = cls.get("stressed_fraction", 0)
        if stressed_fraction < alert_config["min_stressed_fraction"]:
            skip_reasons["stress_below_threshold"] = skip_reasons.get("stress_below_threshold", 0) + 1
            continue
        
        # Rule 3: Check if alert-level class
        if not cls.get("is_alert_class", False):
            skip_reasons["not_alert_class"] = skip_reasons.get("not_alert_class", 0) + 1
            continue
        
        # ALL RULES PASSED → Generate alert
        
        # Determine severity
        primary_class = cls["primary_class"]
        if primary_class == "moderate_stress":
            severity = "WARNING"
            severity_score = 2
        else:
            # Fallback (shouldn't happen with current thresholds)
            severity = "INFO"
            severity_score = 1
        
        alert = {
            "alert_id": f"ALERT_{tile['tile_id']}_{processing_timestamp.replace(':', '').replace('-', '')}",
            "severity": severity,
            "severity_score": severity_score,
            "tile_id": tile["tile_id"],
            
            # Location
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
            
            # Stress metrics
            "ndvi_mean": cls["ndvi_mean"],
            "ndvi_median": cls["ndvi_median"],
            "ndvi_std": cls["ndvi_std"],
            "stressed_fraction": cls["stressed_fraction"],
            "stress_class": cls["primary_class"],
            "stress_label": cls["label"],
            
            # Vegetation info
            "vegetation_fraction": cls["vegetation_fraction"],
            "vegetation_pixels": cls["vegetation_pixels"],
            "vegetated_ha": tile.get("vegetated_ha", 0),
            
            # Pixel breakdown
            "moderate_stress_pixels": cls["moderate_stress_pixels"],
            "mild_stress_pixels": cls["mild_stress_pixels"],
            "healthy_pixels": cls["healthy_pixels"],
            
            # Reasoning
            "reason": _build_alert_reason(cls, tile),
            
            # Metadata
            "detected_at": processing_timestamp,
            "alert_rules": alert_config,
        }
        
        alerts.append(alert)
    
    # Log summary
    logger.info("")
    logger.info(f"Alerts generated: {len(alerts)}")
    logger.info(f"Tiles processed:  {len(classified_tiles)}")
    logger.info("")
    
    if skip_reasons:
        logger.info("Tiles skipped (no alert):")
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            logger.info(f"  {reason:40s}: {count:3d} tiles")
    
    logger.info("="*60)
    
    # Sort by severity and stressed fraction
    alerts.sort(key=lambda a: (-a["severity_score"], -a["stressed_fraction"]))
    
    return alerts


def _build_alert_reason(cls: dict, tile: dict) -> str:
    """Build human-readable alert reason."""
    
    ndvi_mean = cls["ndvi_mean"]
    stressed_frac = cls["stressed_fraction"]
    veg_frac = cls["vegetation_fraction"]
    label = cls["label"]
    veg_ha = tile.get("vegetated_ha", 0)
    
    return (
        f"{label} detected in tile {tile['tile_id']}. "
        f"Mean NDVI = {ndvi_mean:.3f}. "
        f"{stressed_frac*100:.0f}% of vegetation pixels show stress (NDVI < 0.4). "
        f"Vegetated area: {veg_ha:.1f} ha ({veg_frac*100:.0f}% of tile). "
        f"Recommend field inspection and possible intervention."
    )
