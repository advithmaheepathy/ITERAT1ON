"""
run_real_burn_analysis.py
=========================
Run burn detection on real Sentinel-2 data:
    BEFORE: S2A_MSIL2A_20191216 (L2A — has SCL)
    AFTER:  S2B_MSIL1C_20200110 (L1C — no SCL)

Tile T53HQA — eastern Australia, 2019-2020 bushfire season.
"""

import sys
import logging
from pathlib import Path

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
)
from src.run_burn_pipeline import (
    build_output_json,
    write_json,
    write_burn_mask_tif,
    write_severity_tif,
    write_visualization_tif,
)
from src.preprocess import build_cloud_mask

from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("real_burn")

# ── Paths ──
BASE = Path(__file__).parent.parent
RAW = BASE / "data" / "raw"

BEFORE_SAFE = RAW / "S2A_MSIL2A_20191216T004701_N0500_R102_T53HQA_20230619T020958.SAFE"
AFTER_SAFE = RAW / "S2B_MSIL1C_20200110T004659_N0500_R102_T53HQA_20230424T042733.SAFE"

# BEFORE bands (L2A)
BEFORE_B04 = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R10m" / "T53HQA_20191216T004701_B04_10m.jp2"
BEFORE_B08 = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R10m" / "T53HQA_20191216T004701_B08_10m.jp2"
BEFORE_B12 = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R20m" / "T53HQA_20191216T004701_B12_20m.jp2"
BEFORE_SCL = BEFORE_SAFE / "GRANULE" / "L2A_T53HQA_A023408_20191216T004701" / "IMG_DATA" / "R20m" / "T53HQA_20191216T004701_SCL_20m.jp2"

# AFTER bands (L1C)
AFTER_B04 = AFTER_SAFE / "GRANULE" / "L1C_T53HQA_A014857_20200110T005652" / "IMG_DATA" / "T53HQA_20200110T004659_B04.jp2"
AFTER_B08 = AFTER_SAFE / "GRANULE" / "L1C_T53HQA_A014857_20200110T005652" / "IMG_DATA" / "T53HQA_20200110T004659_B08.jp2"
AFTER_B12 = AFTER_SAFE / "GRANULE" / "L1C_T53HQA_A014857_20200110T005652" / "IMG_DATA" / "T53HQA_20200110T004659_B12.jp2"

OUTPUT_DIR = BASE / "outputs"


def load_band_jp2(path: Path) -> tuple:
    """Load a JP2 band as float32 surface reflectance."""
    logger.info(f"Loading: {path.name}")
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        logger.info(f"  Shape: {data.shape}, CRS: {src.crs}, Res: {src.res}")

    # Sentinel-2 DN → surface reflectance
    if data.max() > 1.5:
        data = data / 10000.0
        logger.info(f"  DN→SR: [{data.min():.4f}, {data.max():.4f}]")

    return data, meta


def resample_to_target(source, src_meta, dst_meta, method=WarpResampling.bilinear):
    """Resample source array to match target grid."""
    resampled = np.zeros((dst_meta["height"], dst_meta["width"]), dtype=np.float32)
    reproject(
        source=source,
        destination=resampled,
        src_transform=src_meta["transform"],
        src_crs=src_meta["crs"],
        dst_transform=dst_meta["transform"],
        dst_crs=dst_meta["crs"],
        resampling=method,
    )
    logger.info(f"  Resampled: {source.shape} → {resampled.shape}")
    return resampled


def load_scl_mask(scl_path, target_meta):
    """Load SCL, resample to 10m, build cloud+water mask."""
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
    logger.info(f"  Water pixels: {water.sum():,}")
    valid = valid & (~water)
    logger.info(f"  Valid: {valid.mean()*100:.1f}%")
    return valid


