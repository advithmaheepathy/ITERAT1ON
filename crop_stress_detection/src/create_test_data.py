"""
create_test_data.py
===================
Generate synthetic Sentinel-2 test data for pipeline testing.
Creates realistic B04 (Red) and B08 (NIR) bands with spatial patterns.
"""

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from pathlib import Path

print("Creating test Sentinel-2 data...")

# Create output directory
output_dir = Path("data/test")
output_dir.mkdir(parents=True, exist_ok=True)

# Image parameters (small test image)
width, height = 512, 512  # 512x512 pixels
pixel_size = 10  # 10m resolution (Sentinel-2 standard)

# Geographic bounds (small area in Andhra Pradesh)
lon_min, lat_min = 78.966, 16.581
lon_max = lon_min + (width * pixel_size) / 111320  # ~5km
lat_max = lat_min + (height * pixel_size) / 111320  # ~5km

# Create affine transform
transform = from_bounds(lon_min, lat_min, lon_max, lat_max, width, height)
crs = CRS.from_epsg(4326)

# Generate synthetic B04 (Red band) - surface reflectance [0, 1]
print("Generating B04 (Red band)...")
np.random.seed(42)

# Create spatial patterns: healthy vegetation (low red), stressed areas (high red)
x = np.linspace(0, 4*np.pi, width)
y = np.linspace(0, 4*np.pi, height)
X, Y = np.meshgrid(x, y)

# Base pattern: mix of healthy and stressed vegetation
b04 = 0.05 + 0.03 * np.sin(X) * np.cos(Y)  # Healthy vegetation (low red reflectance)
b04 += 0.02 * np.random.randn(height, width)  # Add noise

# Add stressed patches (higher red reflectance)
stress_mask = (np.sin(X*0.5) > 0.5) & (np.cos(Y*0.5) > 0.5)
b04[stress_mask] += 0.08  # Stressed vegetation has higher red

# Add some bare soil patches (very high red)
bare_soil = (X > 10) & (X < 11) & (Y > 10) & (Y < 11)
b04[bare_soil] = 0.15 + 0.05 * np.random.rand(bare_soil.sum())

# Clip to valid range
b04 = np.clip(b04, 0.0, 0.3).astype(np.float32)

# Generate synthetic B08 (NIR band)
print("Generating B08 (NIR band)...")

# Healthy vegetation has HIGH NIR reflectance
b08 = 0.35 + 0.15 * np.sin(X) * np.cos(Y)  # Healthy vegetation (high NIR)
b08 += 0.03 * np.random.randn(height, width)  # Add noise

# Stressed areas have LOWER NIR
b08[stress_mask] -= 0.15  # Stressed vegetation has lower NIR

# Bare soil has moderate NIR
b08[bare_soil] = 0.20 + 0.05 * np.random.rand(bare_soil.sum())

# Clip to valid range
b08 = np.clip(b08, 0.0, 0.6).astype(np.float32)

# Generate cloud mask (mostly clear)
print("Generating cloud mask...")
cloud_mask = np.ones((height, width), dtype=np.uint8)

# Add some cloudy pixels
cloudy = (X < 2) & (Y < 2)
cloud_mask[cloudy] = 0

# Write B04
print("Writing B04.tif...")
with rasterio.open(
    output_dir / "B04.tif",
    "w",
    driver="GTiff",
    height=height,
    width=width,
    count=1,
    dtype=np.float32,
    crs=crs,
    transform=transform,
    compress="lzw"
) as dst:
    dst.write(b04, 1)

# Write B08
print("Writing B08.tif...")
with rasterio.open(
    output_dir / "B08.tif",
    "w",
    driver="GTiff",
    height=height,
    width=width,
    count=1,
    dtype=np.float32,
    crs=crs,
    transform=transform,
    compress="lzw"
) as dst:
    dst.write(b08, 1)

# Write cloud mask
print("Writing valid_mask.tif...")
with rasterio.open(
    output_dir / "valid_mask.tif",
    "w",
    driver="GTiff",
    height=height,
    width=width,
    count=1,
    dtype=np.uint8,
    crs=crs,
    transform=transform,
    compress="lzw"
) as dst:
    dst.write(cloud_mask, 1)

# Calculate expected NDVI stats
valid_pixels = cloud_mask == 1
ndvi_test = (b08[valid_pixels] - b04[valid_pixels]) / (b08[valid_pixels] + b04[valid_pixels])

print("\n" + "="*60)
print("✓ Test data created successfully!")
print("="*60)
print(f"Location: {output_dir.absolute()}")
print(f"Image size: {width}x{height} pixels ({width*pixel_size/1000:.1f}km x {height*pixel_size/1000:.1f}km)")
print(f"Resolution: {pixel_size}m/pixel")
print(f"Valid pixels: {valid_pixels.sum():,} ({valid_pixels.mean()*100:.1f}%)")
print(f"\nExpected NDVI range: [{ndvi_test.min():.3f}, {ndvi_test.max():.3f}]")
print(f"Expected NDVI mean: {ndvi_test.mean():.3f}")
print(f"\nFiles created:")
print(f"  - B04.tif (Red band)")
print(f"  - B08.tif (NIR band)")
print(f"  - valid_mask.tif (cloud mask)")
print("\n" + "="*60)
print("Next step: Run the pipeline")
print("="*60)
print('python src/run_pipeline.py --b04 data/test/B04.tif --b08 data/test/B08.tif --mask data/test/valid_mask.tif --output outputs/test_result.json')
print("="*60)
