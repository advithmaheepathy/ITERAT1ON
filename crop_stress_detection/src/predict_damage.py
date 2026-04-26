"""
predict_damage.py
=================
Loads the fine-tuned vegetation recovery model and predicts
vegetation damage using ONLY the pre-fire Sentinel-2 image.
Outputs a JSON with predicted damage statistics.
"""

import sys, json, argparse, time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

FEATURE_NAMES = ["B04_pre", "B08_pre", "B12_pre", "NDVI_pre", "NBR_pre"]
SAMPLE_SIZE = 100_000


def load_bands(safe_dir):
    import rasterio
    from src.preprocess import find_safe_bands, read_band_as_float32, resample_to_match

    bands = find_safe_bands(safe_dir)
    b04, _ = read_band_as_float32(bands["B04"])
    b08, b08_meta = read_band_as_float32(bands["B08"])

    safe_path = Path(safe_dir)
    b12_file = None
    for pat in ["*_B12_20m.jp2", "*_B12_20m.tif", "*_B12.jp2", "*_B12.tif"]:
        matches = list(safe_path.rglob(pat))
        if matches:
            b12_file = matches[0]
            break
    if not b12_file:
        raise FileNotFoundError(f"B12 not found in {safe_dir}")

    with rasterio.open(b12_file) as src:
        b12_raw = src.read(1).astype(np.float32)
        b12_meta = src.meta.copy()
    if b12_meta['dtype'] in ('uint16', 'int16'):
        b12_raw /= 10000.0
    b12 = resample_to_match(b12_raw, b12_meta, b08_meta).astype(np.float32)

    with rasterio.open(str(bands["SCL"])) as src:
        scl_raw = src.read(1)
        scl_meta = src.meta.copy()
    scl_10m = resample_to_match(scl_raw, scl_meta, b08_meta)
    invalid = np.zeros(scl_10m.shape, dtype=bool)
    for c in [0, 1, 3, 8, 9, 10, 11]:
        invalid |= (scl_10m == c)

    return b04, b08, b12, ~invalid


def safe_index(a, b, mask):
    result = np.full(a.shape, np.nan, dtype=np.float32)
    denom = a + b
    ok = mask & (denom != 0)
    result[ok] = (a[ok] - b[ok]) / denom[ok]
    return result


def run_prediction(pre_safe, output_path):
    import joblib

    t_start = time.time()

    # Load model
    model_path = Path(__file__).parent.parent / "models" / "vegetation_recovery_model.joblib"
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found at {model_path}. Run finetune_vegetation_recovery.py first.")
    model = joblib.load(model_path)

    # Load pre-fire bands only
    b04, b08, b12, mask = load_bands(pre_safe)
    ndvi = safe_index(b08, b04, mask)
    nbr = safe_index(b08, b12, mask)

    valid = ~np.isnan(ndvi) & ~np.isnan(nbr)
    valid_idx = np.where(valid.ravel())[0]
    total_valid = len(valid_idx)

    # Sample
    n = min(SAMPLE_SIZE, total_valid)
    sampled = np.random.choice(valid_idx, size=n, replace=False)

    X = np.column_stack([
        b04.ravel()[sampled],
        b08.ravel()[sampled],
        b12.ravel()[sampled],
        ndvi.ravel()[sampled],
        nbr.ravel()[sampled],
    ])

    finite = np.all(np.isfinite(X), axis=1)
    X = X[finite]

    # Predict
    predictions = model.predict(X)
    t_elapsed = time.time() - t_start

    # Categorize
    no_damage = float(np.mean(predictions <= 0.02))
    mild = float(np.mean((predictions > 0.02) & (predictions <= 0.05)))
    moderate = float(np.mean((predictions > 0.05) & (predictions <= 0.10)))
    severe = float(np.mean(predictions > 0.10))

    mean_damage = float(np.mean(predictions))
    if mean_damage > 0.10:
        overall = "Severe"
    elif mean_damage > 0.05:
        overall = "Moderate"
    elif mean_damage > 0.02:
        overall = "Mild"
    else:
        overall = "Minimal"

    result = {
        "prediction_type": "vegetation_damage_forecast",
        "model": "GradientBoostingRegressor (fine-tuned)",
        "input": "Pre-fire image only (no post-fire required)",
        "source": {
            "product": Path(pre_safe).name,
            "bands_used": ["B04 (Red)", "B08 (NIR)", "B12 (SWIR)"],
            "indices_computed": ["NDVI", "NBR"],
        },
        "prediction": {
            "mean_delta_ndvi": round(mean_damage, 6),
            "overall_damage_level": overall,
            "interpretation": f"Predicted average NDVI loss of {abs(mean_damage):.4f} — classified as {overall} damage",
        },
        "damage_distribution": {
            "no_damage": {"label": "No Damage (dNDVI <= 0.02)", "fraction": round(no_damage, 4), "pct": round(no_damage * 100, 1)},
            "mild": {"label": "Mild (0.02 < dNDVI <= 0.05)", "fraction": round(mild, 4), "pct": round(mild * 100, 1)},
            "moderate": {"label": "Moderate (0.05 < dNDVI <= 0.10)", "fraction": round(moderate, 4), "pct": round(moderate * 100, 1)},
            "severe": {"label": "Severe (dNDVI > 0.10)", "fraction": round(severe, 4), "pct": round(severe * 100, 1)},
        },
        "statistics": {
            "pixels_analyzed": len(X),
            "total_valid_pixels": total_valid,
            "predicted_mean": round(float(np.mean(predictions)), 6),
            "predicted_median": round(float(np.median(predictions)), 6),
            "predicted_std": round(float(np.std(predictions)), 6),
            "predicted_min": round(float(np.min(predictions)), 6),
            "predicted_max": round(float(np.max(predictions)), 6),
        },
        "processing_time_seconds": round(t_elapsed, 2),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def main():
    p = argparse.ArgumentParser(description="Predict vegetation damage (pre-fire only)")
    p.add_argument("--pre", required=True, help="Pre-fire .SAFE directory")
    p.add_argument("--output", default="outputs/damage_prediction.json")
    args = p.parse_args()
    result = run_prediction(args.pre, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
