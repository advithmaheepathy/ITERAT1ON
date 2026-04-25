"""
run_pipeline.py
===============
Main entry point for the crop stress detection pipeline.

USAGE:
  # Full pipeline run:
  python src/run_pipeline.py \
      --safe_dir "data/raw/S2A_MSIL2A_20240615*.SAFE" \
      --aoi data/aoi.geojson \
      --output outputs/result.json \
      --config configs/pipeline_config.yaml

  # Validate existing output:
  python src/run_pipeline.py --validate outputs/result.json

  # Process already-preprocessed bands (skip .SAFE extraction):
  python src/run_pipeline.py \
      --b04 data/processed/S2A_20240615_T43PGN_B04.tif \
      --b08 data/processed/S2A_20240615_T43PGN_B08.tif \
      --mask data/processed/S2A_20240615_T43PGN_valid_mask.tif \
      --output outputs/result.json
"""

import sys
import json
import logging
import argparse
import glob
from datetime import timezone, datetime
from pathlib import Path

import numpy as np
import rasterio
import yaml

# Local imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.preprocess import preprocess_safe
from src.ndvi import compute_ndvi_from_files
from src.tiling import generate_tiles
from src.stress_classifier import classify_tiles, DEFAULT_THRESHOLDS
from src.alert_generator import generate_alerts
from src.output_writer import build_output_json, write_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pipeline.log"),
    ]
)
logger = logging.getLogger("pipeline")


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_aoi(aoi_path: str) -> dict:
    with open(aoi_path) as f:
        geojson = json.load(f)
    if geojson.get("type") == "FeatureCollection":
        return geojson["features"][0]["geometry"]
    elif geojson.get("type") == "Feature":
        return geojson["geometry"]
    return geojson


def run_pipeline(args, config: dict):
    """Execute the full pipeline."""
    processing_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Pipeline started at {processing_start}")
    
    Path("logs").mkdir(exist_ok=True)
    
    # --- Step 1: Preprocess .SAFE product ---
    aoi_geometry = None
    if args.aoi and Path(args.aoi).exists():
        aoi_geometry = load_aoi(args.aoi)
        logger.info(f"AOI loaded from {args.aoi}")
    
    if args.safe_dir:
        # Find .SAFE directories
        safe_dirs = glob.glob(args.safe_dir)
        if not safe_dirs:
            logger.error(f"No .SAFE directories found matching: {args.safe_dir}")
            sys.exit(1)
        
        # Process the first one (or add loop for multi-date)
        safe_dir = safe_dirs[0]
        logger.info(f"Processing {len(safe_dirs)} .SAFE product(s)")
        logger.info(f"Using: {safe_dir}")
        
        preprocessing_meta = preprocess_safe(
            safe_dir=safe_dir,
            output_dir="data/processed",
            aoi_geometry=aoi_geometry,
        )
        preprocessing_meta["safe_name"] = Path(safe_dir).name
        
        b04_path = preprocessing_meta["b04_path"]
        b08_path = preprocessing_meta["b08_path"]
        mask_path = preprocessing_meta["cloud_mask_path"]
        
    elif args.b04 and args.b08:
        # Use pre-extracted band files
        logger.info(f"Using pre-extracted bands: {args.b04}, {args.b08}")
        b04_path = args.b04
        b08_path = args.b08
        mask_path = args.mask
        
        # Build minimal preprocessing metadata
        preprocessing_meta = {
            "safe_name": "manual_input",
            "b04_path": b04_path,
            "b08_path": b08_path,
            "cloud_mask_path": mask_path,
            "acquisition_date": "UNKNOWN (manually provided bands)",
            "cloud_cover_pct": None,
            "valid_pixel_pct": None,
        }
        
        # Try to get CRS from the band file
        with rasterio.open(b04_path) as src:
            preprocessing_meta["crs"] = str(src.crs)
            preprocessing_meta["shape_pixels"] = list(src.shape)
    
    else:
        logger.error("Must provide either --safe_dir or both --b04 and --b08")
        sys.exit(1)
    
    # --- Step 2: Compute NDVI ---
    logger.info("="*50)
    logger.info("STEP 2: NDVI COMPUTATION")
    logger.info("="*50)
    
    ndvi_output_path = f"data/processed/{Path(b04_path).stem.replace('_B04','')}_NDVI.tif"
    
    ndvi_array, ndvi_metadata = compute_ndvi_from_files(
        b04_path=b04_path,
        b08_path=b08_path,
        valid_mask_path=mask_path,
        output_path=ndvi_output_path,
    )
    
    # --- Step 3: Load spatial reference for tiling ---
    with rasterio.open(b04_path) as src:
        transform = src.transform
        crs = src.crs
    
    # Load valid mask as boolean array
    if mask_path and Path(mask_path).exists():
        with rasterio.open(mask_path) as src:
            valid_mask = src.read(1).astype(bool)
    else:
        valid_mask = ~np.isnan(ndvi_array)
    
    # --- Step 4: Generate tiles ---
    logger.info("="*50)
    logger.info("STEP 3: TILING")
    logger.info("="*50)
    
    tile_size_km = config.get("tile_size_km", 5.0)
    tiles = generate_tiles(
        ndvi=ndvi_array,
        transform=transform,
        crs=crs,
        tile_size_km=tile_size_km,
        valid_mask=valid_mask,
    )
    
    if not tiles:
        logger.error("No tiles generated. Check AOI and cloud coverage.")
        sys.exit(1)
    
    # --- Step 5: Classify tiles ---
    logger.info("="*50)
    logger.info("STEP 4: STRESS CLASSIFICATION")
    logger.info("="*50)
    
    thresholds = config.get("ndvi_thresholds", DEFAULT_THRESHOLDS)
    classified_tiles = classify_tiles(tiles, thresholds)
    
    # --- Step 6: Generate alerts ---
    logger.info("="*50)
    logger.info("STEP 5: ALERT GENERATION")
    logger.info("="*50)
    
    alert_config = config.get("alerts", {})
    processing_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    alerts = generate_alerts(
        classified_tiles=classified_tiles,
        alert_config=alert_config,
        processing_timestamp=processing_end,
    )
    
    # --- Step 7: Build and write output JSON ---
    logger.info("="*50)
    logger.info("STEP 6: OUTPUT GENERATION")
    logger.info("="*50)
    
    output = build_output_json(
        preprocessing_metadata=preprocessing_meta,
        ndvi_metadata=ndvi_metadata,
        tiles=tiles,
        classified_tiles=classified_tiles,
        alerts=alerts,
        config=config,
        processing_start_iso=processing_start,
        processing_end_iso=processing_end,
    )
    
    write_json(output, args.output)
    
    return output


