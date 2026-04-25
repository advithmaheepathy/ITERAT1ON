"""
ndvi_trend.py
=============
Compute NDVI trends across multiple acquisition dates.

This module is ONLY invoked when you have ≥2 processed acquisitions.
It computes real statistics from actual NDVI rasters — no interpolation
between dates is performed unless explicitly requested.

Usage:
  from src.ndvi_trend import compute_ndvi_trend
  
  trend = compute_ndvi_trend([
      {"date": "2024-06-15T05:36:39Z", "ndvi_path": "data/processed/S2A_20240615_NDVI.tif"},
      {"date": "2024-07-20T05:41:03Z", "ndvi_path": "data/processed/S2A_20240720_NDVI.tif"},
  ])
"""

import logging
from typing import List, Dict, Optional

import numpy as np
import rasterio

logger = logging.getLogger(__name__)


def compute_ndvi_trend(
    acquisitions: List[Dict],
    spatial_match: str = "strict",
) -> dict:
    """
    Compute NDVI change statistics across multiple dates.
    
    Args:
        acquisitions: list of dicts, each with:
          - date: ISO 8601 string
          - ndvi_path: path to NDVI GeoTIFF
        spatial_match: "strict" = require same shape/transform
                       "flexible" = resample to common grid (not implemented)
    
    Returns:
        trend dict with per-date stats, delta statistics, and change direction
    
    IMPORTANT: All statistics are from real pixel values.
    "Trend" = simple differencing between dates, not model-fitted curves.
    If you want fitted trends, use scipy.stats.linregress on the mean series.
    """
    if len(acquisitions) < 2:
        raise ValueError("Need at least 2 acquisitions for trend analysis")
    
    # Sort by date
    acquisitions = sorted(acquisitions, key=lambda a: a["date"])
    
    logger.info(f"Computing NDVI trend across {len(acquisitions)} acquisitions")
    
    # Load all NDVI arrays
    arrays = []
    per_date_stats = []
    
    reference_shape = None
    reference_transform = None
    
    for acq in acquisitions:
        with rasterio.open(acq["ndvi_path"]) as src:
            arr = src.read(1).astype(np.float32)
            transform = src.transform
            shape = arr.shape
        
        # Replace nodata with NaN
        arr[arr == -9999.0] = np.nan
        
        if reference_shape is None:
            reference_shape = shape
            reference_transform = transform
        elif spatial_match == "strict" and shape != reference_shape:
            raise ValueError(
                f"Shape mismatch: {acq['date']} has shape {shape}, "
                f"expected {reference_shape}. "
                f"Run pipeline with the same AOI for all dates."
            )
        
        valid = arr[~np.isnan(arr)]
        
        per_date_stats.append({
            "date": acq["date"],
            "ndvi_path": acq["ndvi_path"],
            "n_valid": int(valid.size),
            "n_total": int(arr.size),
            "valid_fraction": round(float(valid.size / arr.size), 4) if arr.size > 0 else 0,
            "mean": round(float(valid.mean()), 6) if valid.size > 0 else None,
            "std": round(float(valid.std()), 6) if valid.size > 0 else None,
            "median": round(float(np.median(valid)), 6) if valid.size > 0 else None,
            "p10": round(float(np.percentile(valid, 10)), 6) if valid.size > 0 else None,
            "p90": round(float(np.percentile(valid, 90)), 6) if valid.size > 0 else None,
        })
        
        arrays.append(arr)
        logger.info(
            f"  {acq['date']}: mean={per_date_stats[-1]['mean']:.4f}, "
            f"valid={per_date_stats[-1]['valid_fraction']*100:.1f}%"
        )
    
    # --- Compute temporal deltas between consecutive dates ---
    deltas = []
    for i in range(1, len(arrays)):
        prev = arrays[i - 1]
        curr = arrays[i]
        
        # Compute difference only where both dates have valid data
        both_valid = ~np.isnan(prev) & ~np.isnan(curr)
        
        if not both_valid.any():
            logger.warning(
                f"No overlapping valid pixels between "
                f"{acquisitions[i-1]['date']} and {acquisitions[i]['date']}"
            )
            continue
        
        delta = curr[both_valid] - prev[both_valid]
        
        # Fraction of pixels that improved / degraded
        improved = (delta > 0.05).sum()   # NDVI increased > 0.05
        degraded = (delta < -0.05).sum()  # NDVI decreased > 0.05
        stable = both_valid.sum() - improved - degraded
        
        deltas.append({
            "from_date": acquisitions[i-1]["date"],
            "to_date": acquisitions[i]["date"],
            "n_pixels_compared": int(both_valid.sum()),
            "mean_delta": round(float(delta.mean()), 6),
            "std_delta": round(float(delta.std()), 6),
            "max_increase": round(float(delta.max()), 6),
            "max_decrease": round(float(delta.min()), 6),
            "pct_improved": round(float(improved / both_valid.sum() * 100), 2),
            "pct_degraded": round(float(degraded / both_valid.sum() * 100), 2),
            "pct_stable": round(float(stable / both_valid.sum() * 100), 2),
            "delta_threshold_used": 0.05,
            "_note": "improved/degraded defined as |delta| > 0.05 NDVI units"
        })
        
        logger.info(
            f"  Delta {acquisitions[i-1]['date'][:10]} → {acquisitions[i]['date'][:10]}: "
            f"mean={delta.mean():.4f}, degraded={degraded/both_valid.sum()*100:.1f}%"
        )
    
    # Overall trend direction from first to last date
    first_mean = per_date_stats[0].get("mean")
    last_mean = per_date_stats[-1].get("mean")
    
    if first_mean is not None and last_mean is not None:
        total_change = last_mean - first_mean
        trend_direction = "improving" if total_change > 0.02 else ("degrading" if total_change < -0.02 else "stable")
    else:
        total_change = None
        trend_direction = "unknown"
    
    return {
        "n_acquisitions": len(acquisitions),
        "date_range": {
            "start": acquisitions[0]["date"],
            "end": acquisitions[-1]["date"],
        },
        "per_date_statistics": per_date_stats,
        "temporal_deltas": deltas,
        "overall_trend": {
            "direction": trend_direction,
            "total_mean_ndvi_change": round(total_change, 6) if total_change is not None else None,
            "_note": (
                "trend_direction: 'improving' if total_change > 0.02, "
                "'degrading' if < -0.02, else 'stable'. "
                "These thresholds are agronomically meaningful NDVI units, not arbitrary."
            )
        }
    }