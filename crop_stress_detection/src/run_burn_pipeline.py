"""
run_burn_pipeline.py
====================
Main entry point for the burnt crop area detection pipeline.

USAGE:

  # From .SAFE directories (before + after fire):
  python src/run_burn_pipeline.py \
      --before_safe data/raw/S2_BEFORE_*.SAFE \
      --after_safe  data/raw/S2_AFTER_*.SAFE \
      --output outputs/burn_result.json

  # From pre-extracted band files:
  python src/run_burn_pipeline.py \
      --before_b04 data/processed/before_B04.tif \
      --before_b08 data/processed/before_B08.tif \
      --before_b12 data/processed/before_B12.tif \
      --after_b04  data/processed/after_B04.tif \
      --after_b08  data/processed/after_B08.tif \
      --after_b12  data/processed/after_B12.tif \
      --scl_before data/processed/before_SCL_10m.tif \
      --scl_after  data/processed/after_SCL_10m.tif \
      --output outputs/burn_result.json

  # With visualization output:
  python src/run_burn_pipeline.py \
      --before_b04 ... --after_b04 ... \
      --output outputs/burn_result.json \
      --vis_output outputs/burn_visualization.tif
"""

import sys
import json
import logging
import argparse
import glob
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Tuple

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling as WarpResampling

# Local imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.burn_detection import (
    compute_ndvi,
    compute_nbr,
    compute_dnbr,
    build_burn_mask,
    classify_burn,
    calculate_area,
    create_burn_visualization,
    SEVERITY_THRESHOLDS,
    VEGETATION_NDVI_MIN,
    DNBR_BURN_THRESHOLD,
)
from src.preprocess import (
    find_safe_bands,
    read_band_as_float32,
    build_cloud_mask,
    SCL_UNUSABLE_CLASSES,
)

# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/burn_pipeline.log"),
    ],
)
logger = logging.getLogger("burn_pipeline")

# SCL classes that indicate water (must be excluded from burn analysis)
SCL_WATER_CLASS = 6


# ══════════════════════════════════════════════════════════════════════
# BAND I/O HELPERS
# ══════════════════════════════════════════════════════════════════════

def load_band(path: str) -> Tuple[np.ndarray, dict]:
    """Load a single-band GeoTIFF as float32 with metadata."""
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        logger.debug(f"Loaded {Path(path).name}: shape={data.shape}, CRS={src.crs}")

    # Convert Sentinel-2 L2A DN to surface reflectance if needed
    if data.max() > 1.5:
        data = data / 10000.0
        logger.debug(f"  DN→SR conversion applied, range [{data.min():.4f}, {data.max():.4f}]")

    return data, meta


def resample_to_10m(
    source_array: np.ndarray,
    source_meta: dict,
    target_meta: dict,
) -> np.ndarray:
    """
    Resample a 20m band (B12 / SCL) to match 10m resolution grid.

    Uses bilinear interpolation for continuous data (B12 reflectance)
    and nearest-neighbor for categorical data (SCL).
    """
    resampled = np.zeros(
        (target_meta["height"], target_meta["width"]),
        dtype=source_array.dtype,
    )

    reproject(
        source=source_array,
        destination=resampled,
        src_transform=source_meta["transform"],
        src_crs=source_meta["crs"],
        dst_transform=target_meta["transform"],
        dst_crs=target_meta["crs"],
        resampling=WarpResampling.bilinear,
    )

    logger.info(
        f"Resampled {source_array.shape} → {resampled.shape} "
        f"(20m → 10m)"
    )

    return resampled


def load_and_resample_b12(
    b12_path: str,
    target_meta: dict,
) -> np.ndarray:
    """Load B12 (SWIR, 20m) and resample to 10m to match B04/B08."""
    b12_raw, b12_meta = load_band(b12_path)
    b12_10m = resample_to_10m(b12_raw, b12_meta, target_meta)
    return b12_10m


