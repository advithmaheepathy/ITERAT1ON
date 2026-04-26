"""
finetune_vegetation_recovery.py
================================
Trains a regression model to predict post-fire vegetation damage
(NDVI drop) from pre-fire spectral features alone.

USE CASE:
  Given ONLY the pre-fire satellite image, predict how much vegetation
  damage will occur. This enables early damage estimation BEFORE
  a post-fire image is even captured — critical for:
    - Insurance rapid-response claims
    - Emergency resource allocation
    - Disaster severity forecasting

FEATURES (pre-fire only):
  - B04_pre (Red reflectance)
  - B08_pre (NIR reflectance)
  - B12_pre (SWIR reflectance)
  - NDVI_pre = (B08 - B04) / (B08 + B04)
  - NBR_pre  = (B08 - B12) / (B08 + B12)

TARGET:
  - delta_NDVI = NDVI_pre - NDVI_post  (positive = vegetation loss)

OUTPUTS:
  - Trained model: models/vegetation_recovery_model.joblib
  - Results JSON:  outputs/vegetation_recovery_results.json

Usage:
  python src/finetune_vegetation_recovery.py \
    --pre  "C:/dss/S2A_.../S2A_..." \
    --post "C:/dss/S2B_.../S2B_..."
"""

import sys, json, argparse, time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE_SIZE = 200_000  # total pixels to sample
FEATURE_NAMES = ["B04_pre", "B08_pre", "B12_pre", "NDVI_pre", "NBR_pre"]


def load_bands(safe_dir):
    """Load B04, B08, B12 + cloud mask from a .SAFE directory."""
    import rasterio
    from src.preprocess import find_safe_bands, read_band_as_float32, resample_to_match

    bands = find_safe_bands(safe_dir)
    b04, _ = read_band_as_float32(bands["B04"])
    b08, b08_meta = read_band_as_float32(bands["B08"])

    # B12 (20m → 10m)
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

    # Cloud mask
    with rasterio.open(str(bands["SCL"])) as src:
        scl_raw = src.read(1)
        scl_meta = src.meta.copy()
    scl_10m = resample_to_match(scl_raw, scl_meta, b08_meta)
    invalid = np.zeros(scl_10m.shape, dtype=bool)
    for c in [0, 1, 3, 8, 9, 10, 11]:
        invalid |= (scl_10m == c)

    return b04, b08, b12, ~invalid, b08_meta


def safe_index(a, b, mask):
    """Compute (a-b)/(a+b), NaN where invalid."""
    result = np.full(a.shape, np.nan, dtype=np.float32)
    denom = a + b
    ok = mask & (denom != 0)
    result[ok] = (a[ok] - b[ok]) / denom[ok]
    return result


