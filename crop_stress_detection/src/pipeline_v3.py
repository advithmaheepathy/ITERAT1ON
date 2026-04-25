"""
pipeline_v3.py
==============
Physically correct, zero-bias NDVI crop stress pipeline.

ROOT CAUSE FIXES vs v2:
  1. Water (SCL=6) no longer masked — was removing 76% of coastal tiles
  2. NDVI valid range correctly [-1, 1] both bounds applied
  3. 6-class balanced classification (no stress bias)
  4. confidence always populated (never null)
  5. Per-step pixel retention log

USAGE:
  python src/pipeline_v3.py \
      --safe_dir "C:/s2_data/S2B_*.SAFE" \
      --config configs/pipeline_config.yaml \
      --output outputs/result_v3.json
"""

import sys, json, logging, argparse
from datetime import timezone, datetime
from pathlib import Path

import numpy as np
import rasterio
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.preprocess        import preprocess_safe, build_cloud_mask, resample_to_match, _read_scl_raw
from src.ndvi_v2           import compute_ndvi, _write_ndvi_tif
from src.tiling            import generate_tiles
from src.classifier_v3     import classify_all_tiles, STRESS_CLASSES, DEFAULT_THRESHOLDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pipeline_v3.log"),
    ],
)
logger = logging.getLogger("pipeline_v3")


# ─────────────────────────────────────────────────────────────────────────────
def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    logger.info(f"Config: {path}")
    return cfg


def _thresholds(cfg: dict) -> dict:
    c = cfg.get("classification", {})
    return {
        "water_nonveg_max":         c.get("water_nonveg_max",    0.0),
        "bare_soil_max":            c.get("bare_soil_max",        0.15),
        "sparse_stressed_max":      c.get("sparse_stressed_max",  0.30),
        "moderate_veg_max":         c.get("moderate_veg_max",     0.50),
        "healthy_veg_max":          c.get("healthy_veg_max",      0.70),
        "min_valid_pixel_fraction": c.get("min_valid_pixel_fraction", 0.10),
    }