def build_valid_mask(
    scl_path: Optional[str],
    target_meta: dict,
) -> np.ndarray:
    """
    Build combined cloud + water mask from SCL.

    Masks out:
        - Clouds / shadows / snow / no-data (SCL classes 0,1,3,8,9,10,11)
        - Water bodies (SCL class 6)
    """
    if scl_path is None or not Path(scl_path).exists():
        h = target_meta["height"]
        w = target_meta["width"]
        logger.warning("No SCL provided — assuming all pixels valid")
        return np.ones((h, w), dtype=bool)

    with rasterio.open(scl_path) as src:
        scl_raw = src.read(1)
        scl_meta = src.meta.copy()

    # Resample SCL to 10m (nearest neighbor for categorical)
    scl_10m = np.zeros(
        (target_meta["height"], target_meta["width"]),
        dtype=scl_raw.dtype,
    )
    reproject(
        source=scl_raw,
        destination=scl_10m,
        src_transform=scl_meta["transform"],
        src_crs=scl_meta["crs"],
        dst_transform=target_meta["transform"],
        dst_crs=target_meta["crs"],
        resampling=WarpResampling.nearest,
    )

    # Build cloud/nodata mask
    cloud_mask = build_cloud_mask(scl_10m)

    # Additionally mask water (SCL == 6)
    water_mask = scl_10m == SCL_WATER_CLASS
    water_count = water_mask.sum()
    if water_count > 0:
        logger.info(f"Water pixels masked: {water_count:,} (SCL=6)")

    valid = cloud_mask & (~water_mask)

    valid_pct = valid.mean() * 100
    logger.info(f"Final valid mask: {valid_pct:.1f}% usable pixels")

    return valid


def find_b12_in_safe(safe_dir: str) -> Path:
    """Locate B12 (SWIR) band file within a .SAFE directory."""
    safe_path = Path(safe_dir)
    patterns = ["*_B12_20m.tif", "*_B12_20m.jp2", "*_B12.tif", "*_B12.jp2"]

    for pattern in patterns:
        matches = list(safe_path.rglob(pattern))
        if matches:
            logger.info(f"Found B12: {matches[0].relative_to(safe_path)}")
            return matches[0]

    raise FileNotFoundError(
        f"B12 (SWIR) not found in {safe_path}. "
        f"Tried patterns: {patterns}. "
        f"Ensure this is an L2A product with SWIR bands."
    )


# ══════════════════════════════════════════════════════════════════════
# OUTPUT WRITERS
# ══════════════════════════════════════════════════════════════════════

def build_output_json(
    area_stats: Dict,
    preprocessing_info: Dict,
    processing_start: str,
    processing_end: str,
) -> Dict:
    """Build the final structured JSON output."""

    burned_pixels = area_stats["burned_pixels"]
    total_pixels = area_stats["total_pixels"]

    # Confidence heuristic based on:
    #   - valid pixel fraction (higher = more confident)
    #   - burned fraction (very small burns have lower confidence)
    valid_frac = preprocessing_info.get("valid_pixel_pct_combined", 100) / 100
    burned_frac = area_stats["burned_fraction"]

    # Base confidence from valid pixel coverage
    confidence = min(valid_frac * 100, 98.0)

    # Reduce confidence if burn area is very small (< 0.1% of image)
    if burned_frac < 0.001 and burned_pixels > 0:
        confidence *= 0.8

    confidence = round(confidence, 1)

    return {
        "metadata": {
            "pipeline": "burn_detection",
            "pipeline_version": "1.0.0",
            "processing_start": processing_start,
            "processing_end": processing_end,
            "method": {
                "ndvi_formula": "NDVI = (B08 - B04) / (B08 + B04)",
                "nbr_formula": "NBR = (B08 - B12) / (B08 + B12)",
                "dnbr_formula": "dNBR = NBR_before - NBR_after",
                "vegetation_filter": f"NDVI_before > {VEGETATION_NDVI_MIN}",
                "burn_threshold": f"dNBR > {DNBR_BURN_THRESHOLD}",
                "severity_thresholds": {
                    k: (v["max"] if v["max"] != float("inf") else "no_upper_limit")
                    for k, v in SEVERITY_THRESHOLDS.items()
                },
                "cloud_mask": "SCL classes 0,1,3,8,9,10,11 masked",
                "water_mask": "SCL class 6 masked",
                "pixel_resolution_m": 10,
            },
            "source": preprocessing_info,
        },
        "summary": {
            "burned_area_ha": area_stats["burned_area_ha"],
            "burned_pixels": area_stats["burned_pixels"],
            "burned_fraction": area_stats["burned_fraction"],
            "severity_distribution": area_stats["severity_distribution"],
            "confidence": confidence,
        },
    }


