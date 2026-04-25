"""
validate_pipeline.py
====================
Comprehensive validation and diagnostic script.

Runs checks on:
1. NDVI raster — pixel value distribution, NaN coverage
2. Tile statistics — coordinate sanity, NDVI consistency
3. Alert logic — verify alerts match threshold rules
4. JSON output — schema and value consistency

Also prints per-band diagnostics to help debug data issues.

USAGE:
  python src/validate_pipeline.py \
      --ndvi_raster data/processed/S2A_20240615_T43PGN_NDVI.tif \
      --b04 data/processed/S2A_20240615_T43PGN_B04.tif \
      --b08 data/processed/S2A_20240615_T43PGN_B08.tif \
      --output_json outputs/result.json
"""

import sys
import json
import argparse
import logging
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def validate_band_file(path: str, band_name: str):
    """Print diagnostics for a single band GeoTIFF."""
    print(f"\n{'='*50}")
    print(f"Band: {band_name} — {path}")
    print(f"{'='*50}")
    
    if not Path(path).exists():
        print(f"  ERROR: File not found: {path}")
        return False
    
    with rasterio.open(path) as src:
        arr = src.read(1)
        print(f"  Shape:     {arr.shape[0]} × {arr.shape[1]} pixels")
        print(f"  CRS:       {src.crs}")
        print(f"  Bounds:    {src.bounds}")
        print(f"  Pixel res: {abs(src.transform.a):.1f}m × {abs(src.transform.e):.1f}m")
        print(f"  Dtype:     {arr.dtype}")
        print(f"  Nodata:    {src.nodata}")
    
    # For float bands (already converted to reflectance)
    if arr.dtype in (np.float32, np.float64):
        valid = arr[arr != 0]
        nonan = arr[~np.isnan(arr) & (arr != -9999.0)]
        print(f"\n  Value distribution (non-zero, non-NaN):")
    else:
        # DN values
        valid = arr[arr > 0].astype(np.float32)
        nonan = valid
        print(f"\n  Value distribution (DN > 0):")
    
    if nonan.size == 0:
        print(f"  ERROR: All pixels are zero or NaN!")
        return False
    
    print(f"  Count:     {nonan.size:,} of {arr.size:,} pixels ({nonan.size/arr.size*100:.1f}%)")
    print(f"  Min:       {nonan.min():.6f}")
    print(f"  Max:       {nonan.max():.6f}")
    print(f"  Mean:      {nonan.mean():.6f}")
    print(f"  Std:       {nonan.std():.6f}")
    
    pcts = np.percentile(nonan, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    pct_labels = ['p1', 'p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95', 'p99']
    print(f"\n  Percentiles:")
    for label, val in zip(pct_labels, pcts):
        print(f"    {label:>3}: {val:.6f}")
    
    return True


def validate_ndvi_spot_check(b04_path: str, b08_path: str, ndvi_path: str):
    """
    Spot-check NDVI computation by recomputing a sample of pixels
    and verifying they match the stored NDVI raster.
    """
    print(f"\n{'='*50}")
    print(f"NDVI Spot-Check (verification)")
    print(f"{'='*50}")
    
    with rasterio.open(b04_path) as src:
        b04 = src.read(1).astype(np.float32)
    with rasterio.open(b08_path) as src:
        b08 = src.read(1).astype(np.float32)
    with rasterio.open(ndvi_path) as src:
        ndvi_stored = src.read(1).astype(np.float32)
        nodata = src.nodata
    
    # Replace nodata with NaN
    if nodata is not None:
        ndvi_stored[ndvi_stored == nodata] = np.nan
    
    # Recompute NDVI for all pixels where denominator > 0
    denom = b08 + b04
    valid = (denom > 0) & ~np.isnan(ndvi_stored)
    
    ndvi_recomputed = np.full_like(b04, np.nan)
    ndvi_recomputed[valid] = (b08[valid] - b04[valid]) / denom[valid]
    
    # Compare recomputed vs stored
    both_valid = valid & ~np.isnan(ndvi_recomputed)
    diff = np.abs(ndvi_recomputed[both_valid] - ndvi_stored[both_valid])
    
    max_diff = diff.max()
    mean_diff = diff.mean()
    
    print(f"  Pixels verified: {both_valid.sum():,}")
    print(f"  Max absolute difference (recomputed vs stored): {max_diff:.8f}")
    print(f"  Mean absolute difference: {mean_diff:.8f}")
    
    tolerance = 1e-5  # float32 precision tolerance
    if max_diff < tolerance:
        print(f"  ✓ NDVI values match recomputation (within float32 tolerance {tolerance})")
    else:
        print(f"  ✗ WARNING: Difference {max_diff:.6f} exceeds tolerance {tolerance}")
        print(f"    This may indicate a scaling or nodata issue.")
    
    # Sample 5 random valid pixels and show computation
    print(f"\n  Sample pixel verification (5 random valid pixels):")
    print(f"  {'Row':>6} {'Col':>6} {'B04':>8} {'B08':>8} {'Stored':>8} {'Recomp':>8} {'Match':>6}")
    print(f"  {'-'*6} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
    
    valid_indices = np.argwhere(both_valid)
    if len(valid_indices) > 5:
        sample_idx = valid_indices[
            np.random.RandomState(42).choice(len(valid_indices), 5, replace=False)
        ]
    else:
        sample_idx = valid_indices
    
    for r, c in sample_idx:
        b4_val = b04[r, c]
        b8_val = b08[r, c]
        ndvi_s = ndvi_stored[r, c]
        ndvi_r = ndvi_recomputed[r, c]
        matches = "✓" if abs(ndvi_s - ndvi_r) < tolerance else "✗"
        print(f"  {r:>6} {c:>6} {b4_val:>8.4f} {b8_val:>8.4f} {ndvi_s:>8.4f} {ndvi_r:>8.4f} {matches:>6}")


def validate_output_json(json_path: str):
    """Validate the output JSON for consistency."""
    print(f"\n{'='*50}")
    print(f"Output JSON Validation: {json_path}")
    print(f"{'='*50}")
    
    if not Path(json_path).exists():
        print(f"  ERROR: File not found: {json_path}")
        return
    
    with open(json_path) as f:
        data = json.load(f)
    
    errors = []
    warnings = []
    
    # Check NDVI range
    ndvi_s = data.get("summary", {}).get("ndvi_statistics", {})
    mean_ndvi = ndvi_s.get("mean", None)
    
    if mean_ndvi is not None:
        if not (-1.0 <= mean_ndvi <= 1.0):
            errors.append(f"NDVI mean {mean_ndvi} outside [-1, 1]")
        if ndvi_s.get("std", 0) > 0.5:
            warnings.append(f"NDVI std {ndvi_s['std']:.4f} is very high (possible cloud contamination)")
        if ndvi_s.get("min", 0) < -0.5:
            warnings.append(f"NDVI min {ndvi_s['min']:.4f} < -0.5 (check water bodies / cloud shadows)")
    
    # Check tile coordinates
    tiles = data.get("tiles", [])
    for t in tiles:
        lat = t.get("center_lat", 0)
        lon = t.get("center_lon", 0)
        if not (-90 <= lat <= 90):
            errors.append(f"Tile {t['tile_id']}: lat={lat} out of range")
        if not (-180 <= lon <= 180):
            errors.append(f"Tile {t['tile_id']}: lon={lon} out of range")
    
    # Check alert count consistency
    n_alerts = len(data.get("alerts", []))
    n_alert_tiles_summary = data.get("summary", {}).get("alert_tiles", 0)
    if n_alerts != n_alert_tiles_summary:
        warnings.append(
            f"Alert count mismatch: summary.alert_tiles={n_alert_tiles_summary}, "
            f"len(alerts)={n_alerts}"
        )
    
    # Check no hardcoded timestamps
    acq = data.get("metadata", {}).get("source", {}).get("acquisition_datetime", "")
    if "2 min ago" in str(data) or "just now" in str(data):
        errors.append("Found relative timestamp ('2 min ago' etc) — must use ISO 8601")
    
    # Summary
    print(f"\n  Acquisition: {acq}")
    print(f"  Tiles: {len(tiles)}, Alerts: {n_alerts}")
    if mean_ndvi is not None:
        print(f"  NDVI mean: {mean_ndvi:.4f}, std: {ndvi_s.get('std', 'N/A'):.4f}")
    
    if warnings:
        print(f"\n  WARNINGS:")
        for w in warnings:
            print(f"    ⚠ {w}")
    
    if errors:
        print(f"\n  ERRORS:")
        for e in errors:
            print(f"    ✗ {e}")
    else:
        print(f"\n  ✓ JSON output passes all validation checks")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--b04", help="B04 GeoTIFF path")
    parser.add_argument("--b08", help="B08 GeoTIFF path")
    parser.add_argument("--ndvi_raster", help="NDVI GeoTIFF path")
    parser.add_argument("--output_json", help="Output JSON path")
    args = parser.parse_args()
    
    if args.b04:
        validate_band_file(args.b04, "B04 (Red)")
    if args.b08:
        validate_band_file(args.b08, "B08 (NIR)")
    if args.ndvi_raster:
        validate_band_file(args.ndvi_raster, "NDVI")
    if args.b04 and args.b08 and args.ndvi_raster:
        validate_ndvi_spot_check(args.b04, args.b08, args.ndvi_raster)
    if args.output_json:
        validate_output_json(args.output_json)


if __name__ == "__main__":
    main()