"""
finetune_severity_classifier.py
================================
Fine-tunes a Random Forest classifier on Sentinel-2 spectral bands
to predict burn severity — validating the traditional dNBR approach
with a machine learning model.

FEATURES (per pixel):
  - B04 (Red reflectance)
  - B08 (NIR reflectance)
  - B12 (SWIR reflectance)
  - NDVI = (B08 - B04) / (B08 + B04)
  - NBR_pre = (B08_pre - B12_pre) / (B08_pre + B12_pre)
  - NBR_post = (B08_post - B12_post) / (B08_post + B12_post)
  - dNBR = NBR_pre - NBR_post

LABELS: dNBR severity class (USGS Key et al. 2006)
  0 = Unburned, 1 = Low, 2 = Moderate, 3 = Severe

OUTPUTS:
  - Trained model: outputs/severity_rf_model.joblib
  - Results JSON:  outputs/finetune_results.json
  - Console:       Accuracy, confusion matrix, feature importance

Usage:
  python src/finetune_severity_classifier.py \
    --pre  "C:/dss/S2A_.../S2A_..." \
    --post "C:/dss/S2B_.../S2B_..."
"""

import sys, json, argparse, time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Config ────────────────────────────────────────────────────────────────────
SAMPLE_PER_CLASS = 50_000   # pixels to sample per severity class
SEVERITY_THRESHOLDS = {     # dNBR → class label
    "unburned":  (  -0.1, 0.1,  0),
    "low":       (   0.1, 0.27, 1),
    "moderate":  (  0.27, 0.66, 2),
    "severe":    (  0.66, 9.9,  3),
}
FEATURE_NAMES = ["B04_pre", "B08_pre", "B12_pre", "B04_post", "B08_post", "B12_post", "NDVI_pre", "NBR_pre", "NBR_post", "dNBR"]


def load_bands(safe_dir, b08_meta_ref=None):
    """Load B04, B08, B12 from a .SAFE directory. Returns arrays + meta."""
    import rasterio
    from src.preprocess import find_safe_bands, read_band_as_float32, resample_to_match

    bands = find_safe_bands(safe_dir)
    b04, b04_meta = read_band_as_float32(bands["B04"])
    b08, b08_meta = read_band_as_float32(bands["B08"])

    # B12 is 20m, resample to 10m
    safe_path = Path(safe_dir)
    patterns = ["*_B12_20m.tif", "*_B12_20m.jp2", "*_B12.tif", "*_B12.jp2"]
    b12_file = None
    for pat in patterns:
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

    # Cloud mask from SCL
    scl_path = str(bands["SCL"])
    with rasterio.open(scl_path) as src:
        scl_raw = src.read(1)
        scl_meta = src.meta.copy()
    scl_10m = resample_to_match(scl_raw, scl_meta, b08_meta)
    cloud_classes = [0, 1, 3, 8, 9, 10, 11]
    invalid = np.zeros(scl_10m.shape, dtype=bool)
    for c in cloud_classes:
        invalid |= (scl_10m == c)
    mask = ~invalid

    return b04, b08, b12, mask, b08_meta


def compute_index(a, b, mask):
    """Compute (a-b)/(a+b) with masking."""
    result = np.full(a.shape, np.nan, dtype=np.float32)
    denom = a + b
    ok = mask & (denom != 0)
    result[ok] = (a[ok] - b[ok]) / denom[ok]
    return result


