"""Audit SCL pixel distribution to find root cause of low valid pixel %."""
import pathlib, sys
import numpy as np
import rasterio

NAMES = {
    0: "NO_DATA", 1: "SAT_DEFECT", 2: "DARK_AREA", 3: "CLOUD_SHADOW",
    4: "VEGETATION", 5: "NOT_VEG", 6: "WATER", 7: "UNCLASSIFIED",
    8: "CLOUD_MED", 9: "CLOUD_HIGH", 10: "THIN_CIRRUS", 11: "SNOW_ICE",
}

def audit(scl_path):
    with rasterio.open(scl_path) as src:
        scl = src.read(1)
    total = scl.size
    print(f"\nSCL file : {scl_path}")
    print(f"Shape    : {scl.shape}")
    print(f"Total px : {total:,}")
    print("-" * 55)
    for c in range(12):
        n = int((scl == c).sum())
        if n > 0:
            print(f"  SCL {c:2d} ({NAMES.get(c,'?'):15s}): {n:10,}  ({n/total*100:6.2f}%)")
    print("-" * 55)

    # Simulate old pipeline (masks water=True)
    INVALID_CLOUD = [0,1,3,8,9,10,11]
    WATER = 6
    bad = np.zeros(scl.shape, dtype=bool)
    for c in INVALID_CLOUD:
        bad |= (scl == c)
    bad |= (scl == WATER)
    valid_with_water_masked = (~bad).sum()

    # Without water mask
    bad2 = np.zeros(scl.shape, dtype=bool)
    for c in INVALID_CLOUD:
        bad2 |= (scl == c)
    valid_no_water_mask = (~bad2).sum()

    print(f"\n  → With water masked  : {valid_with_water_masked:,}  ({valid_with_water_masked/total*100:.2f}%)")
    print(f"  → Without water mask : {valid_no_water_mask:,}  ({valid_no_water_mask/total*100:.2f}%)")
    water_px = int((scl == WATER).sum())
    print(f"  → Water pixels (SCL=6): {water_px:,}  ({water_px/total*100:.2f}%)")
    print()

# Try all possible locations
search_roots = [
    pathlib.Path("C:/s2_data"),
    pathlib.Path("data/processed"),
    pathlib.Path("."),
]

found = False
for root in search_roots:
    files = list(root.rglob("*SCL*"))
    for f in files:
        if f.suffix in (".jp2", ".tif"):
            audit(f)
            found = True

if not found:
    print("No SCL files found. Checking all jp2/tif files...")
    for root in search_roots:
        for f in list(root.rglob("*.jp2")) + list(root.rglob("*.tif")):
            print(f"  {f}")
