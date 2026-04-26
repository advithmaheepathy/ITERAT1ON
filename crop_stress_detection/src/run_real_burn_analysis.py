"""
run_real_burn_analysis.py
=========================
Run burn detection on real Sentinel-2 data:
    BEFORE: S2A_MSIL2A_20191216 (L2A — has SCL)
    AFTER:  S2B_MSIL2A_20200130 (L2A — has SCL)

Tile T53HQA — eastern Australia, 2019-2020 bushfire season.

Reliability improvements:
    - Separate before/after masks, union strategy (|) not intersection (&)
    - Additional NDVI vegetation filter on combined mask
    - Fallback to AFTER-only mask if combined valid% < 50%
    - Full severity distribution across all valid pixels
    - Proper burned_fraction_valid using valid pixel count
    - Confidence score based on valid coverage
    - Warnings array in output JSON
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio.warp import reproject
from rasterio.warp import Resampling as WarpResampling

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.burn_detection import (
    compute_ndvi,
    compute_nbr,
    compute_dnbr,
    build_burn_mask,
    classify_burn,
    calculate_area,
    create_burn_visualization,
    PIXEL_AREA_HA,
)
from src.preprocess import build_cloud_mask

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("real_burn")

# ── Paths ────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent
RAW = BASE / "data" / "raw"

BEFORE_SAFE = Path("C:/dss") / "S2A_MSIL2A_20191216T004701_N0500_R102_T53HQA_20230619T020958.SAFE" / "S2A_MSIL2A_20191216T004701_N0500_R102_T53HQA_20230619T020958.SAFE"
AFTER_SAFE = Path("C:/dss") / "S2B_MSIL2A_20200130T004659_N0500_R102_T53HQA_20230426T105901.SAFE" / "S2B_MSIL2A_20200130T004659_N0500_R102_T53HQA_20230426T105901.SAFE"

BEFORE_B04 = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R10m" / "T53HQA_20191216T004701_B04_10m.jp2"
BEFORE_B08 = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R10m" / "T53HQA_20191216T004701_B08_10m.jp2"
BEFORE_B12 = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R20m" / "T53HQA_20191216T004701_B12_20m.jp2"
BEFORE_SCL = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R20m" / "T53HQA_20191216T004701_SCL_20m.jp2"

AFTER_B04 = AFTER_SAFE / "GRANULE" / "L2A_T53HQA_A015143_20200130T005534" / "IMG_DATA" / "R10m" / "T53HQA_20200130T004659_B04_10m.jp2"
AFTER_B08 = AFTER_SAFE / "GRANULE" / "L2A_T53HQA_A015143_20200130T005534" / "IMG_DATA" / "R10m" / "T53HQA_20200130T004659_B08_10m.jp2"
AFTER_B12 = AFTER_SAFE / "GRANULE" / "L2A_T53HQA_A015143_20200130T005534" / "IMG_DATA" / "R20m" / "T53HQA_20200130T004659_B12_20m.jp2"
AFTER_SCL = AFTER_SAFE / "GRANULE" / "L2A_T53HQA_A015143_20200130T005534" / "IMG_DATA" / "R20m" / "T53HQA_20200130T004659_SCL_20m.jp2"

OUTPUT_DIR = BASE / "outputs"

# ── Thresholds ────────────────────────────────────────────────────────────────
LOW_COVERAGE_THRESHOLD = 50.0   # Warn if valid% below this
FALLBACK_THRESHOLD = 30.0       # Use AFTER-only mask below this


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_band_jp2(path: Path) -> tuple:
    """Load a JP2 band as float32 surface reflectance."""
    logger.info(f"Loading: {path.name}")
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        logger.info(f"  Shape: {data.shape}, CRS: {src.crs}, Res: {src.res}")
    if data.max() > 1.5:
        data = data / 10000.0
        logger.info(f"  DN→SR: [{data.min():.4f}, {data.max():.4f}]")
    return data, meta


def resample_to_target(source, src_meta, dst_meta, method=WarpResampling.bilinear):
    """Resample source array to match target grid."""
    resampled = np.zeros((dst_meta["height"], dst_meta["width"]), dtype=np.float32)
    reproject(
        source=source, destination=resampled,
        src_transform=src_meta["transform"], src_crs=src_meta["crs"],
        dst_transform=dst_meta["transform"], dst_crs=dst_meta["crs"],
        resampling=method,
    )
    logger.info(f"  Resampled: {source.shape} → {resampled.shape}")
    return resampled


def load_scl_mask(scl_path, target_meta) -> np.ndarray:
    """Load SCL, resample to 10m, return cloud+water mask (True=valid)."""
    with rasterio.open(scl_path) as src:
        scl_raw = src.read(1)
        scl_meta = src.meta.copy()

    scl_10m = np.zeros((target_meta["height"], target_meta["width"]), dtype=scl_raw.dtype)
    reproject(
        source=scl_raw, destination=scl_10m,
        src_transform=scl_meta["transform"], src_crs=scl_meta["crs"],
        dst_transform=target_meta["transform"], dst_crs=target_meta["crs"],
        resampling=WarpResampling.nearest,
    )

    valid = build_cloud_mask(scl_10m)
    water = scl_10m == 6
    valid = valid & (~water)
    logger.info(f"  Water pixels masked: {water.sum():,} | Valid: {valid.mean()*100:.1f}%")
    return valid


def write_json(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Output JSON saved: {path}")


def write_tif(array: np.ndarray, meta: dict, path: str, dtype=None):
    m = meta.copy()
    if dtype:
        m["dtype"] = dtype
    m["count"] = 1
    if array.ndim == 3:
        m["count"] = array.shape[0]
    with rasterio.open(path, "w", **m) as dst:
        if array.ndim == 2:
            dst.write(array, 1)
        else:
            for i in range(array.shape[0]):
                dst.write(array[i], i + 1)
    logger.info(f"TIF saved: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    warnings = []
    processing_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Verify files
    for p in [BEFORE_B04, BEFORE_B08, BEFORE_B12, BEFORE_SCL,
              AFTER_B04, AFTER_B08, AFTER_B12, AFTER_SCL]:
        if not p.exists():
            logger.error(f"Missing: {p}")
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("REAL BURN ANALYSIS — 2019-2020 Australian Bushfires")
    logger.info("BEFORE: S2A L2A 2019-12-16  |  AFTER: S2B L2A 2020-01-30")
    logger.info("Tile: T53HQA (Eastern Australia)")
    logger.info("=" * 60)

    # ── STEP 1: Load bands ────────────────────────────────────────────────────
    logger.info("\n── LOADING BEFORE BANDS ──")
    b04_before, b04_meta = load_band_jp2(BEFORE_B04)
    b08_before, _ = load_band_jp2(BEFORE_B08)
    b12_before_raw, b12_meta = load_band_jp2(BEFORE_B12)
    b12_before = resample_to_target(b12_before_raw, b12_meta, b04_meta)

    logger.info("\n── LOADING AFTER BANDS ──")
    b04_after, b04_after_meta = load_band_jp2(AFTER_B04)
    b08_after, _ = load_band_jp2(AFTER_B08)
    b12_after_raw, b12_after_meta = load_band_jp2(AFTER_B12)
    b12_after = resample_to_target(b12_after_raw, b12_after_meta, b04_meta)

    # Align grids if needed
    if b04_after.shape != b04_before.shape:
        logger.info(f"\n── ALIGNING GRIDS: {b04_after.shape} → {b04_before.shape} ──")
        b04_after = resample_to_target(b04_after, b04_after_meta, b04_meta)
        b08_after_raw2, b08_after_meta2 = load_band_jp2(AFTER_B08)
        b08_after = resample_to_target(b08_after_raw2, b08_after_meta2, b04_meta)

    # ── STEP 2: Separate masks + union strategy ───────────────────────────────
    logger.info("\n── CLOUD & WATER MASKING ──")
    logger.info("BEFORE SCL:")
    mask_before = load_scl_mask(BEFORE_SCL, b04_meta)
    logger.info("AFTER SCL:")
    mask_after = load_scl_mask(AFTER_SCL, b04_meta)

    total_pixels = mask_before.size
    valid_pct_before = round(mask_before.mean() * 100, 2)
    valid_pct_after = round(mask_after.mean() * 100, 2)

    # Union: pixel is valid if clear in EITHER image
    union_mask = mask_before | mask_after
    valid_pct_union = round(union_mask.mean() * 100, 2)
    logger.info(f"\n  Before valid: {valid_pct_before}%")
    logger.info(f"  After  valid: {valid_pct_after}%")
    logger.info(f"  Union  valid: {valid_pct_union}%")

    # ── STEP 3: NDVI pre-fire (computed WITHOUT masking for max coverage) ─────
    logger.info("\n── NDVI (pre-fire, unmasked) ──")
    ndvi_before_full = compute_ndvi(b04_before, b08_before)

    # ── STEP 4: Build combined valid mask (union + NDVI vegetation filter) ────
    ndvi_safe = np.nan_to_num(ndvi_before_full, nan=0.0)
    vegetation_mask = ndvi_safe > 0.3
    combined_mask = union_mask & vegetation_mask
    valid_pct_combined = round(combined_mask.mean() * 100, 2)
    valid_pixel_count = int(combined_mask.sum())

    logger.info(f"  Vegetation filter (NDVI>0.3): {vegetation_mask.mean()*100:.1f}%")
    logger.info(f"  Combined valid (union ∩ NDVI): {valid_pct_combined}%  ({valid_pixel_count:,} px)")

    # ── STEP 5: Data quality check + fallback ────────────────────────────────
    mask_strategy = "union_with_ndvi"
    if valid_pct_combined < FALLBACK_THRESHOLD:
        w = (f"Combined valid pixel coverage {valid_pct_combined}% is critically low (<{FALLBACK_THRESHOLD}%). "
             f"Falling back to AFTER-only mask.")
        logger.warning(w)
        warnings.append(w)
        combined_mask = mask_after & vegetation_mask
        valid_pct_combined = round(combined_mask.mean() * 100, 2)
        valid_pixel_count = int(combined_mask.sum())
        mask_strategy = "after_only_fallback"
        logger.info(f"  Fallback valid: {valid_pct_combined}%  ({valid_pixel_count:,} px)")

    if valid_pct_combined < LOW_COVERAGE_THRESHOLD:
        w = (f"Valid pixel coverage is {valid_pct_combined}% (below {LOW_COVERAGE_THRESHOLD}%). "
             f"Results may be unreliable. Use with caution for insurance reporting.")
        logger.warning(w)
        warnings.append(w)

    # ── STEP 6: Index computation on combined mask ────────────────────────────
    logger.info("\n── NDVI (pre-fire, masked) ──")
    ndvi_before = compute_ndvi(b04_before, b08_before, combined_mask)

    logger.info("\n── NBR ──")
    # For NBR: before uses mask_before where available, else union
    nbr_before_mask = mask_before if mask_before.mean() > 0.05 else combined_mask
    nbr_after_mask = mask_after if mask_after.mean() > 0.05 else combined_mask
    nbr_before = compute_nbr(b08_before, b12_before, combined_mask)
    nbr_after = compute_nbr(b08_after, b12_after, combined_mask)

    logger.info("\n── dNBR ──")
    dnbr = compute_dnbr(nbr_before, nbr_after)

    # ── STEP 7: Burn mask (dNBR + NDVI + valid_mask) ─────────────────────────
    logger.info("\n── BURN MASK ──")
    burn_mask = build_burn_mask(dnbr, ndvi_before, valid_mask=combined_mask)

    # ── STEP 8: Full severity distribution on ALL valid pixels ────────────────
    logger.info("\n── SEVERITY DISTRIBUTION (all valid pixels) ──")
    severity_map = classify_burn(dnbr, burn_mask, valid_mask=combined_mask)

    # ── STEP 9: Area calculation with valid pixel denominator ─────────────────
    logger.info("\n── AREA CALCULATION ──")
    area_stats = calculate_area(burn_mask, severity_map, valid_pixels=valid_pixel_count)

    # ── STEP 10: Confidence score ─────────────────────────────────────────────
    # Based on: valid coverage, overlap between dates, not capped at 23%
    overlap_pct = round((mask_before & mask_after).mean() * 100, 2)
    raw_confidence = valid_pct_combined / 100.0
    # Penalty for low overlap
    overlap_factor = min(1.0, overlap_pct / 30.0)  # Full confidence if ≥30% overlap
    confidence = round(min(1.0, raw_confidence * (0.7 + 0.3 * overlap_factor)) * 100, 1)
    logger.info(f"\n  Confidence: {confidence}% (coverage={valid_pct_combined}%, overlap={overlap_pct}%)")

    # ── STEP 11: Visualization ────────────────────────────────────────────────
    logger.info("\n── VISUALIZATION ──")
    rgb = create_burn_visualization(
        b04=b04_after, b08=b08_after,
        burn_mask=burn_mask, severity_map=severity_map,
        ndvi_before=ndvi_before, valid_mask=combined_mask,
    )

    # ── STEP 12: Build output JSON ────────────────────────────────────────────
    logger.info("\n── WRITING OUTPUTS ──")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    processing_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sev_dist = area_stats["severity_distribution"]

    output = {
        "metadata": {
            "pipeline": "burn_detection",
            "pipeline_version": "2.0.0",
            "processing_start": processing_start,
            "processing_end": processing_end,
            "method": {
                "ndvi_formula": "NDVI = (B08 - B04) / (B08 + B04)",
                "nbr_formula": "NBR = (B08 - B12) / (B08 + B12)",
                "dnbr_formula": "dNBR = NBR_before - NBR_after",
                "vegetation_filter": "NDVI_before > 0.3",
                "burn_threshold": "dNBR > 0.3",
                "severity_thresholds": {
                    "unburned": 0.1,
                    "low": 0.3,
                    "moderate": 0.6,
                    "severe": "no_upper_limit",
                },
                "mask_strategy": mask_strategy,
                "cloud_mask": "SCL classes 0,1,3,8,9,10,11 masked",
                "water_mask": "SCL class 6 masked",
                "pixel_resolution_m": 10,
            },
            "source": {
                "before": {
                    "product": "S2A_MSIL2A_20191216T004701",
                    "level": "L2A",
                    "date": "2019-12-16",
                    "tile": "T53HQA",
                },
                "after": {
                    "product": "S2B_MSIL2A_20200130T004659",
                    "level": "L2A",
                    "date": "2020-01-30",
                    "tile": "T53HQA",
                },
                "region": "Eastern Australia",
                "event": "2019-2020 Australian Bushfire Season",
                "bands_used": ["B04 (Red, 10m)", "B08 (NIR, 10m)", "B12 (SWIR, 20m→10m)"],
            },
        },
        "summary": {
            "burned_area_ha": area_stats["burned_area_ha"],
            "burned_pixels": area_stats["burned_pixels"],
            "burned_fraction": area_stats["burned_fraction"],
            "burned_fraction_valid": area_stats["burned_fraction_valid"],
            "valid_pixel_pct_before": valid_pct_before,
            "valid_pixel_pct_after": valid_pct_after,
            "valid_pixel_pct_combined": valid_pct_combined,
            "total_pixels": area_stats["total_pixels"],
            "valid_pixels": valid_pixel_count,
            "severity_distribution": {
                k: {
                    "label": v["label"],
                    "pixel_count": v["pixel_count"],
                    "area_ha": v["area_ha"],
                    "pct_of_valid": round(v["pixel_count"] / max(valid_pixel_count, 1) * 100, 2),
                }
                for k, v in sev_dist.items()
            },
            "confidence": confidence,
            "warnings": warnings,
        },
    }

    write_json(output, str(OUTPUT_DIR / "burn_result_real.json"))

    # Write GeoTIFFs
    burn_tif_meta = b04_meta.copy()
    burn_tif_meta.update(dtype="uint8", count=1)
    write_tif(burn_mask.astype(np.uint8), burn_tif_meta, str(OUTPUT_DIR / "burn_mask_real.tif"))
    write_tif(severity_map, burn_tif_meta, str(OUTPUT_DIR / "burn_severity_real.tif"))

    vis_meta = b04_meta.copy()
    vis_meta.update(dtype="uint8", count=3)
    write_tif(np.moveaxis(rgb, -1, 0), vis_meta, str(OUTPUT_DIR / "burn_visualization_real.tif"))

    # ── Summary ────────────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("BURN ANALYSIS COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Burned area:          {area_stats['burned_area_ha']:,} ha")
    logger.info(f"  Burned pixels:        {area_stats['burned_pixels']:,}")
    logger.info(f"  Burned frac (valid):  {area_stats['burned_fraction_valid']*100:.3f}%")
    logger.info(f"  Valid before:         {valid_pct_before}%")
    logger.info(f"  Valid after:          {valid_pct_after}%")
    logger.info(f"  Valid combined:       {valid_pct_combined}%")
    logger.info(f"  Confidence:           {confidence}%")
    for k, v in sev_dist.items():
        if v["pixel_count"] > 0:
            pct = round(v["pixel_count"] / max(valid_pixel_count, 1) * 100, 2)
            logger.info(f"  {v['label']:20s}: {v['area_ha']:,} ha  ({pct}% of valid)")
    if warnings:
        logger.info(f"  ⚠ {len(warnings)} warning(s):")
        for w in warnings:
            logger.warning(f"    - {w}")
    logger.info(f"  Output: {OUTPUT_DIR / 'burn_result_real.json'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