def validate_output(json_path: str):
    """
    Validate an existing output JSON.
    Checks internal consistency: NDVI values, alert coordinates, tile counts.
    """
    print(f"\nValidating: {json_path}")
    
    with open(json_path) as f:
        data = json.load(f)
    
    errors = []
    warnings = []
    
    # Check metadata
    acq = data.get("metadata", {}).get("source", {}).get("acquisition_datetime", "")
    if acq == "UNKNOWN":
        warnings.append("acquisition_datetime is UNKNOWN — was .SAFE name parseable?")
    
    # Check NDVI statistics are in valid range
    ndvi_s = data.get("summary", {}).get("ndvi_statistics", {})
    mean_ndvi = ndvi_s.get("mean")
    if mean_ndvi is not None:
        if not (-1.0 <= mean_ndvi <= 1.0):
            errors.append(f"NDVI mean={mean_ndvi} outside valid range [-1, 1]")
        if ndvi_s.get("min", 0) > ndvi_s.get("max", 0):
            errors.append("NDVI min > max — impossible")
        if ndvi_s.get("p25", 0) > ndvi_s.get("p75", 0):
            errors.append("NDVI p25 > p75 — impossible")
    
    # Check alert coordinates are plausible
    for alert in data.get("alerts", []):
        lat = alert["location"]["center_lat"]
        lon = alert["location"]["center_lon"]
        if not (-90 <= lat <= 90):
            errors.append(f"Alert {alert['alert_id']}: invalid lat={lat}")
        if not (-180 <= lon <= 180):
            errors.append(f"Alert {alert['alert_id']}: invalid lon={lon}")
        if not (-1.0 <= alert["ndvi_mean"] <= 1.0):
            errors.append(f"Alert {alert['alert_id']}: NDVI mean {alert['ndvi_mean']} out of range")
        if not (0 <= alert["stressed_pixel_fraction"] <= 1):
            errors.append(f"Alert {alert['alert_id']}: stressed_pixel_fraction out of [0,1]")
    
    # Check tile count consistency
    n_tiles_summary = data.get("summary", {}).get("total_tiles", 0)
    n_tiles_array = len(data.get("tiles", []))
    if n_tiles_summary != n_tiles_array:
        errors.append(f"Tile count mismatch: summary says {n_tiles_summary}, array has {n_tiles_array}")
    
    # Print results
    print(f"\n--- Validation Results ---")
    print(f"Tiles: {n_tiles_array}")
    print(f"Alerts: {len(data.get('alerts', []))}")
    print(f"Acquisition: {acq}")
    
    if ndvi_s:
        print(f"\nNDVI (sanity check):")
        print(f"  mean={mean_ndvi:.4f}  std={ndvi_s.get('std'):.4f}")
        print(f"  min={ndvi_s.get('min'):.4f}   max={ndvi_s.get('max'):.4f}")
        print(f"  p25={ndvi_s.get('p25'):.4f}  p75={ndvi_s.get('p75'):.4f}")
    
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠ {w}")
    
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
        return False
    else:
        print(f"\n✓ Output validated successfully")
        return True


def main():
    parser = argparse.ArgumentParser(description="Crop Stress Detection Pipeline")
    
    # Input modes
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--safe_dir", help="Glob pattern for .SAFE directories, e.g. 'data/raw/*.SAFE'"
    )
    input_group.add_argument(
        "--validate", metavar="JSON_PATH",
        help="Validate an existing output JSON instead of running pipeline"
    )
    
    # Pre-extracted band mode
    parser.add_argument("--b04", help="Path to pre-extracted B04 GeoTIFF")
    parser.add_argument("--b08", help="Path to pre-extracted B08 GeoTIFF")
    parser.add_argument("--mask", help="Path to valid pixel mask GeoTIFF (optional)")
    
    # Common args
    parser.add_argument("--aoi", default="data/aoi.geojson", help="AOI GeoJSON file")
    parser.add_argument("--output", default="outputs/result.json", help="Output JSON path")
    parser.add_argument("--config", default="configs/pipeline_config.yaml")
    parser.add_argument("--tile_size_km", type=float, help="Override tile size in km")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.validate:
        success = validate_output(args.validate)
        sys.exit(0 if success else 1)
    
    if not args.safe_dir and not (args.b04 and args.b08):
        parser.error("Must provide --safe_dir or both --b04 and --b08")
    
    config = load_config(args.config)
    
    if args.tile_size_km:
        config["tile_size_km"] = args.tile_size_km
    
    run_pipeline(args, config)


if __name__ == "__main__":
    main()