def write_json(data: Dict, output_path: str):
    """Write result JSON to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Output JSON saved: {path}")


def write_visualization_tif(
    rgb: np.ndarray,
    reference_meta: dict,
    output_path: str,
):
    """Write RGB visualization as a 3-band GeoTIFF."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    meta = reference_meta.copy()
    meta.update({
        "dtype": "uint8",
        "count": 3,
        "compress": "lzw",
        "driver": "GTiff",
    })
    # Remove nodata for RGB output
    meta.pop("nodata", None)

    with rasterio.open(path, "w", **meta) as dst:
        for band_idx in range(3):
            dst.write(rgb[:, :, band_idx], band_idx + 1)

    logger.info(f"Visualization saved: {path}")


def write_burn_mask_tif(
    burn_mask: np.ndarray,
    reference_meta: dict,
    output_path: str,
):
    """Write binary burn mask as a single-band GeoTIFF."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    meta = reference_meta.copy()
    meta.update({
        "dtype": "uint8",
        "count": 1,
        "compress": "lzw",
        "driver": "GTiff",
        "nodata": 255,
    })

    with rasterio.open(path, "w", **meta) as dst:
        dst.write(burn_mask.astype(np.uint8), 1)

    logger.info(f"Burn mask saved: {path}")


def write_severity_tif(
    severity_map: np.ndarray,
    reference_meta: dict,
    output_path: str,
):
    """Write severity classification as a single-band GeoTIFF."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    meta = reference_meta.copy()
    meta.update({
        "dtype": "uint8",
        "count": 1,
        "compress": "lzw",
        "driver": "GTiff",
        "nodata": 255,
    })

    with rasterio.open(path, "w", **meta) as dst:
        dst.write(severity_map, 1)

    logger.info(f"Severity map saved: {path}")


# ══════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════

