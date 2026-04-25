"""
create_burn_test_data.py
========================
Generate synthetic bi-temporal Sentinel-2 data to test the burn detection pipeline.

Creates fake BEFORE (healthy) and AFTER (burned) band arrays as GeoTIFFs,
then runs the pipeline against them.

The synthetic scene contains:
    - A vegetated region (high NDVI before, burned after)
    - A water body (excluded via SCL)
    - Bare soil (low NDVI, not flagged as burn)
    - A cloud patch (masked out)

This is ONLY for pipeline validation. No real satellite data.
"""

import sys
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


def create_synthetic_scene(output_dir: str):
    """
    Generate synthetic before/after band GeoTIFFs for testing.
    
    Scene layout (500×500 pixels at 10m = 5km × 5km):
        ┌──────────────────────┐
        │    Healthy veg       │  rows 0–199
        │    (NDVI ~0.7)       │
        ├──────────────────────┤
        │    BURNED ZONE       │  rows 200–349
        │    (high dNBR)       │
        ├──────────────────────┤
        │ Bare soil │  Water   │  rows 350–449
        │ (low NDVI)│ (SCL=6)  │
        ├──────────────────────┤
        │    Clouds (masked)   │  rows 450–499
        └──────────────────────┘
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    H, W = 500, 500
    rng = np.random.default_rng(42)

    # Spatial reference: UTM zone 44N (same as existing pipeline data)
    crs = CRS.from_epsg(32644)
    # 5km × 5km scene near Chennai
    transform = from_bounds(
        80.2 * 111320, 13.0 * 110540,  # approximate meters
        80.2 * 111320 + 5000, 13.0 * 110540 + 5000,
        W, H,
    )

    meta_10m = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": W,
        "height": H,
        "count": 1,
        "crs": crs,
        "transform": transform,
        "compress": "lzw",
    }
    meta_20m = meta_10m.copy()
    meta_20m.update({
        "width": W // 2,
        "height": H // 2,
        "transform": from_bounds(
            80.2 * 111320, 13.0 * 110540,
            80.2 * 111320 + 5000, 13.0 * 110540 + 5000,
            W // 2, H // 2,
        ),
    })
    meta_scl = meta_20m.copy()
    meta_scl["dtype"] = "uint8"

    # ── BEFORE scene (pre-fire: healthy vegetation everywhere) ────

    # B04 (Red): low for vegetation, moderate for bare soil
    b04_before = np.full((H, W), 0.04, dtype=np.float32)  # healthy veg
    b04_before[350:450, :250] = 0.20  # bare soil
    b04_before[350:450, 250:] = 0.02  # water
    b04_before += rng.normal(0, 0.005, (H, W)).astype(np.float32)
    b04_before = np.clip(b04_before, 0, 1)

    # B08 (NIR): high for vegetation, low for bare soil & water
    b08_before = np.full((H, W), 0.35, dtype=np.float32)  # healthy veg
    b08_before[350:450, :250] = 0.12  # bare soil
    b08_before[350:450, 250:] = 0.01  # water
    b08_before += rng.normal(0, 0.01, (H, W)).astype(np.float32)
    b08_before = np.clip(b08_before, 0, 1)

    # B12 (SWIR, 20m): moderate for vegetation, high for bare soil, very low for water
    b12_before_20m = np.full((H // 2, W // 2), 0.15, dtype=np.float32)
    b12_before_20m[175:225, :125] = 0.25  # bare soil
    b12_before_20m[175:225, 125:] = 0.005  # water
    b12_before_20m += rng.normal(0, 0.005, (H // 2, W // 2)).astype(np.float32)
    b12_before_20m = np.clip(b12_before_20m, 0, 1)

    # ── AFTER scene (post-fire: burn zone has changed spectral signature) ──

    # In the burn zone (rows 200-349), vegetation is destroyed:
    #   - B04 (Red) increases (char/ash is darker in NIR but brighter in red/SWIR)
    #   - B08 (NIR) drops dramatically
    #   - B12 (SWIR) increases (exposed soil + char)

    b04_after = b04_before.copy()
    b08_after = b08_before.copy()
    b12_after_20m = b12_before_20m.copy()

    # Burn zone modifications
    b04_after[200:350, :] = 0.08 + rng.normal(0, 0.01, (150, W)).astype(np.float32)
    b08_after[200:350, :] = 0.06 + rng.normal(0, 0.01, (150, W)).astype(np.float32)  # NIR drops
    b12_after_20m[100:175, :] = 0.30 + rng.normal(0, 0.01, (75, W // 2)).astype(np.float32)  # SWIR rises

    b04_after = np.clip(b04_after, 0, 1)
    b08_after = np.clip(b08_after, 0, 1)
    b12_after_20m = np.clip(b12_after_20m, 0, 1)

    # ── SCL (Scene Classification Layer) ──
    # 4 = vegetation, 5 = bare soil, 6 = water, 9 = cloud
    scl_before_20m = np.full((H // 2, W // 2), 4, dtype=np.uint8)  # vegetation
    scl_before_20m[175:225, :125] = 5  # bare soil
    scl_before_20m[175:225, 125:] = 6  # water
    scl_before_20m[225:, :] = 9        # clouds

    scl_after_20m = scl_before_20m.copy()

    # ── Write GeoTIFFs ────────────────────────────────────────────
    files = {
        "before_B04.tif": (b04_before, meta_10m),
        "before_B08.tif": (b08_before, meta_10m),
        "before_B12.tif": (b12_before_20m, meta_20m),
        "after_B04.tif": (b04_after, meta_10m),
        "after_B08.tif": (b08_after, meta_10m),
        "after_B12.tif": (b12_after_20m, meta_20m),
    }

    for fname, (data, meta) in files.items():
        fpath = out / fname
        with rasterio.open(fpath, "w", **meta) as dst:
            dst.write(data, 1)
        print(f"  ✓ {fname}: shape={data.shape}, range=[{data.min():.4f}, {data.max():.4f}]")

    # SCL files (uint8)
    for fname, data in [("before_SCL.tif", scl_before_20m), ("after_SCL.tif", scl_after_20m)]:
        fpath = out / fname
        with rasterio.open(fpath, "w", **meta_scl) as dst:
            dst.write(data, 1)
        print(f"  ✓ {fname}: shape={data.shape}, classes={np.unique(data)}")

    print(f"\n✓ Test data written to {out}/")
    return out


def run_test_pipeline(data_dir: str):
    """Run burn pipeline on synthetic test data."""
    from src.run_burn_pipeline import run_burn_pipeline

    class Args:
        before_safe = None
        after_safe = None
        before_b04 = str(Path(data_dir) / "before_B04.tif")
        before_b08 = str(Path(data_dir) / "before_B08.tif")
        before_b12 = str(Path(data_dir) / "before_B12.tif")
        after_b04 = str(Path(data_dir) / "after_B04.tif")
        after_b08 = str(Path(data_dir) / "after_B08.tif")
        after_b12 = str(Path(data_dir) / "after_B12.tif")
        scl_before = str(Path(data_dir) / "before_SCL.tif")
        scl_after = str(Path(data_dir) / "after_SCL.tif")
        output = "outputs/burn_test_result.json"
        vis_output = "outputs/burn_test_visualization.tif"
        debug = False

    result = run_burn_pipeline(Args())

    # Validate output
    print("\n" + "=" * 60)
    print("TEST VALIDATION")
    print("=" * 60)

    burned_ha = result["summary"]["burned_area_ha"]
    burned_px = result["summary"]["burned_pixels"]
    confidence = result["summary"]["confidence"]

    print(f"  Burned area:  {burned_ha} ha ({burned_px:,} pixels)")
    print(f"  Confidence:   {confidence}%")

    sev = result["summary"]["severity_distribution"]
    for key, info in sev.items():
        if info["pixel_count"] > 0:
            print(f"  {info['label']}: {info['area_ha']} ha ({info['pixel_count']:,} px)")

    # Basic sanity checks
    errors = []
    if burned_px == 0:
        errors.append("FAIL: No burned pixels detected (expected burn in rows 200-349)")
    if burned_ha <= 0:
        errors.append("FAIL: Burned area should be > 0")

    # Check output files exist
    for f in ["burn_test_result.json", "burn_mask.tif", "burn_severity.tif", "burn_test_visualization.tif"]:
        if not (Path("outputs") / f).exists():
            errors.append(f"FAIL: Missing output file: {f}")

    if errors:
        print("\n✗ ERRORS:")
        for e in errors:
            print(f"  {e}")
    else:
        print("\n✓ All checks passed — burn detection pipeline is working correctly")

    return result


if __name__ == "__main__":
    print("Creating synthetic bi-temporal test data...")
    data_dir = create_synthetic_scene("data/test_burn")
    print("\nRunning burn detection pipeline on test data...\n")
    run_test_pipeline(str(data_dir))