def run_finetune(pre_safe, post_safe):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    import joblib

    t_start = time.time()
    print("=" * 60)
    print("BURN SEVERITY — RANDOM FOREST FINE-TUNING")
    print("=" * 60)

    # ── Load bands ────────────────────────────────────────────────────────
    print("\n[1/5] Loading pre-fire bands...")
    b04_pre, b08_pre, b12_pre, mask_pre, meta_pre = load_bands(pre_safe)
    print(f"      Shape: {b08_pre.shape}, Valid: {mask_pre.sum():,} px")

    print("[2/5] Loading post-fire bands...")
    b04_post, b08_post, b12_post, mask_post, meta_post = load_bands(post_safe)
    print(f"      Shape: {b08_post.shape}, Valid: {mask_post.sum():,} px")

    # ── Compute indices ───────────────────────────────────────────────────
    print("[3/5] Computing spectral indices...")
    ndvi_pre = compute_index(b08_pre, b04_pre, mask_pre)
    nbr_pre  = compute_index(b08_pre, b12_pre, mask_pre)
    nbr_post = compute_index(b08_post, b12_post, mask_post)

    joint_valid = ~np.isnan(nbr_pre) & ~np.isnan(nbr_post)
    dnbr = np.full(nbr_pre.shape, np.nan, dtype=np.float32)
    dnbr[joint_valid] = nbr_pre[joint_valid] - nbr_post[joint_valid]

    total_valid = int(joint_valid.sum())
    print(f"      Joint valid pixels: {total_valid:,}")

    # ── Build feature matrix + labels (memory-efficient) ────────────────
    print("[4/5] Sampling pixels & building feature matrix...")

    # Get valid pixel indices
    valid_idx = np.where(joint_valid.ravel())[0]
    dnbr_valid = dnbr.ravel()[valid_idx]

    # Assign labels based on dNBR thresholds
    labels = np.full(len(valid_idx), -1, dtype=np.int32)
    for name, (lo, hi, cls) in SEVERITY_THRESHOLDS.items():
        mask_cls = (dnbr_valid >= lo) & (dnbr_valid < hi)
        labels[mask_cls] = cls

    # Drop regrowth pixels (dNBR < -0.1)
    keep = labels >= 0
    valid_idx = valid_idx[keep]
    labels = labels[keep]

    # Balanced sampling — sample indices FIRST to save memory
    sampled_idx = []
    sampled_labels = []
    class_names = ["Unburned", "Low", "Moderate", "Severe"]

    print(f"\n      {'Class':<12s}  {'Total Pixels':>14s}  {'Sampled':>10s}")
    print(f"      {'─'*12}  {'─'*14}  {'─'*10}")

    for cls_id in range(4):
        cls_mask = labels == cls_id
        cls_count = int(cls_mask.sum())
        n_sample = min(SAMPLE_PER_CLASS, cls_count)
        if n_sample == 0:
            print(f"      {class_names[cls_id]:<12s}  {cls_count:>14,}  {'SKIP':>10s}")
            continue
        idx = np.random.choice(np.where(cls_mask)[0], size=n_sample, replace=False)
        sampled_idx.append(valid_idx[idx])
        sampled_labels.append(np.full(n_sample, cls_id))
        print(f"      {class_names[cls_id]:<12s}  {cls_count:>14,}  {n_sample:>10,}")

    all_sampled_idx = np.concatenate(sampled_idx)
    y = np.concatenate(sampled_labels)

    # Extract features only for sampled pixels (memory-efficient)
    X = np.column_stack([
        b04_pre.ravel()[all_sampled_idx],
        b08_pre.ravel()[all_sampled_idx],
        b12_pre.ravel()[all_sampled_idx],
        b04_post.ravel()[all_sampled_idx],
        b08_post.ravel()[all_sampled_idx],
        b12_post.ravel()[all_sampled_idx],
        ndvi_pre.ravel()[all_sampled_idx],
        nbr_pre.ravel()[all_sampled_idx],
        nbr_post.ravel()[all_sampled_idx],
        dnbr.ravel()[all_sampled_idx],
    ])

    # Remove any NaN/Inf
    finite_mask = np.all(np.isfinite(X), axis=1)
    X = X[finite_mask]
    y = y[finite_mask]

    print(f"\n      Total training samples: {len(X):,}")

    # ── Train Random Forest ───────────────────────────────────────────────
    print("[5/5] Training Random Forest classifier...")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    rf = RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        min_samples_leaf=10,
        n_jobs=-1,
        random_state=42,
        class_weight="balanced",
    )
    rf.fit(X_train, y_train)

    y_pred = rf.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)
    report = classification_report(y_test, y_pred, target_names=class_names, output_dict=True)

    t_elapsed = time.time() - t_start

    # ── Print results ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Accuracy:       {accuracy*100:.2f}%")
    print(f"  Training time:  {t_elapsed:.1f}s")
    print(f"\n  Confusion Matrix:")
    print(f"  {'':12s}  {'Unburned':>10s}  {'Low':>10s}  {'Moderate':>10s}  {'Severe':>10s}")
    for i, row in enumerate(cm):
        print(f"  {class_names[i]:<12s}  {row[0]:>10,}  {row[1]:>10,}  {row[2]:>10,}  {row[3]:>10,}")

    print(f"\n  Feature Importance:")
    importances = rf.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    for rank, idx in enumerate(sorted_idx):
        bar = "█" * int(importances[idx] * 40)
        print(f"  {rank+1}. {FEATURE_NAMES[idx]:<12s}  {importances[idx]:.4f}  {bar}")

    # ── Save outputs ──────────────────────────────────────────────────────
    Path("outputs").mkdir(exist_ok=True)
    Path("models").mkdir(exist_ok=True)

    model_path = "models/severity_rf_model.joblib"
    joblib.dump(rf, model_path)
    print(f"\n  Model saved: {model_path}")

    results = {
        "model": "RandomForestClassifier",
        "n_estimators": 100,
        "max_depth": 12,
        "accuracy": round(accuracy, 6),
        "training_samples": len(X),
        "test_samples": len(X_test),
        "training_time_seconds": round(t_elapsed, 2),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feature_importance": {
            FEATURE_NAMES[i]: round(float(importances[i]), 6) for i in sorted_idx
        },
        "classification_report": {
            k: v for k, v in report.items()
            if k in class_names + ["accuracy", "macro avg", "weighted avg"]
        },
        "confusion_matrix": {
            class_names[i]: {class_names[j]: int(cm[i][j]) for j in range(len(cm[i]))}
            for i in range(len(cm))
        },
        "source": {
            "pre_fire": Path(pre_safe).name,
            "post_fire": Path(post_safe).name,
        },
    }

    results_path = "outputs/finetune_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved: {results_path}")
    print(f"{'='*60}")

    return results


def main():
    p = argparse.ArgumentParser(description="Fine-tune burn severity classifier")
    p.add_argument("--pre",  required=True, help="Pre-fire .SAFE directory")
    p.add_argument("--post", required=True, help="Post-fire .SAFE directory")
    args = p.parse_args()
    run_finetune(args.pre, args.post)


if __name__ == "__main__":
    main()