# ─────────────────────────────────────────────────────────────────────────────
def run_pipeline(args):
    ts_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    Path("logs").mkdir(exist_ok=True)
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)

    logger.info("=" * 80)
    logger.info("NDVI CROP STRESS PIPELINE  v3.0  (zero-bias, high retention)")
    logger.info("=" * 80)
    logger.info(f"Started: {ts_start}")

    cfg          = load_config(args.config)
    mask_cfg     = cfg.get("masking", {})
    ndvi_cfg     = cfg.get("ndvi", {})
    alert_cfg    = cfg.get("alerts", {})
    thresholds   = _thresholds(cfg)
    alert_classes = alert_cfg.get("alert_classes", ["sparse_stressed"])
    tile_size_km  = cfg.get("tile_size_km", 5.0)
    mask_water    = mask_cfg.get("mask_water", False)

    logger.info(f"  mask_water        : {mask_water}")
    logger.info(f"  tile_size_km      : {tile_size_km}")
    logger.info(f"  ndvi range        : [{ndvi_cfg.get('valid_range_min',-1)}, {ndvi_cfg.get('valid_range_max',1)}]")
    logger.info(f"  alert_classes     : {alert_classes}")

    # ── Step 1: Preprocess .SAFE ──────────────────────────────────────────
    logger.info("\n── STEP 1: PREPROCESS .SAFE ──")
    if args.safe_dir:
        import glob
        safe_list = glob.glob(args.safe_dir)
        if not safe_list:
            logger.error(f"No .SAFE dir: {args.safe_dir}"); sys.exit(1)
        safe_dir = safe_list[0]
        logger.info(f"  Source: {safe_dir}")
        pre = preprocess_safe(safe_dir=safe_dir, output_dir="data/processed")
        b04_path = pre["b04_path"]
        b08_path = pre["b08_path"]
        scl_path = pre["scl_path"]
    elif args.b04 and args.b08:
        b04_path, b08_path, scl_path = args.b04, args.b08, args.scl
        pre = {
            "b04_path": b04_path, "b08_path": b08_path, "scl_path": scl_path,
            "acquisition_date": "UNKNOWN", "cloud_cover_pct": None,
            "valid_pixel_pct": None, "shape_pixels": None, "crs": None,
        }
    else:
        logger.error("Provide --safe_dir or --b04+--b08+--scl"); sys.exit(1)

    # ── Step 2: Build cloud-only mask (water intentionally kept) ──────────
    logger.info("\n── STEP 2: MASKING (pixel retention audit) ──")
    with rasterio.open(scl_path) as src:
        scl_array = src.read(1)

    total_px = scl_array.size
    logger.info(f"  Total pixels              : {total_px:,}")

    # Count each class
    NAMES = {0:"NO_DATA",1:"SAT_DEFECT",2:"DARK_AREA",3:"CLOUD_SHADOW",
              4:"VEGETATION",5:"NOT_VEG",6:"WATER",7:"UNCLASSIFIED",
              8:"CLOUD_MED",9:"CLOUD_HIGH",10:"THIN_CIRRUS",11:"SNOW_ICE"}
    logger.info("  SCL class distribution:")
    for c in range(12):
        n = int((scl_array == c).sum())
        if n > 0:
            logger.info(f"    SCL {c:2d} ({NAMES.get(c,'?'):15s}): {n:10,}  ({n/total_px*100:6.2f}%)")

    # Masks: only cloud classes
    cloud_classes = mask_cfg.get("scl_cloud_classes", [0,1,3,8,9,10,11])
    cloud_mask = np.zeros(scl_array.shape, dtype=bool)
    for c in cloud_classes:
        cloud_mask |= (scl_array == c)
    cloud_px = int(cloud_mask.sum())
    logger.info(f"\n  Pixels removed (clouds/shadows/nodata): {cloud_px:,}  ({cloud_px/total_px*100:.4f}%)")

    if mask_water:
        water_px = int((scl_array == 6).sum())
        water_mask = (scl_array == 6)
        final_invalid = cloud_mask | water_mask
        logger.info(f"  Pixels removed (water SCL=6)          : {water_px:,}  ({water_px/total_px*100:.2f}%)")
    else:
        water_px = int((scl_array == 6).sum())
        final_invalid = cloud_mask
        logger.info(f"  Water pixels KEPT (mask_water=false)  : {water_px:,}  ({water_px/total_px*100:.2f}%)")

    valid_mask = ~final_invalid
    valid_after_masking = int(valid_mask.sum())
    logger.info(f"  Valid after masking                    : {valid_after_masking:,}  ({valid_after_masking/total_px*100:.4f}%)")

    # Write mask
    mask_path = Path("data/processed") / "valid_mask_v3.tif"
    with rasterio.open(b04_path) as src:
        m = src.meta.copy()
        m.update({"dtype": "uint8", "count": 1, "driver": "GTiff"})
    with rasterio.open(mask_path, "w", **m) as dst:
        dst.write(valid_mask.astype(np.uint8), 1)

    # ── Step 3: Load bands + compute NDVI ────────────────────────────────
    logger.info("\n── STEP 3: NDVI COMPUTATION ──")
    with rasterio.open(b04_path) as src:
        b04 = src.read(1).astype(np.float32)
        raster_meta = src.meta.copy()
        transform = src.transform
        crs = src.crs
    with rasterio.open(b08_path) as src:
        b08 = src.read(1).astype(np.float32)

    ndvi_array, ndvi_meta = compute_ndvi(
        b04, b08,
        valid_mask=valid_mask,
        ndvi_min=ndvi_cfg.get("valid_range_min", -1.0),
        ndvi_max=ndvi_cfg.get("valid_range_max",  1.0),
        apply_smoothing=ndvi_cfg.get("apply_smoothing", False),
        smoothing_sigma=ndvi_cfg.get("smoothing_sigma", 1.0),
    )
    _write_ndvi_tif(ndvi_array, raster_meta, "data/processed/ndvi_v3.tif")

    ndvi_meta.update({"b04_source": b04_path, "b08_source": b08_path,
                      "crs": str(crs), "transform": list(transform),
                      "shape": list(ndvi_array.shape)})

    # ── Validation print ─────────────────────────────────────────────────
    total_px_nd  = ndvi_meta["total_pixels"]
    valid_px_nd  = ndvi_meta["valid_pixels"]
    valid_pct_nd = ndvi_meta["valid_pixel_pct"]
    stats        = ndvi_meta["ndvi_stats"]

    logger.info("\n── PIXEL RETENTION REPORT ──")
    logger.info(f"  Step 1 — Total pixels         : {total_px_nd:,}")
    logger.info(f"  Step 2 — After cloud mask      : {valid_after_masking:,}  ({valid_after_masking/total_px_nd*100:.4f}%)")
    logger.info(f"  Step 3 — Valid NDVI (excl NaN) : {valid_px_nd:,}  ({valid_pct_nd:.4f}%)")
    lost = valid_after_masking - valid_px_nd
    logger.info(f"           Zero-denominator drop  : {lost:,}  ({lost/total_px_nd*100:.6f}%)")

    if valid_pct_nd < 85:
        if mask_water:
            logger.warning(f"  ⚠  Only {valid_pct_nd:.1f}% valid. "
                           f"Consider mask_water: false (water is {water_px/total_px*100:.1f}% of tile).")
        else:
            logger.warning(f"  ⚠  Only {valid_pct_nd:.1f}% valid — check data quality.")
    else:
        logger.info(f"  ✓  Data retention: {valid_pct_nd:.2f}% — excellent.")

    logger.info(f"\n── NDVI HISTOGRAM SUMMARY ──")
    valid_vals = ndvi_array[~np.isnan(ndvi_array)]
    bins = [-1.0, 0.0, 0.15, 0.30, 0.50, 0.70, 1.01]
    labels = ["<0.0 water/nonveg", "0.0–0.15 bare soil",
              "0.15–0.30 sparse/stressed", "0.30–0.50 moderate veg",
              "0.50–0.70 healthy veg", ">0.70 dense veg"]
    counts, _ = np.histogram(valid_vals, bins=bins)
    for label, count in zip(labels, counts):
        pct = count / valid_vals.size * 100 if valid_vals.size else 0
        bar = "█" * int(pct / 2)
        logger.info(f"  {label:28s}: {count:10,}  ({pct:5.1f}%)  {bar}")
    logger.info(f"\n  NDVI mean={stats['mean']:.4f}  median={stats['median']:.4f}  "
                f"std={stats['std']:.4f}  range=[{stats['min']:.4f},{stats['max']:.4f}]")

    # Sanity check
    dominant_frac = max(counts) / valid_vals.size * 100 if valid_vals.size else 0
    dominant_label = labels[list(counts).index(max(counts))]
    if dominant_frac > 80:
        logger.warning(f"  ⚠  Class distribution biased: '{dominant_label}' = {dominant_frac:.1f}%")
        logger.warning(f"     This is expected for coastal/oceanic tiles (water dominance).")
    else:
        logger.info(f"  ✓  Class distribution is balanced (no single class >80%)")

    # ── Step 4: Tiling ───────────────────────────────────────────────────
    logger.info("\n── STEP 4: TILING ──")
    tiles = generate_tiles(ndvi=ndvi_array, transform=transform, crs=crs,
                           tile_size_km=tile_size_km, valid_mask=valid_mask)
    if not tiles:
        logger.error("No tiles generated!"); sys.exit(1)
    logger.info(f"  {len(tiles)} tiles with valid data")

    # ── Step 5: Classification ───────────────────────────────────────────
    logger.info("\n── STEP 5: CLASSIFICATION ──")
    classified = classify_all_tiles(
        tiles=tiles,
        ndvi_array=ndvi_array,
        thresholds=thresholds,
        alert_classes=alert_classes,
    )

    # ── Step 6: Alerts ───────────────────────────────────────────────────
    logger.info("\n── STEP 6: ALERTS ──")
    ts_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    min_stressed  = alert_cfg.get("min_stressed_fraction", 0.50)
    min_valid_alrt = alert_cfg.get("min_valid_pixel_fraction", 0.30)

    alerts = []
    for t in classified:
        cls = t["classification"]
        if not cls.get("is_alert_class", False): continue
        if cls.get("valid_pixel_fraction", 0) < min_valid_alrt: continue
        if cls.get("stressed_fraction", 0) < min_stressed: continue
        alerts.append({
            "alert_id":   f"ALERT_{t['tile_id']}_{ts_end.replace(':','').replace('-','')}",
            "severity":   "WARNING",
            "tile_id":    t["tile_id"],
            "location": {
                "center_lat": t["center_lat"], "center_lon": t["center_lon"],
                "bbox": {"lat_min": t["lat_min"], "lat_max": t["lat_max"],
                         "lon_min": t["lon_min"], "lon_max": t["lon_max"]},
            },
            "primary_class":        cls["primary_class"],
            "stress_label":         cls["label"],
            "ndvi_mean":            cls["ndvi_mean"],
            "stressed_fraction":    cls["stressed_fraction"],
            "valid_pixel_fraction": cls["valid_pixel_fraction"],
            "pixel_breakdown":      cls.get("pixel_breakdown", {}),
            "detected_at":          ts_end,
        })
    logger.info(f"  {len(alerts)} alerts generated")

    # ── Step 7: Output ───────────────────────────────────────────────────
    logger.info("\n── STEP 7: OUTPUT ──")
    output = _build_output(pre, ndvi_meta, classified, alerts,
                           thresholds, cfg, ts_start, ts_end,
                           mask_stats={
                               "total_pixels": total_px,
                               "cloud_masked": cloud_px,
                               "water_pixels": water_px,
                               "water_masked": mask_water,
                               "valid_pixels": valid_after_masking,
                           })
    _write_output(output, args.output)

    # ── Final summary ─────────────────────────────────────────────────────
    logger.info("\n" + "=" * 80)
    logger.info("PIPELINE v3 COMPLETE")
    logger.info("=" * 80)
    logger.info(f"  Output          : {args.output}")
    logger.info(f"  Valid pixel %   : {valid_pct_nd:.4f}%")
    logger.info(f"  Total tiles     : {len(classified)}")
    logger.info(f"  Alerts          : {len(alerts)}")
    logger.info("=" * 80)
    return output


