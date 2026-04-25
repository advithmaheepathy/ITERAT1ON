"""
burn_analysis_v3.py
===================
Physically correct burn severity analysis using dNBR (delta Normalized Burn Ratio).

INPUTS  : Two Sentinel-2 L2A .SAFE products from the SAME tile:
            - pre-fire  image  (earlier date)
            - post-fire image  (later date)

OUTPUTS : JSON with:
            - dNBR statistics
            - Burn severity classification (USGS standard)
            - Per-tile breakdown
            - Summary statistics

FORMULAS:
  NBR  = (B08 - B12) / (B08 + B12)     NIR=B08 (10m), SWIR2=B12 (20m→10m)
  dNBR = NBR_pre - NBR_post

BURN SEVERITY THRESHOLDS (USGS standard):
  dNBR < -0.1          → Enhanced Regrowth (post-fire green-up)
  -0.1 ≤ dNBR < 0.1   → Unburned
  0.1  ≤ dNBR < 0.27  → Low Burn Severity
  0.27 ≤ dNBR < 0.44  → Moderate-Low Severity
  0.44 ≤ dNBR < 0.66  → Moderate-High Severity
  dNBR ≥ 0.66         → High Severity
"""

import sys, json, argparse, logging
from datetime import timezone, datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling as WarpResampling

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.preprocess import find_safe_bands, read_band_as_float32, resample_to_match, _read_scl_raw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler("logs/burn_analysis_v3.log")],
)
logger = logging.getLogger("burn_analysis_v3")

# ── USGS standard dNBR thresholds ─────────────────────────────────────────────
USGS_SEVERITY = [
    {"label": "Enhanced Regrowth", "class": "regrowth",        "dnbr_min": -9.9, "dnbr_max": -0.10},
    {"label": "Unburned",          "class": "unburned",         "dnbr_min": -0.10, "dnbr_max":  0.10},
    {"label": "Low Severity",      "class": "low",              "dnbr_min":  0.10, "dnbr_max":  0.27},
    {"label": "Moderate-Low",      "class": "moderate_low",     "dnbr_min":  0.27, "dnbr_max":  0.44},
    {"label": "Moderate-High",     "class": "moderate_high",    "dnbr_min":  0.44, "dnbr_max":  0.66},
    {"label": "High Severity",     "class": "high",             "dnbr_min":  0.66, "dnbr_max":  9.9},
]

SCL_CLOUD = [0, 1, 3, 8, 9, 10, 11]   # cloud, shadow, nodata classes


# ─────────────────────────────────────────────────────────────────────────────
def _parse_date(safe_name: str) -> str:
    """Extract ISO date from SAFE folder name."""
    try:
        parts = safe_name.split("_")
        dt = parts[2]
        return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}T{dt[9:11]}:{dt[11:13]}:{dt[13:15]}Z"
    except Exception:
        return "UNKNOWN"


def _load_b12(safe_dir: str, b08_meta: dict) -> np.ndarray:
    """
    Find B12 (SWIR2, 20m) in a .SAFE product and resample to match B08 (10m).
    B12 is essential for NBR.
    """
    safe_path = Path(safe_dir)
    patterns = ["*_B12_20m.tif", "*_B12_20m.jp2", "*_B12.tif", "*_B12.jp2"]
    found = None
    for pat in patterns:
        matches = list(safe_path.rglob(pat))
        if matches:
            found = matches[0]
            break
    if found is None:
        raise FileNotFoundError(
            f"B12 (SWIR2) not found in {safe_dir}.\n"
            f"Tried: {patterns}\n"
            f"This band is REQUIRED for NBR calculation."
        )
    logger.info(f"  B12 found: {found.relative_to(safe_path)}")

    with rasterio.open(found) as src:
        b12_raw = src.read(1).astype(np.float32)
        b12_meta = src.meta.copy()

    # DN → reflectance
    if b12_meta['dtype'] in ('uint16', 'int16'):
        b12_raw = b12_raw / 10000.0

    # Resample 20m → 10m to match B08
    b12_10m = resample_to_match(b12_raw, b12_meta, b08_meta)
    return b12_10m.astype(np.float32)


def _build_cloud_mask(scl_path: str, b08_meta: dict) -> np.ndarray:
    """Build cloud mask at 10m resolution. True = valid pixel."""
    with rasterio.open(scl_path) as src:
        scl_raw = src.read(1)
        scl_meta = src.meta.copy()
    # Resample SCL to 10m
    scl_10m = resample_to_match(scl_raw, scl_meta, b08_meta)
    invalid = np.zeros(scl_10m.shape, dtype=bool)
    for c in SCL_CLOUD:
        invalid |= (scl_10m == c)
    return ~invalid


