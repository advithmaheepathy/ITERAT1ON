"""
run_pipeline_improved.py
=========================
PRODUCTION-READY crop stress detection pipeline.

IMPROVEMENTS:
1. Robust NDVI computation (outlier removal, smoothing)
2. Water masking (CRITICAL for accuracy)
3. Vegetation filtering (NDVI > 0.2)
4. Strict alert rules (30% veg, 40% stress)
5. Clear logging and error handling

USAGE:
  python src/run_pipeline_improved.py \\
      --safe_dir "data/raw/S2C_MSIL2A_*.SAFE" \\
      --aoi data/aoi.geojson \\
      --output outputs/result_improved.json
"""

import sys
import json
import logging
import argparse
from datetime import timezone, datetime
from pathlib import Path

import numpy as np
import rasterio

# Import improved modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.preprocess import preprocess_safe  # Use existing for .SAFE extraction
from src.preprocess_improved import build_combined_mask
from src.ndvi_improved import compute_ndvi_from_files
from src.tiling import generate_tiles
from src.stress_classifier_improved import classify_tiles_improved, THRESHOLDS
from src.alert_generator_improved import generate_alerts_improved, ALERT_CONFIG
from src.output_writer import build_output_json, write_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pipeline_improved.log"),
    ]
)
logger = logging.getLogger("pipeline_improved")


def load_aoi(aoi_path: str) -> dict:
    with open(aoi_path) as f:
        geojson = json.load(f)
    if geojson.get("type") == "FeatureCollection":
        return geojson["features"][0]["geometry"]
    elif geojson.get("type") == "Feature":
        return geojson["geometry"]
    return geojson


