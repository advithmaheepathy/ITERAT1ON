"""
pipeline_v2.py
==============
Scientifically correct, configurable NDVI crop stress pipeline.

USAGE:
  python src/pipeline_v2.py \
      --safe_dir "C:/s2_data/S2B_MSIL2A_*.SAFE" \
      --config configs/pipeline_config.yaml \
      --output outputs/result_v2.json

All parameters come from the config file — nothing is hardcoded.
"""

import sys
import json
import logging
import argparse
from datetime import timezone, datetime
from pathlib import Path

import numpy as np
import rasterio
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.preprocess import preprocess_safe
from src.preprocess_improved import build_combined_mask
from src.ndvi_v2 import compute_ndvi_from_safe_bands
from src.tiling import generate_tiles
from src.classifier_v2 import classify_all_tiles, STRESS_CLASSES, DEFAULT_THRESHOLDS
from src.output_writer_v2 import build_output, write_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pipeline_v2.log"),
    ],
)
logger = logging.getLogger("pipeline_v2")


# ─────────────────────────────────────────────────────────────────────────────
# Config loading
# ─────────────────────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    logger.info(f"Config loaded: {config_path}")
    return cfg


def _classification_thresholds(cfg: dict) -> dict:
    """Extract classification thresholds from config."""
    c = cfg.get("classification", {})
    return {
        "bare_soil_max":            c.get("bare_soil_max",       0.15),
        "severe_stress_max":        c.get("severe_stress_max",   0.30),
        "moderate_stress_max":      c.get("moderate_stress_max", 0.45),
        "mild_stress_max":          c.get("mild_stress_max",     0.60),
        "min_valid_pixel_fraction": c.get("min_valid_pixel_fraction", 0.10),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(args):
    processing_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    Path("logs").mkdir(exist_ok=True)
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)

    logger.info("=" * 80)
    logger.info("NDVI CROP STRESS PIPELINE  v2.0  (scientifically correct)")
    logger.info("=" * 80)
    logger.info(f"Started: {processing_start}")

    # ── Config ────────────────────────────────────────────────────────────────
    cfg = load_config(args.config)
    ndvi_cfg  = cfg.get("ndvi", {})
    mask_cfg  = cfg.get("masking", {})
    alert_cfg = cfg.get("alerts", {})
    area_cfg  = cfg.get("area", {})
    thresholds = _classification_thresholds(cfg)
    alert_classes = alert_cfg.get("alert_classes", ["severe_stress", "moderate_stress"])
    tile_size_km  = cfg.get("tile_size_km", 5.0)

    logger.info(f"  tile_size_km           : {tile_size_km}")
    logger.info(f"  ndvi valid range       : [{ndvi_cfg.get('valid_range_min',-1.0)}, {ndvi_cfg.get('valid_range_max',1.0)}]")
    logger.info(f"  mask_water             : {mask_cfg.get('mask_water', True)}")
    logger.info(f"  apply_smoothing        : {ndvi_cfg.get('apply_smoothing', False)}")
    logger.info(f"  min_valid_px_fraction  : {thresholds['min_valid_pixel_fraction']}")
    logger.info(f"  alert_classes          : {alert_classes}")

    # ── Step 1: Preprocess .SAFE ──────────────────────────────────────────────
    logger.info("")
    logger.info("── STEP 1: PREPROCESS .SAFE ──")
    if args.safe_dir:
        import glob
        safe_list = glob.glob(args.safe_dir)
        if not safe_list:
            logger.error(f"No .SAFE directory found: {args.safe_dir}")
            sys.exit(1)
        safe_dir = safe_list[0]
        logger.info(f"  Source: {safe_dir}")
        pre = preprocess_safe(safe_dir=safe_dir, output_dir="data/processed")
        b04_path = pre["b04_path"]
        b08_path = pre["b08_path"]
        scl_path = pre["scl_path"]
    elif args.b04 and args.b08:
        b04_path = args.b04
        b08_path = args.b08
        scl_path = args.scl
        pre = {
            "b04_path": b04_path, "b08_path": b08_path, "scl_path": scl_path,
            "acquisition_date": "UNKNOWN", "cloud_cover_pct": None, "valid_pixel_pct": None,
            "shape_pixels": None, "crs": None, "transform": None,
        }
    else:
        logger.error("Provide --safe_dir or --b04 + --b08 + --scl")
        sys.exit(1)

    # ── Step 2: Build cloud/water mask ───────────────────────────────────────
    logger.info("")
    logger.info("── STEP 2: MASKING ──")
    with rasterio.open(scl_path) as src:
        scl_array = src.read(1)

    valid_mask, mask_stats = build_combined_mask(
        scl_array,
        mask_water=mask_cfg.get("mask_water", True),
        mask_clouds=mask_cfg.get("mask_clouds", True),
    )

    # Write mask
    mask_path = Path("data/processed") / "valid_mask_v2.tif"
    with rasterio.open(b04_path) as src:
        m = src.meta.copy()
        m.update({"dtype": "uint8", "count": 1, "driver": "GTiff"})
    with rasterio.open(mask_path, "w", **m) as dst:
        dst.write(valid_mask.astype(np.uint8), 1)
    logger.info(f"  Mask written: {mask_path}")

    # ── Step 3: Compute NDVI ─────────────────────────────────────────────────
    logger.info("")
    logger.info("── STEP 3: NDVI COMPUTATION ──")
    ndvi_out = "data/processed/ndvi_v2.tif"
    ndvi_array, ndvi_meta = compute_ndvi_from_safe_bands(
        b04_path=b04_path,
        b08_path=b08_path,
        valid_mask_path=str(mask_path),
        output_path=ndvi_out,
        ndvi_min=ndvi_cfg.get("valid_range_min", -1.0),
        ndvi_max=ndvi_cfg.get("valid_range_max",  1.0),
        apply_smoothing=ndvi_cfg.get("apply_smoothing", False),
        smoothing_sigma=ndvi_cfg.get("smoothing_sigma", 1.0),
    )

    # ── Validation print ─────────────────────────────────────────────────────
    total_px  = ndvi_meta["total_pixels"]
    valid_px  = ndvi_meta["valid_pixels"]
    valid_pct = ndvi_meta["valid_pixel_pct"]
    stats     = ndvi_meta["ndvi_stats"]

    logger.info("")
    logger.info("── VALIDATION (pre-classification) ──")
    logger.info(f"  Total pixels       : {total_px:,}")
    logger.info(f"  Valid NDVI pixels  : {valid_px:,}  ({valid_pct:.2f}%)")
    logger.info(f"  NDVI range         : [{stats['min']:.4f}, {stats['max']:.4f}]")
    logger.info(f"  NDVI mean          : {stats['mean']:.4f}")
    logger.info(f"  NDVI std           : {stats['std']:.4f}")
    if valid_pct < 70:
        logger.warning(
            f"  ⚠  Valid pixel % ({valid_pct:.1f}%) is below 70%. "
            "Results may be unreliable — check cloud cover."
        )
    else:
        logger.info(f"  ✓  Valid pixel coverage is adequate ({valid_pct:.1f}%)")

    # ── Step 4: Tiling ───────────────────────────────────────────────────────
    logger.info("")
    logger.info("── STEP 4: TILING ──")
    with rasterio.open(b04_path) as src:
        transform = src.transform
        crs = src.crs

    tiles = generate_tiles(
        ndvi=ndvi_array,
        transform=transform,
        crs=crs,
        tile_size_km=tile_size_km,
        valid_mask=valid_mask,
    )
    if not tiles:
        logger.error("No tiles generated!")
        sys.exit(1)
    logger.info(f"  {len(tiles)} tiles generated")

    # ── Step 5: Classification ───────────────────────────────────────────────
    logger.info("")
    logger.info("── STEP 5: CLASSIFICATION ──")
    classified = classify_all_tiles(
        tiles=tiles,
        ndvi_array=ndvi_array,
        thresholds=thresholds,
        alert_classes=alert_classes,
    )

    # ── Step 6: Alerts ───────────────────────────────────────────────────────
    logger.info("")
    logger.info("── STEP 6: ALERTS ──")
    processing_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    min_stressed = alert_cfg.get("min_stressed_fraction", 0.40)
    min_valid    = alert_cfg.get("min_valid_pixel_fraction", 0.10)

    alerts = []
    for t in classified:
        cls = t["classification"]
        if not cls.get("is_alert_class", False):
            continue
        if cls.get("valid_pixel_fraction", 0) < min_valid:
            continue
        if cls.get("stressed_fraction", 0) < min_stressed:
            continue
        alerts.append({
            "alert_id":  f"ALERT_{t['tile_id']}_{processing_end.replace(':','').replace('-','')}",
            "severity":  "WARNING",
            "tile_id":   t["tile_id"],
            "location": {
                "center_lat": t["center_lat"],
                "center_lon": t["center_lon"],
                "bbox": {
                    "lat_min": t["lat_min"], "lat_max": t["lat_max"],
                    "lon_min": t["lon_min"], "lon_max": t["lon_max"],
                },
            },
            "primary_class":       cls["primary_class"],
            "stress_label":        cls["label"],
            "ndvi_mean":           cls["ndvi_mean"],
            "stressed_fraction":   cls["stressed_fraction"],
            "valid_pixel_fraction":cls["valid_pixel_fraction"],
            "pixel_breakdown":     cls.get("pixel_breakdown", {}),
            "detected_at":         processing_end,
        })
    logger.info(f"  {len(alerts)} alerts generated")

    # ── Step 7: Build output JSON ─────────────────────────────────────────────
    logger.info("")
    logger.info("── STEP 7: OUTPUT ──")
    pre.update({
        "mask_stats": mask_stats,
        "acquisition_date": pre.get("acquisition_date", "UNKNOWN"),
    })

    output = build_output(
        preprocessing_meta=pre,
        ndvi_meta=ndvi_meta,
        classified_tiles=classified,
        alerts=alerts,
        thresholds=thresholds,
        config=cfg,
        processing_start=processing_start,
        processing_end=processing_end,
    )
    write_json(output, args.output)

    # ── Final summary ─────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 80)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 80)
    logger.info(f"  Output          : {args.output}")
    logger.info(f"  Total tiles     : {len(classified)}")
    logger.info(f"  Alerts          : {len(alerts)}")
    logger.info(f"  Valid pixel %   : {valid_pct:.2f}%")
    logger.info(f"  NDVI mean       : {stats['mean']:.4f}")
    logger.info("=" * 80)
    return output


# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NDVI Crop Stress Pipeline v2")
    parser.add_argument("--safe_dir", help="Glob path to .SAFE directory")
    parser.add_argument("--b04", help="Pre-extracted B04 GeoTIFF")
    parser.add_argument("--b08", help="Pre-extracted B08 GeoTIFF")
    parser.add_argument("--scl", help="Pre-extracted SCL GeoTIFF")
    parser.add_argument("--config", default="configs/pipeline_config.yaml")
    parser.add_argument("--output", default="outputs/result_v2.json")
    args = parser.parse_args()

    if not args.safe_dir and not (args.b04 and args.b08):
        parser.error("Provide --safe_dir  OR  --b04 + --b08 + --scl")

    run_pipeline(args)


if __name__ == "__main__":
    main()