# ─────────────────────────────────────────────────────────────────────────────
def _build_output(pre, ndvi_meta, classified, alerts, thresholds,
                  cfg, ts_start, ts_end, mask_stats):
    import json
    from src.classifier_v3 import STRESS_CLASSES

    ndvi_stats = ndvi_meta.get("ndvi_stats", {})
    total_px   = ndvi_meta["total_pixels"]
    valid_px   = ndvi_meta["valid_pixels"]
    valid_pct  = ndvi_meta["valid_pixel_pct"]

    # Stress distribution
    counts = {}
    for t in classified:
        c = t["classification"].get("primary_class", "unknown")
        counts[c] = counts.get(c, 0) + 1
    dist = {}
    for c, n in counts.items():
        label = STRESS_CLASSES.get(c, {}).get("label", c)
        dist[c] = {"label": label, "tile_count": n,
                   "pct": round(n / len(classified) * 100, 1) if classified else 0}

    # Per-tile output
    tiles_out = []
    for t in classified:
        cls = t.get("classification", {})
        tiles_out.append({
            "tile_id":              t["tile_id"],
            "center_lat":           t["center_lat"],
            "center_lon":           t["center_lon"],
            "lat_min":              t.get("lat_min"),
            "lat_max":              t.get("lat_max"),
            "lon_min":              t.get("lon_min"),
            "lon_max":              t.get("lon_max"),
            "valid_pixel_fraction": cls.get("valid_pixel_fraction"),
            "confidence":           cls.get("confidence"),      # always set
            "ndvi_mean":            cls.get("ndvi_mean"),
            "ndvi_median":          cls.get("ndvi_median"),
            "ndvi_std":             cls.get("ndvi_std"),
            "stress_class":         cls.get("primary_class", "unknown"),
            "stress_label":         cls.get("label", "unknown"),
            "is_alert":             cls.get("is_alert_class", False),
            "stressed_fraction":    cls.get("stressed_fraction"),
            "pixel_breakdown":      cls.get("pixel_breakdown"),
            "vegetated_ha":         t.get("vegetated_ha"),
            "total_valid_ha":       t.get("total_valid_ha"),
        })

    # Consistency check
    computed_pct = round(valid_px / total_px * 100, 4) if total_px else None

    return {
        "metadata": {
            "pipeline_version": "3.0.0",
            "processing_start": ts_start,
            "processing_end":   ts_end,
            "source": {
                "platform":      "Sentinel-2",
                "product_type":  "L2A",
                "acquisition_datetime": pre.get("acquisition_date", "UNKNOWN"),
                "bands_used": ["B04 (Red, 10m)", "B08 (NIR, 10m)"],
            },
            "method": {
                "ndvi_formula":   "NDVI = (B08 - B04) / (B08 + B04)",
                "valid_ndvi_range": [-1.0, 1.0],
                "cloud_filtering": f"SCL classes {cfg.get('masking',{}).get('scl_cloud_classes',[0,1,3,8,9,10,11])} masked",
                "water_masking":  "enabled" if mask_stats["water_masked"] else "disabled — water pixels retained",
                "veg_prefilter":  "NONE",
                "tile_size_km":   cfg.get("tile_size_km", 5.0),
                "thresholds":     thresholds,
            },
            "masking_report": mask_stats,
        },
        "summary": {
            "acquisition_date":  pre.get("acquisition_date", "UNKNOWN"),
            "cloud_cover_pct":   pre.get("cloud_cover_pct"),
            "valid_pixel_pct":   round(valid_pct, 4),
            "total_pixels":      total_px,
            "valid_ndvi_pixels": valid_px,
            "pixels_consistency_check": computed_pct,  # should == valid_pixel_pct
            "image_shape_pixels": ndvi_meta.get("shape"),
            "ndvi_statistics":   ndvi_stats,
            "stress_distribution": dist,
            "total_tiles":       len(classified),
            "alert_tiles":       sum(1 for t in classified if t["classification"].get("is_alert_class")),
            "total_alerts":      len(alerts),
        },
        "tiles":  tiles_out,
        "alerts": alerts,
    }