def run_improved_pipeline(args):
    """Execute the IMPROVED pipeline with all production-ready filters."""
    
    processing_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    logger.info("="*80)
    logger.info("PRODUCTION-READY CROP STRESS DETECTION PIPELINE")
    logger.info("="*80)
    logger.info(f"Started at: {processing_start}")
    logger.info("")
    
    Path("logs").mkdir(exist_ok=True)
    
    # Load AOI
    aoi_geometry = None
    if args.aoi and Path(args.aoi).exists():
        aoi_geometry = load_aoi(args.aoi)
        logger.info(f"AOI loaded from {args.aoi}")
    
    # --- STEP 1: Preprocess .SAFE (extract bands) ---
    if args.safe_dir:
        import glob
        safe_dirs = glob.glob(args.safe_dir)
        if not safe_dirs:
            logger.error(f"No .SAFE directories found: {args.safe_dir}")
            sys.exit(1)
        
        safe_dir = safe_dirs[0]
        logger.info(f"Processing: {safe_dir}")
        
        # Use existing preprocess (but we'll rebuild the mask)
        preprocessing_meta = preprocess_safe(
            safe_dir=safe_dir,
            output_dir="data/processed",
            aoi_geometry=aoi_geometry,
        )
        
        b04_path = preprocessing_meta["b04_path"]
        b08_path = preprocessing_meta["b08_path"]
        scl_path = preprocessing_meta["scl_path"]
        
    elif args.b04 and args.b08:
        logger.info(f"Using pre-extracted bands: {args.b04}, {args.b08}")
        b04_path = args.b04
        b08_path = args.b08
        scl_path = args.scl
        
        preprocessing_meta = {
            "safe_name": "manual_input",
            "b04_path": b04_path,
            "b08_path": b08_path,
            "scl_path": scl_path,
        }
    else:
        logger.error("Must provide --safe_dir or both --b04 and --b08")
        sys.exit(1)
    
    # --- STEP 2: Build IMPROVED mask (clouds + water) ---
    logger.info("")
    logger.info("="*80)
    logger.info("LOADING BANDS AND BUILDING IMPROVED MASK")
    logger.info("="*80)
    
    # Load SCL
    with rasterio.open(scl_path) as src:
        scl_array = src.read(1)
    
    # Build combined mask (clouds + water)
    valid_mask, mask_stats = build_combined_mask(
        scl_array,
        mask_water=True,  # CRITICAL
        mask_clouds=True,
    )
    
    # Write improved mask
    mask_output = Path("data/processed") / "valid_mask_improved.tif"
    with rasterio.open(b04_path) as src:
        meta = src.meta.copy()
        meta.update({"dtype": "uint8", "count": 1, "driver": "GTiff"})
    
    with rasterio.open(mask_output, "w", **meta) as dst:
        dst.write(valid_mask.astype(np.uint8), 1)
    
    logger.info(f"Improved mask saved: {mask_output}")
    
    # --- STEP 3: Compute IMPROVED NDVI ---
    logger.info("")
    ndvi_output = "data/processed/ndvi_improved.tif"
    
    ndvi_array, ndvi_metadata = compute_ndvi_from_files(
        b04_path=b04_path,
        b08_path=b08_path,
        valid_mask_path=str(mask_output),
        output_path=ndvi_output,
        apply_smoothing=True,  # Gaussian filter
    )
    
    # --- STEP 4: Generate tiles ---
    logger.info("")
    with rasterio.open(b04_path) as src:
        transform = src.transform
        crs = src.crs
    
    tiles = generate_tiles(
        ndvi=ndvi_array,
        transform=transform,
        crs=crs,
        tile_size_km=5.0,
        valid_mask=valid_mask,
    )
    
    if not tiles:
        logger.error("No tiles generated!")
        sys.exit(1)
    
    # --- STEP 5: Classify tiles (IMPROVED) ---
    logger.info("")
    classified_tiles = classify_tiles_improved(
        tiles=tiles,
        ndvi_array=ndvi_array,
        thresholds=THRESHOLDS,
        min_vegetation_fraction=0.3,
    )
    
    # --- STEP 6: Generate alerts (IMPROVED) ---
    logger.info("")
    processing_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    alerts = generate_alerts_improved(
        classified_tiles=classified_tiles,
        alert_config=ALERT_CONFIG,
        processing_timestamp=processing_end,
    )
    
    # --- STEP 7: Build output JSON ---
    logger.info("")
    logger.info("="*80)
    logger.info("BUILDING OUTPUT")
    logger.info("="*80)
    
    # Add mask stats to preprocessing metadata
    preprocessing_meta.update({
        "mask_stats": mask_stats,
        "water_masked": True,
    })
    
    output = build_output_json(
        preprocessing_metadata=preprocessing_meta,
        ndvi_metadata=ndvi_metadata,
        tiles=tiles,
        classified_tiles=classified_tiles,
        alerts=alerts,
        config={"thresholds": THRESHOLDS, "alert_config": ALERT_CONFIG},
        processing_start_iso=processing_start,
        processing_end_iso=processing_end,
    )
    
    # Add improvement notes
    output["metadata"]["improvements"] = {
        "water_masking": "Enabled (SCL=6 masked to prevent false vegetation)",
        "outlier_removal": "NDVI outside [-0.2, 1.0] removed",
        "gaussian_smoothing": "Applied (sigma=1.0) for noise reduction",
        "vegetation_filtering": "Only NDVI > 0.2 analyzed",
        "strict_alerts": "30% vegetation + 40% stress required",
    }
    
    write_json(output, args.output)
    
    logger.info("")
    logger.info("="*80)
    logger.info("PIPELINE COMPLETE")
    logger.info("="*80)
    logger.info(f"Output: {args.output}")
    logger.info(f"Alerts: {len(alerts)}")
    logger.info(f"Processing time: {processing_start} → {processing_end}")
    logger.info("="*80)
    
    return output


def main():
    parser = argparse.ArgumentParser(
        description="IMPROVED Crop Stress Detection Pipeline"
    )
    
    parser.add_argument("--safe_dir", help="Path to .SAFE directory")
    parser.add_argument("--b04", help="Path to B04 GeoTIFF")
    parser.add_argument("--b08", help="Path to B08 GeoTIFF")
    parser.add_argument("--scl", help="Path to SCL GeoTIFF")
    parser.add_argument("--aoi", help="Path to AOI GeoJSON")
    parser.add_argument("--output", default="outputs/result_improved.json")
    
    args = parser.parse_args()
    
    if not args.safe_dir and not (args.b04 and args.b08):
        parser.error("Must provide --safe_dir or both --b04 and --b08")
    
    run_improved_pipeline(args)


if __name__ == "__main__":
    main()
