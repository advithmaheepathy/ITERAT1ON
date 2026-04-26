#!/usr/bin/env python3
"""
infer.py — AgriSat-7 Unified Inference Entry Point
====================================================
Single command to run the full analysis pipeline:
  1. dNBR burn severity analysis (requires pre + post images)
  2. ML vegetation damage prediction (pre-fire image only)

Usage:
  # Full analysis (burn detection + ML prediction)
  python infer.py --pre <PRE_FIRE.SAFE> --post <POST_FIRE.SAFE>

  # ML prediction only (pre-fire image only)
  python infer.py --pre <PRE_FIRE.SAFE>

  # With custom output directory
  python infer.py --pre <PRE_FIRE.SAFE> --post <POST_FIRE.SAFE> --output results/

Example:
  python infer.py \
    --pre  "C:/dss/S2A_MSIL2A_20191216T004701_.../S2A_..." \
    --post "C:/dss/S2B_MSIL2A_20200130T004659_.../S2B_..."
"""

import sys, json, argparse, time, os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(
        description="AgriSat-7 — Burn Severity & Vegetation Damage Inference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--pre", required=True, help="Path to pre-fire .SAFE directory")
    parser.add_argument("--post", default=None, help="Path to post-fire .SAFE directory (optional)")
    parser.add_argument("--output", default="crop_stress_detection/outputs", help="Output directory for results")
    args = parser.parse_args()

    # Validate paths
    pre_path = Path(args.pre)
    if not pre_path.exists():
        print(f"ERROR: Pre-fire dataset not found: {pre_path}")
        sys.exit(1)

    post_path = Path(args.post) if args.post else None
    if post_path and not post_path.exists():
        print(f"ERROR: Post-fire dataset not found: {post_path}")
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ["PYTHONIOENCODING"] = "utf-8"
    src_dir = Path(__file__).parent / "crop_stress_detection"

    print("=" * 65)
    print("  AgriSat-7 — Satellite Burn Analysis & ML Inference")
    print("=" * 65)
    print(f"  Pre-fire:  {pre_path.name}")
    print(f"  Post-fire: {post_path.name if post_path else 'NOT PROVIDED (ML-only mode)'}")
    print(f"  Output:    {out_dir.resolve()}")
    print("=" * 65)

    results = {}
    t_total = time.time()

    # ── Step 1: Full dNBR Burn Analysis (if post-fire provided) ───────
    if post_path:
        print("\n[STEP 1/2] Running dNBR burn severity analysis...")
        print("           (This processes 120M+ pixels — takes ~60-90 seconds)")
        burn_output = out_dir / "burn_severity_result.json"
        sys.path.insert(0, str(src_dir))

        from src.burn_analysis_v3 import run_burn_analysis
        run_burn_analysis(str(pre_path), str(post_path), str(burn_output))

        if burn_output.exists():
            with open(burn_output, "r", encoding="utf-8") as f:
                results["burn_severity"] = json.load(f)
            print(f"\n  >> Burn analysis saved: {burn_output}")
        else:
            print("  >> WARNING: Burn analysis did not produce output")
    else:
        print("\n[STEP 1/2] Skipping burn analysis (no post-fire image provided)")

    # ── Step 2: ML Vegetation Damage Prediction ───────────────────────
    print("\n[STEP 2/2] Running ML vegetation damage prediction...")
    print("           (Uses fine-tuned model — pre-fire image only — ~30 seconds)")
    pred_output = out_dir / "damage_prediction.json"
    sys.path.insert(0, str(src_dir))

    from src.predict_damage import run_prediction
    pred_result = run_prediction(str(pre_path), str(pred_output))
    results["ml_prediction"] = pred_result
    print(f"\n  >> ML prediction saved: {pred_output}")

    # ── Summary ───────────────────────────────────────────────────────
    elapsed = time.time() - t_total
    print(f"\n{'=' * 65}")
    print(f"  INFERENCE COMPLETE — {elapsed:.1f}s total")
    print(f"{'=' * 65}")

    if "burn_severity" in results:
        bs = results["burn_severity"].get("summary", {})
        print(f"\n  BURN SEVERITY (dNBR):")
        print(f"    Burned area:     {bs.get('burned_area_ha', 'N/A')} ha")
        print(f"    Burned fraction: {(bs.get('burned_fraction', 0) * 100):.2f}%")
        sev = bs.get("severity_distribution", {})
        for level in ["unburned", "low", "moderate", "severe"]:
            if level in sev:
                s = sev[level]
                print(f"    {s.get('label', level):<20s}  {s.get('pct_of_valid', 0):>6.1f}%  ({s.get('area_ha', 0):,.0f} ha)")

    pred = results.get("ml_prediction", {}).get("prediction", {})
    dist = results.get("ml_prediction", {}).get("damage_distribution", {})
    print(f"\n  ML DAMAGE PREDICTION (pre-fire only):")
    print(f"    Predicted level: {pred.get('overall_damage_level', 'N/A')}")
    print(f"    Mean dNDVI:      {pred.get('mean_delta_ndvi', 'N/A')}")
    for cat in ["no_damage", "mild", "moderate", "severe"]:
        if cat in dist:
            d = dist[cat]
            print(f"    {d.get('label', cat):<30s}  {d.get('pct', 0):>5.1f}%")

    # Save combined results
    combined_path = out_dir / "inference_results.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Combined results: {combined_path}")
    print(f"{'=' * 65}")


if __name__ == "__main__":
    main()
