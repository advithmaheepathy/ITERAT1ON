"""
ndvi_v2.py
==========
Scientifically correct, minimally biased NDVI computation.

KEY CHANGES from ndvi_improved.py:
1. Valid range is [-1, 1] — physically correct, NOT [-0.2, 1.0]
2. NO global vegetation filter (NDVI > 0.2) — was discarding bare soil
   and stressed pixels before classification even started
3. Gaussian smoothing is configurable (default: OFF to preserve data)
4. Statistics reported on ALL valid pixels — not a filtered subset
5. Consistent pixel counts: total → cloud-masked → ndvi-valid (zero-denom)

Author: Senior Remote Sensing Engineer
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import rasterio

logger = logging.getLogger(__name__)


def compute_ndvi(
    b04: np.ndarray,
    b08: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
    ndvi_min: float = -1.0,
    ndvi_max: float = 1.0,
    apply_smoothing: bool = False,
    smoothing_sigma: float = 1.0,
) -> Tuple[np.ndarray, dict]:
    """
    Compute NDVI with minimal bias.

    Args:
        b04          : Red band, float32 (H, W), surface reflectance [0, 1]
        b08          : NIR band, float32 (H, W), surface reflectance [0, 1]
        valid_mask   : bool (H, W) — True = valid pixel (cloud/water already masked)
        ndvi_min     : physical lower bound  (default -1.0)
        ndvi_max     : physical upper bound  (default  1.0)
        apply_smoothing : Gaussian spatial smoothing (default False)
        smoothing_sigma : sigma for gaussian filter (only if apply_smoothing=True)

    Returns:
        ndvi     : float32 (H, W), NaN where invalid
        metadata : dict with pixel counts and NDVI statistics

    WHAT IS MASKED / SET TO NaN:
        1. Pixels where cloud/water mask says invalid (if valid_mask provided)
        2. Pixels where B04+B08 == 0 (zero denominator → undefined NDVI)
        3. Pixels outside physical range [-1, 1] (sensor artefacts)
    """

    if b04.shape != b08.shape:
        raise ValueError(f"Band shape mismatch: B04={b04.shape} vs B08={b08.shape}")

    b04 = b04.astype(np.float32)
    b08 = b08.astype(np.float32)
    total_pixels = b04.size

    logger.info("=" * 60)
    logger.info("NDVI COMPUTATION  (v2 — unbiased)")
    logger.info("=" * 60)
    logger.info(f"  Total pixels  : {total_pixels:,}")

    # ── Step 1: cloud / water mask ──────────────────────────────────────────
    ndvi = np.full(b04.shape, np.nan, dtype=np.float32)

    if valid_mask is not None:
        if valid_mask.shape != b04.shape:
            raise ValueError(
                f"valid_mask shape {valid_mask.shape} != band shape {b04.shape}"
            )
        masked_out = int((~valid_mask).sum())
        logger.info(f"  Cloud/water masked : {masked_out:,}  ({masked_out/total_pixels*100:.2f}%)")
        work_pixels = valid_mask
    else:
        work_pixels = np.ones(b04.shape, dtype=bool)
        logger.info("  No valid_mask provided — using all pixels")

    # ── Step 2: safe division (zero denominator) ────────────────────────────
    denom = b08 + b04
    zero_denom = (denom == 0) & work_pixels
    zero_count = int(zero_denom.sum())
    if zero_count:
        logger.info(f"  Zero-denominator   : {zero_count:,} ({zero_count/total_pixels*100:.4f}%) → NaN")

    compute_mask = work_pixels & (~zero_denom)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi[compute_mask] = (b08[compute_mask] - b04[compute_mask]) / denom[compute_mask]

    # ── Step 3: physical range filter [-1, 1] ──────────────────────────────
    out_of_range = (~np.isnan(ndvi)) & ((ndvi < ndvi_min) | (ndvi > ndvi_max))
    oor_count = int(out_of_range.sum())
    if oor_count:
        ndvi[out_of_range] = np.nan
        logger.info(
            f"  Out-of-range [{ndvi_min},{ndvi_max}] : {oor_count:,} "
            f"({oor_count/total_pixels*100:.4f}%) → NaN"
        )
    else:
        logger.info(f"  Out-of-range [{ndvi_min},{ndvi_max}] : 0")

    # ── Step 4: optional Gaussian smoothing ────────────────────────────────
    if apply_smoothing:
        from scipy.ndimage import gaussian_filter
        valid_before = ~np.isnan(ndvi)
        if valid_before.sum() > 100:
            tmp = ndvi.copy()
            tmp[~valid_before] = 0.0
            tmp = gaussian_filter(tmp, sigma=smoothing_sigma).astype(np.float32)
            tmp[~valid_before] = np.nan
            ndvi = tmp
            logger.info(f"  Gaussian smoothing : sigma={smoothing_sigma}")
        else:
            logger.warning("  Smoothing skipped — too few valid pixels")

    # ── Step 5: statistics ──────────────────────────────────────────────────
    valid_vals = ndvi[~np.isnan(ndvi)]
    valid_count = int(valid_vals.size)
    valid_pct = valid_count / total_pixels * 100

    logger.info("─" * 60)
    logger.info(f"  Valid NDVI pixels  : {valid_count:,}  ({valid_pct:.2f}%)")

    if valid_count == 0:
        logger.error("  ⚠  ALL pixels are NaN — check masking!")
        return ndvi, {
            "error": "no_valid_pixels",
            "total_pixels": total_pixels,
            "valid_pixels": 0,
            "valid_pixel_pct": 0.0,
        }

    pcts = np.percentile(valid_vals, [5, 10, 25, 50, 75, 90, 95]).tolist()
    logger.info(f"  NDVI mean  : {valid_vals.mean():.4f}")
    logger.info(f"  NDVI median: {np.median(valid_vals):.4f}")
    logger.info(f"  NDVI std   : {valid_vals.std():.4f}")
    logger.info(f"  NDVI range : [{valid_vals.min():.4f}, {valid_vals.max():.4f}]")
    logger.info(
        f"  Percentiles: "
        f"p5={pcts[0]:.3f}  p25={pcts[2]:.3f}  p50={pcts[3]:.3f}  "
        f"p75={pcts[4]:.3f}  p95={pcts[6]:.3f}"
    )
    logger.info("=" * 60)

    metadata = {
        "total_pixels": total_pixels,
        "valid_pixels": valid_count,
        "valid_pixel_pct": round(valid_pct, 4),
        "shape": list(ndvi.shape),
        "ndvi_stats": {
            "mean":   round(float(valid_vals.mean()), 6),
            "median": round(float(np.median(valid_vals)), 6),
            "std":    round(float(valid_vals.std()), 6),
            "min":    round(float(valid_vals.min()), 6),
            "max":    round(float(valid_vals.max()), 6),
            "p5":     round(pcts[0], 6),
            "p10":    round(pcts[1], 6),
            "p25":    round(pcts[2], 6),
            "p75":    round(pcts[4], 6),
            "p90":    round(pcts[5], 6),
            "p95":    round(pcts[6], 6),
        },
        "config": {
            "valid_range": [ndvi_min, ndvi_max],
            "smoothing_applied": apply_smoothing,
            "smoothing_sigma": smoothing_sigma if apply_smoothing else None,
        },
    }
    return ndvi, metadata


def compute_ndvi_from_safe_bands(
    b04_path: str,
    b08_path: str,
    valid_mask_path: Optional[str] = None,
    output_path: Optional[str] = None,
    ndvi_min: float = -1.0,
    ndvi_max: float = 1.0,
    apply_smoothing: bool = False,
    smoothing_sigma: float = 1.0,
) -> Tuple[np.ndarray, dict]:
    """
    Load B04, B08, and optional valid_mask from GeoTIFFs, compute NDVI,
    optionally write result to disk.

    Returns:
        ndvi_array : float32 ndarray
        metadata   : dict (consistent with output_writer expectations)
    """
    logger.info(f"  Loading B04 : {b04_path}")
    with rasterio.open(b04_path) as src:
        b04 = src.read(1).astype(np.float32)
        raster_meta = src.meta.copy()
        transform = src.transform
        crs = src.crs

    logger.info(f"  Loading B08 : {b08_path}")
    with rasterio.open(b08_path) as src:
        b08 = src.read(1).astype(np.float32)

    valid_mask = None
    if valid_mask_path is not None:
        logger.info(f"  Loading mask: {valid_mask_path}")
        with rasterio.open(valid_mask_path) as src:
            valid_mask = src.read(1).astype(bool)

    ndvi, meta = compute_ndvi(
        b04, b08, valid_mask,
        ndvi_min=ndvi_min,
        ndvi_max=ndvi_max,
        apply_smoothing=apply_smoothing,
        smoothing_sigma=smoothing_sigma,
    )

    meta.update({
        "b04_source": b04_path,
        "b08_source": b08_path,
        "valid_mask_source": valid_mask_path,
        "crs": str(crs),
        "transform": list(transform),
    })

    if output_path is not None:
        _write_ndvi_tif(ndvi, raster_meta, output_path)
        meta["ndvi_raster_path"] = output_path

    return ndvi, meta


def _write_ndvi_tif(ndvi: np.ndarray, base_meta: dict, output_path: str):
    """Write NDVI float32 GeoTIFF.  NaN → nodata=-9999."""
    out_meta = base_meta.copy()
    out_meta.update({
        "dtype": "float32",
        "count": 1,
        "nodata": -9999.0,
        "compress": "lzw",
        "driver": "GTiff",
    })
    ndvi_out = np.where(np.isnan(ndvi), -9999.0, ndvi).astype(np.float32)
    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(ndvi_out, 1)
    logger.info(f"  NDVI raster saved: {output_path}")