def run_finetune(pre_safe, post_safe):
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    import joblib

    t_start = time.time()
    print("=" * 60)
    print("VEGETATION RECOVERY PREDICTOR — FINE-TUNING")
    print("=" * 60)
    print("  Goal: Predict NDVI damage from pre-fire features alone")
    print()

    # ── Load bands ────────────────────────────────────────────────────────
    print("[1/5] Loading pre-fire bands...")
    b04_pre, b08_pre, b12_pre, mask_pre, _ = load_bands(pre_safe)
    print(f"      Shape: {b08_pre.shape}, Valid: {mask_pre.sum():,} px")

    print("[2/5] Loading post-fire bands...")
    b04_post, b08_post, b12_post, mask_post, _ = load_bands(post_safe)
    print(f"      Shape: {b08_post.shape}, Valid: {mask_post.sum():,} px")

    # ── Compute indices ───────────────────────────────────────────────────
    print("[3/5] Computing spectral indices...")
    ndvi_pre  = safe_index(b08_pre, b04_pre, mask_pre)
    ndvi_post = safe_index(b08_post, b04_post, mask_post)
    nbr_pre   = safe_index(b08_pre, b12_pre, mask_pre)

    joint_valid = ~np.isnan(ndvi_pre) & ~np.isnan(ndvi_post)
    delta_ndvi = np.full(ndvi_pre.shape, np.nan, dtype=np.float32)
    delta_ndvi[joint_valid] = ndvi_pre[joint_valid] - ndvi_post[joint_valid]

    total_valid = int(joint_valid.sum())
    print(f"      Joint valid pixels: {total_valid:,}")

    dndvi_vals = delta_ndvi[joint_valid]
    print(f"      Delta NDVI: mean={dndvi_vals.mean():.4f}, "
          f"std={dndvi_vals.std():.4f}, "
          f"range=[{dndvi_vals.min():.4f}, {dndvi_vals.max():.4f}]")

    # ── Sample & build features ───────────────────────────────────────────
    print("[4/5] Sampling pixels & building features...")

    valid_idx = np.where(joint_valid.ravel())[0]
    n_sample = min(SAMPLE_SIZE, len(valid_idx))
    sampled_idx = np.random.choice(valid_idx, size=n_sample, replace=False)

    # Features: PRE-FIRE ONLY (this is the key innovation)
    X = np.column_stack([
        b04_pre.ravel()[sampled_idx],
        b08_pre.ravel()[sampled_idx],
        b12_pre.ravel()[sampled_idx],
        ndvi_pre.ravel()[sampled_idx],
        nbr_pre.ravel()[sampled_idx],
    ])

    # Target: vegetation change
    y = delta_ndvi.ravel()[sampled_idx]

    # Clean
    finite = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
    X, y = X[finite], y[finite]
    print(f"      Samples: {len(X):,}")

    # ── Train model ───────────────────────────────────────────────────────
    print("[5/5] Training Gradient Boosting regressor...")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        min_samples_leaf=20,
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    t_elapsed = time.time() - t_start

    # ── Categorize predictions ────────────────────────────────────────────
    # How well does the model predict damage categories?
    def categorize(vals):
        cats = np.zeros(len(vals), dtype=int)
        cats[vals > 0.02] = 1   # mild damage
        cats[vals > 0.05] = 2   # moderate damage
        cats[vals > 0.10] = 3   # severe damage
        return cats

    cat_true = categorize(y_test)
    cat_pred = categorize(y_pred)
    cat_accuracy = np.mean(cat_true == cat_pred)

    # ── Print results ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  R² Score:           {r2:.4f}")
    print(f"  MAE:                {mae:.6f}")
    print(f"  RMSE:               {rmse:.6f}")
    print(f"  Category Accuracy:  {cat_accuracy*100:.1f}%")
    print(f"  Training time:      {t_elapsed:.1f}s")

    print(f"\n  Damage Category Breakdown (test set):")
    cat_names = ["No Damage", "Mild", "Moderate", "Severe"]
    for i, name in enumerate(cat_names):
        n_true = int((cat_true == i).sum())
        n_pred = int((cat_pred == i).sum())
        print(f"    {name:<12s}  True: {n_true:>8,}  Predicted: {n_pred:>8,}")

    print(f"\n  Feature Importance (pre-fire features only):")
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    for rank, idx in enumerate(sorted_idx):
        bar = "█" * int(importances[idx] * 40)
        print(f"    {rank+1}. {FEATURE_NAMES[idx]:<12s}  {importances[idx]:.4f}  {bar}")

    # ── Prediction examples ───────────────────────────────────────────────
    print(f"\n  Sample Predictions (actual vs predicted delta_NDVI):")
    print(f"    {'Actual':>10s}  {'Predicted':>10s}  {'Error':>10s}  Interpretation")
    print(f"    {'─'*10}  {'─'*10}  {'─'*10}  {'─'*25}")
    sample_indices = np.random.choice(len(y_test), size=8, replace=False)
    for si in sample_indices:
        actual = y_test[si]
        pred = y_pred[si]
        err = abs(actual - pred)
        if actual > 0.10:
            interp = "Severe vegetation loss"
        elif actual > 0.05:
            interp = "Moderate damage"
        elif actual > 0.02:
            interp = "Mild stress"
        elif actual > -0.02:
            interp = "No significant change"
        else:
            interp = "Vegetation recovery"
        print(f"    {actual:>10.4f}  {pred:>10.4f}  {err:>10.4f}  {interp}")

    # ── Save ──────────────────────────────────────────────────────────────
    Path("outputs").mkdir(exist_ok=True)
    Path("models").mkdir(exist_ok=True)

    model_path = "models/vegetation_recovery_model.joblib"
    joblib.dump(model, model_path)
    print(f"\n  Model saved: {model_path}")

    results = {
        "model": "GradientBoostingRegressor",
        "task": "Predict post-fire NDVI damage from pre-fire spectral features",
        "n_estimators": 200,
        "max_depth": 6,
        "r2_score": round(r2, 6),
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "category_accuracy": round(cat_accuracy, 4),
        "damage_categories": {
            "no_damage": "delta_NDVI <= 0.02",
            "mild": "0.02 < delta_NDVI <= 0.05",
            "moderate": "0.05 < delta_NDVI <= 0.10",
            "severe": "delta_NDVI > 0.10",
        },
        "training_samples": len(X),
        "test_samples": len(X_test),
        "training_time_seconds": round(t_elapsed, 2),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feature_importance": {
            FEATURE_NAMES[i]: round(float(importances[i]), 6) for i in sorted_idx
        },
        "source": {
            "pre_fire": Path(pre_safe).name,
            "post_fire": Path(post_safe).name,
        },
        "interpretation": (
            "This model predicts vegetation damage using ONLY pre-fire spectral "
            "features. A positive delta_NDVI means vegetation loss. The model "
            "enables early damage forecasting before post-fire imagery is available."
        ),
    }

    results_path = "outputs/vegetation_recovery_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved: {results_path}")
    print(f"{'='*60}")

    return results


def main():
    p = argparse.ArgumentParser(description="Vegetation Recovery Predictor")
    p.add_argument("--pre",  required=True, help="Pre-fire .SAFE directory")
    p.add_argument("--post", required=True, help="Post-fire .SAFE directory")
    args = p.parse_args()
    run_finetune(args.pre, args.post)


if __name__ == "__main__":
    main()