def _compute_nbr(b08: np.ndarray, b12: np.ndarray,
                 valid_mask: np.ndarray) -> np.ndarray:
    """Compute NBR = (B08 - B12) / (B08 + B12).  NaN where invalid."""
    nbr = np.full(b08.shape, np.nan, dtype=np.float32)
    denom = b08 + b12
    ok = valid_mask & (denom != 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        nbr[ok] = (b08[ok] - b12[ok]) / denom[ok]
    # Clip to physical range
    nbr = np.where(np.isnan(nbr), np.nan,
                   np.clip(nbr, -1.0, 1.0).astype(np.float32))
    return nbr


def _classify_dnbr(dnbr_val: float) -> dict:
    for tier in USGS_SEVERITY:
        if tier["dnbr_min"] <= dnbr_val < tier["dnbr_max"]:
            return tier
    return USGS_SEVERITY[-1]   # fallback: high severity


def _ndvi(b04, b08, mask):
    """Quick NDVI for vegetation pre-filter (optional)."""
    ndvi = np.full(b04.shape, np.nan, dtype=np.float32)
    denom = b08 + b04
    ok = mask & (denom != 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi[ok] = (b08[ok] - b04[ok]) / denom[ok]
    return ndvi


def _pixel_stats(arr: np.ndarray) -> dict:
    v = arr[~np.isnan(arr)]
    if v.size == 0:
        return {"n": 0}
    pcts = np.percentile(v, [5, 10, 25, 50, 75, 90, 95]).tolist()
    return {
        "n":      int(v.size),
        "mean":   round(float(v.mean()), 6),
        "median": round(float(np.median(v)), 6),
        "std":    round(float(v.std()), 6),
        "min":    round(float(v.min()), 6),
        "max":    round(float(v.max()), 6),
        "p5":     round(pcts[0], 6), "p10": round(pcts[1], 6),
        "p25":    round(pcts[2], 6), "p75": round(pcts[4], 6),
        "p90":    round(pcts[5], 6), "p95": round(pcts[6], 6),
    }


# ─────────────────────────────────────────────────────────────────────────────
def run_burn_analysis(pre_safe: str, post_safe: str, output_path: str):
    ts_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    Path("logs").mkdir(exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)

    pre_date  = _parse_date(Path(pre_safe).name)
    post_date = _parse_date(Path(post_safe).name)

    logger.info("=" * 80)
    logger.info("BURN SEVERITY ANALYSIS  v3  (dNBR — USGS standard)")
    logger.info("=" * 80)
    logger.info(f"  Pre-fire  : {Path(pre_safe).name}  ({pre_date})")
    logger.info(f"  Post-fire : {Path(post_safe).name}  ({post_date})")

    # ── Step 1: Load pre-fire bands ──────────────────────────────────────
    logger.info("\n── STEP 1: PRE-FIRE BANDS ──")
    pre_bands = find_safe_bands(pre_safe)
    b04_pre,  b04_pre_meta  = read_band_as_float32(pre_bands["B04"])
    b08_pre,  b08_pre_meta  = read_band_as_float32(pre_bands["B08"])
    b12_pre  = _load_b12(pre_safe, b08_pre_meta)
    mask_pre = _build_cloud_mask(str(pre_bands["SCL"]), b08_pre_meta)
    logger.info(f"  B08 shape: {b08_pre.shape}  valid: {mask_pre.sum():,} / {mask_pre.size:,} ({mask_pre.mean()*100:.2f}%)")

    # ── Step 2: Load post-fire bands ─────────────────────────────────────
    logger.info("\n── STEP 2: POST-FIRE BANDS ──")
    post_bands = find_safe_bands(post_safe)
    b04_post, b04_post_meta = read_band_as_float32(post_bands["B04"])
    b08_post, b08_post_meta = read_band_as_float32(post_bands["B08"])
    b12_post = _load_b12(post_safe, b08_post_meta)
    mask_post = _build_cloud_mask(str(post_bands["SCL"]), b08_post_meta)
    logger.info(f"  B08 shape: {b08_post.shape}  valid: {mask_post.sum():,} / {mask_post.size:,} ({mask_post.mean()*100:.2f}%)")

    # ── Step 3: Compute NBR pre & post ───────────────────────────────────
    logger.info("\n── STEP 3: NBR COMPUTATION ──")
    nbr_pre  = _compute_nbr(b08_pre,  b12_pre,  mask_pre)
    nbr_post = _compute_nbr(b08_post, b12_post, mask_post)

    nbr_pre_vals  = nbr_pre[~np.isnan(nbr_pre)]
    nbr_post_vals = nbr_post[~np.isnan(nbr_post)]
    logger.info(f"  NBR pre  — mean={nbr_pre_vals.mean():.4f}  std={nbr_pre_vals.std():.4f}  "
                f"range=[{nbr_pre_vals.min():.4f},{nbr_pre_vals.max():.4f}]")
    logger.info(f"  NBR post — mean={nbr_post_vals.mean():.4f}  std={nbr_post_vals.std():.4f}  "
                f"range=[{nbr_post_vals.min():.4f},{nbr_post_vals.max():.4f}]")

    # ── Step 4: Compute dNBR ─────────────────────────────────────────────
    logger.info("\n── STEP 4: dNBR = NBR_pre − NBR_post ──")
    # Valid only where BOTH dates have valid pixels (intersection mask)
    joint_valid = ~np.isnan(nbr_pre) & ~np.isnan(nbr_post)
    dnbr = np.full(nbr_pre.shape, np.nan, dtype=np.float32)
    dnbr[joint_valid] = nbr_pre[joint_valid] - nbr_post[joint_valid]

    total_px = dnbr.size
    valid_px = int(joint_valid.sum())
    valid_pct = valid_px / total_px * 100
    logger.info(f"  Joint valid pixels : {valid_px:,} / {total_px:,}  ({valid_pct:.2f}%)")

    dnbr_vals = dnbr[joint_valid]
    logger.info(f"  dNBR mean={dnbr_vals.mean():.4f}  median={np.median(dnbr_vals):.4f}  "
                f"std={dnbr_vals.std():.4f}  range=[{dnbr_vals.min():.4f},{dnbr_vals.max():.4f}]")

    # ── Step 5: Severity classification ──────────────────────────────────
    logger.info("\n── STEP 5: BURN SEVERITY CLASSIFICATION (USGS) ──")
    severity_counts = {t["class"]: 0 for t in USGS_SEVERITY}
    severity_px     = {t["class"]: int(0) for t in USGS_SEVERITY}

    for tier in USGS_SEVERITY:
        mask = (dnbr >= tier["dnbr_min"]) & (dnbr < tier["dnbr_max"])
        n = int(mask.sum())
        severity_px[tier["class"]]     = n
        severity_counts[tier["class"]] = n

    total_burned_px = sum(
        severity_px[c["class"]] for c in USGS_SEVERITY
        if c["class"] not in ("unburned", "regrowth")
    )
    burned_frac = total_burned_px / valid_px if valid_px else 0

    logger.info(f"\n  {'Severity Class':25s}  {'Pixels':>10s}  {'%':>7s}")
    logger.info(f"  {'─'*25}  {'─'*10}  {'─'*7}")
    for tier in USGS_SEVERITY:
        c = tier["class"]
        n = severity_px[c]
        pct = n / valid_px * 100 if valid_px else 0
        bar = "█" * int(pct / 2)
        logger.info(f"  {tier['label']:25s}  {n:10,}  {pct:6.2f}%  {bar}")
    logger.info(f"\n  Total burned pixels : {total_burned_px:,}  ({burned_frac*100:.2f}% of valid)")

    # ── Step 6: NDVI pre vs post (vegetation change) ──────────────────────
    logger.info("\n── STEP 6: NDVI VEGETATION CHANGE ──")
    ndvi_pre  = _ndvi(b04_pre,  b08_pre,  mask_pre)
    ndvi_post = _ndvi(b04_post, b08_post, mask_post)
    ndvi_change = np.full(ndvi_pre.shape, np.nan, dtype=np.float32)
    ndvi_change[joint_valid] = ndvi_pre[joint_valid] - ndvi_post[joint_valid]

    ndvi_pre_v    = ndvi_pre[joint_valid]
    ndvi_post_v   = ndvi_post[joint_valid]
    ndvi_change_v = ndvi_change[joint_valid]
    logger.info(f"  NDVI pre  mean : {ndvi_pre_v.mean():.4f}")
    logger.info(f"  NDVI post mean : {ndvi_post_v.mean():.4f}")
    logger.info(f"  NDVI change    : {ndvi_change_v.mean():.4f}  "
                f"({'↑ increase' if ndvi_change_v.mean()>=0 else '↓ decrease — possible burn damage'})")

    # ── Step 7: Build output JSON ─────────────────────────────────────────
    logger.info("\n── STEP 7: BUILD OUTPUT ──")
    ts_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    pixel_area_ha = 100 / 10000   # 10m × 10m = 0.01 ha

    severity_distribution = {}
    for tier in USGS_SEVERITY:
        c = tier["class"]
        n = severity_px[c]
        pct = n / valid_px * 100 if valid_px else 0
        severity_distribution[c] = {
            "label":       tier["label"],
            "pixel_count": n,
            "area_ha":     round(n * pixel_area_ha, 2),
            "pct_of_valid": round(pct, 4),
            "dnbr_range":  [tier["dnbr_min"], tier["dnbr_max"]],
        }

    output = {
        "metadata": {
            "pipeline_version": "3.0.0",
            "analysis_type":    "burn_severity_dnbr",
            "processing_start": ts_start,
            "processing_end":   ts_end,
            "pre_fire": {
                "safe_name":          Path(pre_safe).name,
                "acquisition_date":   pre_date,
                "valid_pixel_pct":    round(mask_pre.mean() * 100, 4),
            },
            "post_fire": {
                "safe_name":          Path(post_safe).name,
                "acquisition_date":   post_date,
                "valid_pixel_pct":    round(mask_post.mean() * 100, 4),
            },
            "method": {
                "nbr_formula":   "NBR = (B08 - B12) / (B08 + B12)",
                "dnbr_formula":  "dNBR = NBR_pre - NBR_post",
                "bands_used":    ["B04 (Red, 10m)", "B08 (NIR, 10m)", "B12 (SWIR2, 20m→10m)"],
                "severity_standard": "USGS Key et al. 2006",
                "cloud_filtering": f"SCL classes {SCL_CLOUD} masked",
                "joint_mask": "Pixels valid in BOTH dates used for dNBR",
            },
        },
        "summary": {
            "total_pixels":    total_px,
            "joint_valid_pixels": valid_px,
            "joint_valid_pct": round(valid_pct, 4),
            "total_burned_pixels": total_burned_px,
            "total_burned_ha":     round(total_burned_px * pixel_area_ha, 2),
            "burned_fraction_of_valid": round(burned_frac, 6),
            "dnbr_statistics": _pixel_stats(dnbr_vals),
            "nbr_pre_statistics":  _pixel_stats(nbr_pre_vals),
            "nbr_post_statistics": _pixel_stats(nbr_post_vals),
            "ndvi_change": {
                "ndvi_pre_mean":    round(float(ndvi_pre_v.mean()), 6),
                "ndvi_post_mean":   round(float(ndvi_post_v.mean()), 6),
                "ndvi_delta_mean":  round(float(ndvi_change_v.mean()), 6),
                "interpretation":   (
                    "Vegetation declined post-fire" if ndvi_change_v.mean() > 0.02 else
                    "Vegetation increased post-fire (regrowth or seasonal green-up)" if ndvi_change_v.mean() < -0.02 else
                    "No significant vegetation change detected"
                ),
            },
            "severity_distribution": severity_distribution,
        },
    }

    # Write JSON
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=lambda o: float(o) if hasattr(o, '__float__') else str(o))
    logger.info(f"Output written: {output_path}")

    # ── Human-readable summary ────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("BURN SEVERITY ANALYSIS — RESULTS")
    print("=" * 70)
    print(f"Pre-fire   : {pre_date}  ({Path(pre_safe).name[:30]}...)")
    print(f"Post-fire  : {post_date}  ({Path(post_safe).name[:30]}...)")
    print(f"\nJoint valid pixels : {valid_px:,} / {total_px:,}  ({valid_pct:.2f}%)")
    print(f"\ndNBR statistics:")
    print(f"  mean   = {dnbr_vals.mean():.4f}")
    print(f"  median = {np.median(dnbr_vals):.4f}")
    print(f"  std    = {dnbr_vals.std():.4f}")
    print(f"  range  = [{dnbr_vals.min():.4f}, {dnbr_vals.max():.4f}]")
    print(f"\nBurn Severity Distribution (USGS standard):")
    print(f"  {'Severity Class':25s}  {'Area (ha)':>10s}  {'% Valid':>8s}")
    print(f"  {'─'*25}  {'─'*10}  {'─'*8}")
    for tier in USGS_SEVERITY:
        c   = tier["class"]
        info = severity_distribution[c]
        bar  = "█" * int(info["pct_of_valid"] / 2)
        print(f"  {tier['label']:25s}  {info['area_ha']:10,.1f}  {info['pct_of_valid']:7.2f}%  {bar}")
    print(f"\nTotal burned area  : {output['summary']['total_burned_ha']:,.1f} ha")
    print(f"Burned fraction    : {burned_frac*100:.2f}% of valid land")
    print(f"\nNDVI vegetation change:")
    print(f"  Pre-fire NDVI mean  : {ndvi_pre_v.mean():.4f}")
    print(f"  Post-fire NDVI mean : {ndvi_post_v.mean():.4f}")
    print(f"  Delta NDVI          : {ndvi_change_v.mean():+.4f}  → {output['summary']['ndvi_change']['interpretation']}")
    print(f"\nFull output: {output_path}")
    print("=" * 70)

    return output


# ─────────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Burn Severity Analysis v3 (dNBR)")
    p.add_argument("--pre",    required=True, help="Pre-fire .SAFE directory")
    p.add_argument("--post",   required=True, help="Post-fire .SAFE directory")
    p.add_argument("--output", default="outputs/burn_result_v3.json")
    args = p.parse_args()
    run_burn_analysis(args.pre, args.post, args.output)


if __name__ == "__main__":
    main()