def run_burn_pipeline(args):
    """Execute the full burn detection pipeline."""
    processing_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("=" * 60)
    logger.info("BURN DETECTION PIPELINE — START")
    logger.info("=" * 60)

    Path("logs").mkdir(exist_ok=True)

    # ── Load bands ────────────────────────────────────────────────
    if args.before_safe and args.after_safe:
        # .SAFE directory mode
        before_dirs = glob.glob(args.before_safe)
        after_dirs = glob.glob(args.after_safe)

        if not before_dirs:
            logger.error(f"No before .SAFE found: {args.before_safe}")
            sys.exit(1)
        if not after_dirs:
            logger.error(f"No after .SAFE found: {args.after_safe}")
            sys.exit(1)

        before_dir = before_dirs[0]
        after_dir = after_dirs[0]

        logger.info(f"BEFORE: {before_dir}")
        logger.info(f"AFTER:  {after_dir}")

        # Find all bands
        before_bands = find_safe_bands(before_dir)
        after_bands = find_safe_bands(after_dir)
        before_b12_path = find_b12_in_safe(before_dir)
        after_b12_path = find_b12_in_safe(after_dir)

        # Read B04, B08 (10m)
        b04_before, b04_before_meta = read_band_as_float32(before_bands["B04"])
        b08_before, _ = read_band_as_float32(before_bands["B08"])
        b04_after, b04_after_meta = read_band_as_float32(after_bands["B04"])
        b08_after, _ = read_band_as_float32(after_bands["B08"])

        # Read and resample B12 (20m → 10m)
        b12_before = load_and_resample_b12(str(before_b12_path), b04_before_meta)
        b12_after = load_and_resample_b12(str(after_b12_path), b04_after_meta)

        # Build SCL masks
        scl_before_path = str(before_bands.get("SCL", ""))
        scl_after_path = str(after_bands.get("SCL", ""))

        reference_meta = b04_before_meta

        preprocessing_info = {
            "before_safe": Path(before_dir).name,
            "after_safe": Path(after_dir).name,
            "bands_used": ["B04 (Red, 10m)", "B08 (NIR, 10m)", "B12 (SWIR, 20m→10m)"],
            "cloud_mask": "SCL band",
        }

    elif args.before_b04 and args.before_b08 and args.before_b12:
        # Pre-extracted band mode
        logger.info("Using pre-extracted band files")

        b04_before, b04_before_meta = load_band(args.before_b04)
        b08_before, _ = load_band(args.before_b08)
        b04_after, b04_after_meta = load_band(args.after_b04)
        b08_after, _ = load_band(args.after_b08)

        b12_before = load_and_resample_b12(args.before_b12, b04_before_meta)
        b12_after = load_and_resample_b12(args.after_b12, b04_after_meta)

        scl_before_path = args.scl_before
        scl_after_path = args.scl_after

        reference_meta = b04_before_meta

        preprocessing_info = {
            "before_b04": args.before_b04,
            "before_b08": args.before_b08,
            "before_b12": args.before_b12,
            "after_b04": args.after_b04,
            "after_b08": args.after_b08,
            "after_b12": args.after_b12,
            "bands_used": ["B04 (Red, 10m)", "B08 (NIR, 10m)", "B12 (SWIR, 20m→10m)"],
        }

    else:
        logger.error(
            "Must provide either --before_safe/--after_safe OR "
            "--before_b04/b08/b12 and --after_b04/b08/b12"
        )
        sys.exit(1)

    # ── Build masks ───────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: PREPROCESSING — Cloud & Water Masking")
    logger.info("=" * 60)

    mask_before = build_valid_mask(scl_before_path, b04_before_meta)
    mask_after = build_valid_mask(scl_after_path, b04_after_meta)

    # Combined mask: pixel must be valid in BOTH timestamps
    combined_mask = mask_before & mask_after

    combined_valid_pct = round(combined_mask.mean() * 100, 2)
    logger.info(f"Combined valid mask: {combined_valid_pct:.1f}% usable across both dates")

    preprocessing_info["valid_pixel_pct_before"] = round(mask_before.mean() * 100, 2)
    preprocessing_info["valid_pixel_pct_after"] = round(mask_after.mean() * 100, 2)
    preprocessing_info["valid_pixel_pct_combined"] = combined_valid_pct

    # ── Compute NDVI (before) ─────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: NDVI COMPUTATION (pre-fire vegetation filter)")
    logger.info("=" * 60)

    ndvi_before = compute_ndvi(b04_before, b08_before, combined_mask)

    veg_count = np.sum((~np.isnan(ndvi_before)) & (ndvi_before > VEGETATION_NDVI_MIN))
    total_valid = np.sum(~np.isnan(ndvi_before))
    logger.info(
        f"Vegetation pixels (NDVI>{VEGETATION_NDVI_MIN}): {veg_count:,} "
        f"({veg_count / max(total_valid, 1) * 100:.1f}% of valid area)"
    )

    # ── Compute NBR (before & after) ──────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: NBR COMPUTATION (before & after)")
    logger.info("=" * 60)

    nbr_before = compute_nbr(b08_before, b12_before, combined_mask)
    nbr_after = compute_nbr(b08_after, b12_after, combined_mask)

    # ── Compute dNBR ──────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4: dNBR (differenced NBR)")
    logger.info("=" * 60)

    dnbr = compute_dnbr(nbr_before, nbr_after)

    # ── Build burn mask ───────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 5: BURN MASK")
    logger.info("=" * 60)

    burn_mask = build_burn_mask(dnbr, ndvi_before)

    # ── Classify severity ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 6: BURN SEVERITY CLASSIFICATION")
    logger.info("=" * 60)

    severity_map = classify_burn(dnbr, burn_mask)

    # ── Calculate area ────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 7: AREA CALCULATION")
    logger.info("=" * 60)

    area_stats = calculate_area(burn_mask, severity_map)

    # ── Generate visualization ────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 8: VISUALIZATION")
    logger.info("=" * 60)

    rgb = create_burn_visualization(
        b04=b04_after,
        b08=b08_after,
        burn_mask=burn_mask,
        severity_map=severity_map,
        ndvi_before=ndvi_before,
        valid_mask=combined_mask,
    )

    # ── Write outputs ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 9: WRITE OUTPUTS")
    logger.info("=" * 60)

    processing_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # JSON summary
    output_json = build_output_json(
        area_stats=area_stats,
        preprocessing_info=preprocessing_info,
        processing_start=processing_start,
        processing_end=processing_end,
    )
    write_json(output_json, args.output)

    # Burn mask GeoTIFF
    output_dir = Path(args.output).parent
    write_burn_mask_tif(
        burn_mask, reference_meta,
        str(output_dir / "burn_mask.tif"),
    )

    # Severity map GeoTIFF
    write_severity_tif(
        severity_map, reference_meta,
        str(output_dir / "burn_severity.tif"),
    )

    # Visualization GeoTIFF
    vis_path = args.vis_output or str(output_dir / "burn_visualization.tif")
    write_visualization_tif(rgb, reference_meta, vis_path)

    logger.info("=" * 60)
    logger.info("BURN DETECTION PIPELINE — COMPLETE")
    logger.info(f"  Burned area: {area_stats['burned_area_ha']} ha")
    logger.info(f"  Burned pixels: {area_stats['burned_pixels']:,}")
    logger.info(f"  Confidence: {output_json['summary']['confidence']}%")
    logger.info(f"  Output: {args.output}")
    logger.info("=" * 60)

    return output_json


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Burnt Crop Area Detection Pipeline — Sentinel-2 bi-temporal dNBR analysis"
    )

    # .SAFE directory inputs
    parser.add_argument("--before_safe", help="Glob for pre-fire .SAFE directory")
    parser.add_argument("--after_safe", help="Glob for post-fire .SAFE directory")

    # Pre-extracted band inputs
    parser.add_argument("--before_b04", help="Pre-fire B04 (Red, 10m) GeoTIFF")
    parser.add_argument("--before_b08", help="Pre-fire B08 (NIR, 10m) GeoTIFF")
    parser.add_argument("--before_b12", help="Pre-fire B12 (SWIR, 20m) GeoTIFF")
    parser.add_argument("--after_b04", help="Post-fire B04 (Red, 10m) GeoTIFF")
    parser.add_argument("--after_b08", help="Post-fire B08 (NIR, 10m) GeoTIFF")
    parser.add_argument("--after_b12", help="Post-fire B12 (SWIR, 20m) GeoTIFF")

    # SCL masks (optional)
    parser.add_argument("--scl_before", help="Pre-fire SCL GeoTIFF (optional)")
    parser.add_argument("--scl_after", help="Post-fire SCL GeoTIFF (optional)")

    # Output
    parser.add_argument("--output", default="outputs/burn_result.json",
                        help="Path for output JSON")
    parser.add_argument("--vis_output", help="Path for visualization GeoTIFF (optional)")

    # Debug
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate input combinations
    has_safe = args.before_safe and args.after_safe
    has_bands = (
        args.before_b04 and args.before_b08 and args.before_b12
        and args.after_b04 and args.after_b08 and args.after_b12
    )

    if not has_safe and not has_bands:
        parser.error(
            "Provide either:\n"
            "  --before_safe + --after_safe\n"
            "OR all of:\n"
            "  --before_b04 --before_b08 --before_b12\n"
            "  --after_b04  --after_b08  --after_b12"
        )

    run_burn_pipeline(args)


if __name__ == "__main__":
    main()