def main():
    processing_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Verify all files exist
    all_paths = [BEFORE_B04, BEFORE_B08, BEFORE_B12, BEFORE_SCL,
                 AFTER_B04, AFTER_B08, AFTER_B12]
    for p in all_paths:
        if not p.exists():
            logger.error(f"Missing: {p}")
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("REAL BURN ANALYSIS — 2019-2020 Australian Bushfires")
    logger.info("BEFORE: S2A L2A 2019-12-16  |  AFTER: S2B L1C 2020-01-10")
    logger.info("Tile: T53HQA (Eastern Australia)")
    logger.info("=" * 60)

    # ── Load BEFORE bands ──
    logger.info("\n── LOADING BEFORE BANDS ──")
    b04_before, b04_meta = load_band_jp2(BEFORE_B04)
    b08_before, _ = load_band_jp2(BEFORE_B08)
    b12_before_raw, b12_meta = load_band_jp2(BEFORE_B12)
    b12_before = resample_to_target(b12_before_raw, b12_meta, b04_meta)

    # ── Load AFTER bands ──
    logger.info("\n── LOADING AFTER BANDS ──")
    b04_after, b04_after_meta = load_band_jp2(AFTER_B04)
    b08_after, _ = load_band_jp2(AFTER_B08)
    b12_after_raw, b12_after_meta = load_band_jp2(AFTER_B12)
    b12_after = resample_to_target(b12_after_raw, b12_after_meta, b04_meta)

    # ── Align grids if needed ──
    if b04_after.shape != b04_before.shape:
        logger.info(f"\n── ALIGNING: {b04_after.shape} → {b04_before.shape} ──")
        b04_after = resample_to_target(b04_after, b04_after_meta, b04_meta)
        b08_after_raw, b08_after_meta = load_band_jp2(AFTER_B08)
        b08_after = resample_to_target(b08_after_raw, b08_after_meta, b04_meta)

    # ── Cloud + water masking (from BEFORE L2A only) ──
    logger.info("\n── CLOUD & WATER MASKING ──")
    logger.info("BEFORE SCL:")
    combined_mask = load_scl_mask(BEFORE_SCL, b04_meta)

    valid_pct = round(combined_mask.mean() * 100, 2)
    logger.info(f"Combined valid: {valid_pct}%")

    # ── NDVI (before) ──
    logger.info("\n── NDVI (pre-fire) ──")
    ndvi_before = compute_ndvi(b04_before, b08_before, combined_mask)

    # ── NBR ──
    logger.info("\n── NBR ──")
    nbr_before = compute_nbr(b08_before, b12_before, combined_mask)
    nbr_after = compute_nbr(b08_after, b12_after, combined_mask)

    # ── dNBR ──
    logger.info("\n── dNBR ──")
    dnbr = compute_dnbr(nbr_before, nbr_after)

    # ── Burn mask ──
    logger.info("\n── BURN MASK ──")
    burn_mask = build_burn_mask(dnbr, ndvi_before)

    # ── Severity ──
    logger.info("\n── SEVERITY ──")
    severity_map = classify_burn(dnbr, burn_mask)

    # ── Area ──
    logger.info("\n── AREA ──")
    area_stats = calculate_area(burn_mask, severity_map)

    # ── Visualization ──
    logger.info("\n── VISUALIZATION ──")
    rgb = create_burn_visualization(
        b04=b04_after, b08=b08_after,
        burn_mask=burn_mask, severity_map=severity_map,
        ndvi_before=ndvi_before, valid_mask=combined_mask,
    )

    # ── Write outputs ──
    logger.info("\n── WRITING OUTPUTS ──")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    processing_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    preprocessing_info = {
        "before": {
            "product": "S2A_MSIL2A_20191216T004701",
            "level": "L2A",
            "date": "2019-12-16",
            "tile": "T53HQA",
        },
        "after": {
            "product": "S2B_MSIL1C_20200110T004659",
            "level": "L1C",
            "date": "2020-01-10",
            "tile": "T53HQA",
        },
        "region": "Eastern Australia",
        "event": "2019-2020 Australian Bushfire Season",
        "bands_used": ["B04 (Red, 10m)", "B08 (NIR, 10m)", "B12 (SWIR, 20m→10m)"],
        "cloud_mask": "SCL from BEFORE only (L2A)",
        "valid_pixel_pct_combined": valid_pct,
    }

    output_json = build_output_json(
        area_stats=area_stats,
        preprocessing_info=preprocessing_info,
        processing_start=processing_start,
        processing_end=processing_end,
    )
    write_json(output_json, str(OUTPUT_DIR / "burn_result_real.json"))
    write_burn_mask_tif(burn_mask, b04_meta, str(OUTPUT_DIR / "burn_mask_real.tif"))
    write_severity_tif(severity_map, b04_meta, str(OUTPUT_DIR / "burn_severity_real.tif"))
    write_visualization_tif(rgb, b04_meta, str(OUTPUT_DIR / "burn_visualization_real.tif"))

    # ── Summary ──
    logger.info("\n" + "=" * 60)
    logger.info("BURN ANALYSIS COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Burned area:    {area_stats['burned_area_ha']} ha")
    logger.info(f"  Burned pixels:  {area_stats['burned_pixels']:,}")
    logger.info(f"  Confidence:     {output_json['summary']['confidence']}%")
    for key, info in area_stats["severity_distribution"].items():
        if info["pixel_count"] > 0:
            logger.info(f"  {info['label']:20s}: {info['area_ha']} ha ({info['pixel_count']:,} px)")
    logger.info(f"  Output: {OUTPUT_DIR / 'burn_result_real.json'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