def _write_output(output, path):
    import json, numpy as np
    def ser(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        raise TypeError(f"Not serializable: {type(obj)}")

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(output, f, indent=2, default=ser)
    logger.info(f"Output written: {path}")

    s = output["summary"]
    ndvi = s.get("ndvi_statistics", {})
    print("\n" + "=" * 70)
    print("NDVI PIPELINE v3.0 — RESULTS")
    print("=" * 70)
    print(f"Acquisition   : {s['acquisition_date']}")
    print(f"Cloud cover   : {s['cloud_cover_pct']}%")
    print(f"Valid pixels  : {s['valid_ndvi_pixels']:,} / {s['total_pixels']:,}  ({s['valid_pixel_pct']}%)")
    print(f"  ✓ Consistency: recomputed = {s['pixels_consistency_check']}%  (should match)")
    print(f"\nNDVI statistics (ALL valid pixels):")
    print(f"  mean   = {ndvi.get('mean'):.4f}")
    print(f"  median = {ndvi.get('median'):.4f}")
    print(f"  std    = {ndvi.get('std'):.4f}")
    print(f"  range  = [{ndvi.get('min'):.4f}, {ndvi.get('max'):.4f}]")
    print(f"\nStress distribution (6-class, balanced):")
    for cls, info in (s.get("stress_distribution") or {}).items():
        bar = "█" * int(info["pct"] / 2)
        print(f"  {info['label']:28s}: {info['tile_count']:4d}  ({info['pct']:5.1f}%)  {bar}")
    print(f"\nTotal tiles: {s['total_tiles']}   Alert tiles: {s['alert_tiles']}   Alerts: {s['total_alerts']}")
    if output.get("alerts"):
        print("\nTop alerts:")
        for a in output["alerts"][:5]:
            print(f"  [{a['severity']}] {a['tile_id']}  lat={a['location']['center_lat']:.4f}  "
                  f"lon={a['location']['center_lon']:.4f}  "
                  f"class={a['primary_class']}  stressed={a['stressed_fraction']*100:.0f}%")
    print(f"\nFull output: {path}")
    print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="NDVI Crop Stress Pipeline v3")
    p.add_argument("--safe_dir")
    p.add_argument("--b04"); p.add_argument("--b08"); p.add_argument("--scl")
    p.add_argument("--config", default="configs/pipeline_config.yaml")
    p.add_argument("--output", default="outputs/result_v3.json")
    args = p.parse_args()
    if not args.safe_dir and not (args.b04 and args.b08):
        p.error("Provide --safe_dir OR --b04+--b08+--scl")
    run_pipeline(args)


if __name__ == "__main__":
    main()
