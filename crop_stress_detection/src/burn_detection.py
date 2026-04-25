"""
burn_detection.py
=================
Detect burnt crop areas using bi-temporal Sentinel-2 imagery.

Method:
    1. Compute NDVI (before) to isolate vegetated land
    2. Compute NBR (before & after) from NIR (B08) and SWIR (B12)
    3. Derive dNBR = NBR_before - NBR_after
    4. Apply burn mask: dNBR > 0.3 AND NDVI_before > 0.3
    5. Classify severity using USGS dNBR thresholds

Formulas:
    NDVI = (B08 - B04) / (B08 + B04)
    NBR  = (B08 - B12) / (B08 + B12)
    dNBR = NBR_before  - NBR_after

Severity thresholds (USGS / Key & Benson, 2006):
    dNBR < 0.1  → Unburned
    0.1–0.3     → Low severity
    0.3–0.6     → Moderate severity
    > 0.6       → Severe

References:
    Key, C.H. & Benson, N.C. (2006). "Landscape Assessment: Ground measure
    of severity, the Composite Burn Index; and Remote sensing of severity,
    the Normalized Burn Ratio." FIREMON: Fire Effects Monitoring and
    Inventory System, USDA Forest Service, RMRS-GTR-164-CD.

    García, M.J.L. & Caselles, V. (1991). "Mapping burns and natural reforestation
    using Thematic Mapper data." Geocarto International, 6(1), 31-37.
"""

import logging
from typing import Optional, Tuple, Dict

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Severity classification thresholds (USGS standard)
# ──────────────────────────────────────────────────────────────────────
SEVERITY_THRESHOLDS = {
    "unburned":  {"max": 0.1, "label": "Unburned",          "code": 0},
    "low":       {"max": 0.3, "label": "Low Severity",      "code": 1},
    "moderate":  {"max": 0.6, "label": "Moderate Severity",  "code": 2},
    "severe":    {"max": float("inf"), "label": "Severe",    "code": 3},
}

# Vegetation filter: only pixels with NDVI > this are considered
VEGETATION_NDVI_MIN = 0.3

# Burn detection: dNBR must exceed this to be flagged as burned
DNBR_BURN_THRESHOLD = 0.3

# Pixel area at 10m resolution
PIXEL_AREA_HA = 0.01  # 10m × 10m = 100 m² = 0.01 ha


# ══════════════════════════════════════════════════════════════════════
# CORE INDEX COMPUTATION
# ══════════════════════════════════════════════════════════════════════

def compute_ndvi(
    b04: np.ndarray,
    b08: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Compute per-pixel NDVI from surface reflectance arrays.

    Args:
        b04: Red band, float32, shape (H, W), range [0,1]
        b08: NIR band, float32, shape (H, W), range [0,1]
        valid_mask: bool array, True=valid pixel. If None, all assumed valid.

    Returns:
        ndvi: float32 array, shape (H, W)
              Values in [-1, 1] for valid pixels, NaN otherwise.
    """
    if b04.shape != b08.shape:
        raise ValueError(f"Shape mismatch: B04={b04.shape}, B08={b08.shape}")

    b04 = np.asarray(b04, dtype=np.float32)
    b08 = np.asarray(b08, dtype=np.float32)

    denom = b08 + b04
    zero_mask = denom == 0

    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(zero_mask, np.nan, (b08 - b04) / denom).astype(np.float32)

    if valid_mask is not None:
        ndvi[~valid_mask] = np.nan

    valid = ndvi[~np.isnan(ndvi)]
    if valid.size > 0:
        logger.info(
            f"NDVI computed: {valid.size:,} valid px | "
            f"mean={valid.mean():.4f} std={valid.std():.4f} "
            f"[{valid.min():.4f}, {valid.max():.4f}]"
        )
    else:
        logger.warning("NDVI: ALL pixels are NaN — check inputs and mask")

    return ndvi


def compute_nbr(
    b08: np.ndarray,
    b12: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Compute Normalized Burn Ratio from NIR (B08) and SWIR (B12).

    NBR = (B08 - B12) / (B08 + B12)

    Args:
        b08: NIR band, float32, shape (H, W)
        b12: SWIR band, float32, shape (H, W) — must be resampled to 10m
        valid_mask: bool array, True=valid pixel

    Returns:
        nbr: float32 array, shape (H, W), range [-1, 1], NaN for invalid
    """
    if b08.shape != b12.shape:
        raise ValueError(
            f"Shape mismatch: B08={b08.shape}, B12={b12.shape}. "
            f"B12 must be resampled to 10m to match B08."
        )

    b08 = np.asarray(b08, dtype=np.float32)
    b12 = np.asarray(b12, dtype=np.float32)

    denom = b08 + b12
    zero_mask = denom == 0

    with np.errstate(divide="ignore", invalid="ignore"):
        nbr = np.where(zero_mask, np.nan, (b08 - b12) / denom).astype(np.float32)

    if valid_mask is not None:
        nbr[~valid_mask] = np.nan

    valid = nbr[~np.isnan(nbr)]
    if valid.size > 0:
        logger.info(
            f"NBR computed: {valid.size:,} valid px | "
            f"mean={valid.mean():.4f} std={valid.std():.4f} "
            f"[{valid.min():.4f}, {valid.max():.4f}]"
        )
    else:
        logger.warning("NBR: ALL pixels are NaN — check inputs and mask")

    return nbr


def compute_dnbr(
    nbr_before: np.ndarray,
    nbr_after: np.ndarray,
) -> np.ndarray:
    """
    Compute differenced NBR (delta-NBR).

    dNBR = NBR_before - NBR_after

    Positive values indicate vegetation loss (burn).
    Negative values indicate regrowth.

    Args:
        nbr_before: NBR from pre-fire image, float32
        nbr_after:  NBR from post-fire image, float32

    Returns:
        dnbr: float32 array. NaN where either input is NaN.
    """
    if nbr_before.shape != nbr_after.shape:
        raise ValueError(
            f"Shape mismatch: before={nbr_before.shape}, after={nbr_after.shape}"
        )

    dnbr = (nbr_before - nbr_after).astype(np.float32)

    valid = dnbr[~np.isnan(dnbr)]
    if valid.size > 0:
        logger.info(
            f"dNBR computed: {valid.size:,} valid px | "
            f"mean={valid.mean():.4f} std={valid.std():.4f} "
            f"[{valid.min():.4f}, {valid.max():.4f}]"
        )
    else:
        logger.warning("dNBR: ALL pixels are NaN")

    return dnbr


# ══════════════════════════════════════════════════════════════════════
# BURN MASK & SEVERITY
# ══════════════════════════════════════════════════════════════════════

def build_burn_mask(
    dnbr: np.ndarray,
    ndvi_before: np.ndarray,
    dnbr_threshold: float = DNBR_BURN_THRESHOLD,
    ndvi_threshold: float = VEGETATION_NDVI_MIN,
) -> np.ndarray:
    """
    Generate binary burn mask.

    A pixel is classified as burned when BOTH conditions are met:
        1. dNBR > dnbr_threshold  (spectral evidence of burn)
        2. NDVI_before > ndvi_threshold  (was vegetated before — avoids
           false positives from bare soil, water, urban)

    Args:
        dnbr: delta-NBR array, float32
        ndvi_before: NDVI from pre-fire image, float32
        dnbr_threshold: dNBR cutoff for burn detection (default 0.3)
        ndvi_threshold: minimum pre-fire NDVI (default 0.3)

    Returns:
        burn_mask: bool array. True = burned pixel.
                   NaN input pixels → False (not burned).
    """
    # Treat NaN as not-burned (safe default)
    dnbr_safe = np.nan_to_num(dnbr, nan=-999.0)
    ndvi_safe = np.nan_to_num(ndvi_before, nan=-999.0)

    burn_mask = (dnbr_safe > dnbr_threshold) & (ndvi_safe > ndvi_threshold)

    burned_count = burn_mask.sum()
    total_valid = np.sum(~np.isnan(dnbr) & ~np.isnan(ndvi_before))

    logger.info(
        f"Burn mask: {burned_count:,} burned pixels "
        f"({burned_count / max(total_valid, 1) * 100:.2f}% of valid area)"
    )

    return burn_mask


def classify_burn(
    dnbr: np.ndarray,
    burn_mask: np.ndarray,
) -> np.ndarray:
    """
    Classify burn severity from dNBR values.

    Only pixels where burn_mask=True are classified.
    All other pixels are set to 255 (no-data / unburned / not vegetated).

    Severity codes (stored as uint8):
        0 = Unburned       (dNBR < 0.1)
        1 = Low severity   (0.1 ≤ dNBR < 0.3)
        2 = Moderate        (0.3 ≤ dNBR < 0.6)
        3 = Severe          (dNBR ≥ 0.6)
        255 = No data / non-burn

    Args:
        dnbr: delta-NBR array, float32
        burn_mask: bool array from build_burn_mask()

    Returns:
        severity: uint8 array with severity class codes
    """
    severity = np.full(dnbr.shape, 255, dtype=np.uint8)

    # Only classify where burn_mask is True
    dnbr_vals = np.nan_to_num(dnbr, nan=-999.0)

    severity[burn_mask & (dnbr_vals < 0.1)] = 0   # Unburned (unlikely given mask threshold, but safe)
    severity[burn_mask & (dnbr_vals >= 0.1) & (dnbr_vals < 0.3)] = 1  # Low
    severity[burn_mask & (dnbr_vals >= 0.3) & (dnbr_vals < 0.6)] = 2  # Moderate
    severity[burn_mask & (dnbr_vals >= 0.6)] = 3   # Severe

    # Log distribution
    for key, info in SEVERITY_THRESHOLDS.items():
        count = np.sum(severity == info["code"])
        if count > 0:
            logger.info(f"  Severity [{info['label']}]: {count:,} pixels")

    return severity


# ══════════════════════════════════════════════════════════════════════
# AREA CALCULATION
# ══════════════════════════════════════════════════════════════════════

def calculate_area(
    burn_mask: np.ndarray,
    severity_map: np.ndarray,
    pixel_area_ha: float = PIXEL_AREA_HA,
) -> Dict:
    """
    Calculate burned area in hectares from burn mask.

    Assumes 10m spatial resolution: 1 pixel = 10m × 10m = 100 m² = 0.01 ha.

    Args:
        burn_mask: bool array, True=burned
        severity_map: uint8 severity class array
        pixel_area_ha: area per pixel in hectares (default 0.01)

    Returns:
        dict with total burned area and per-severity breakdown
    """
    burned_pixels = int(burn_mask.sum())
    burned_area_ha = round(burned_pixels * pixel_area_ha, 2)

    severity_dist = {}
    for key, info in SEVERITY_THRESHOLDS.items():
        count = int(np.sum(severity_map == info["code"]))
        area = round(count * pixel_area_ha, 2)
        severity_dist[key] = {
            "label": info["label"],
            "pixel_count": count,
            "area_ha": area,
        }

    total_pixels = int(burn_mask.size)

    result = {
        "total_pixels": total_pixels,
        "burned_pixels": burned_pixels,
        "burned_area_ha": burned_area_ha,
        "burned_fraction": round(burned_pixels / max(total_pixels, 1), 6),
        "pixel_resolution_m": 10,
        "pixel_area_ha": pixel_area_ha,
        "severity_distribution": severity_dist,
    }

    logger.info(f"Burned area: {burned_area_ha} ha ({burned_pixels:,} pixels)")
    for key, info in severity_dist.items():
        if info["pixel_count"] > 0:
            logger.info(f"  {info['label']}: {info['area_ha']} ha")

    return result


# ══════════════════════════════════════════════════════════════════════
# VISUALIZATION
# ══════════════════════════════════════════════════════════════════════

def create_burn_visualization(
    b04: np.ndarray,
    b08: np.ndarray,
    burn_mask: np.ndarray,
    severity_map: np.ndarray,
    ndvi_before: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Create RGB visualization image highlighting burned areas.

    Color scheme:
        - Burned pixels: shaded by severity
            Severe   → bright red   (255, 50, 50)
            Moderate → orange-red   (255, 140, 50)
            Low      → yellow       (255, 220, 80)
        - Healthy vegetation (NDVI > 0.3, not burned): green tones
        - Background / bare soil: grayscale from NIR band

    Args:
        b04: Red band (post-fire), float32 [0,1]
        b08: NIR band (post-fire), float32 [0,1]
        burn_mask: bool array, True=burned
        severity_map: uint8 severity classes
        ndvi_before: pre-fire NDVI, float32
        valid_mask: optional bool mask, True=valid

    Returns:
        rgb: uint8 array, shape (H, W, 3), ready for image output
    """
    h, w = b04.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)

    # --- Background: grayscale from NIR (good land/water contrast) ---
    nir_norm = np.clip(b08, 0, 1)
    gray = (nir_norm * 200).astype(np.uint8)
    rgb[:, :, 0] = gray
    rgb[:, :, 1] = gray
    rgb[:, :, 2] = gray

    # --- Healthy vegetation overlay: green ---
    ndvi_safe = np.nan_to_num(ndvi_before, nan=0.0)
    veg_mask = (ndvi_safe > VEGETATION_NDVI_MIN) & (~burn_mask)
    if valid_mask is not None:
        veg_mask &= valid_mask

    green_intensity = np.clip((ndvi_safe - 0.3) / 0.5 * 180 + 60, 60, 240).astype(np.uint8)
    rgb[veg_mask, 0] = (green_intensity[veg_mask] * 0.15).astype(np.uint8)  # Low red
    rgb[veg_mask, 1] = green_intensity[veg_mask]                             # Strong green
    rgb[veg_mask, 2] = (green_intensity[veg_mask] * 0.1).astype(np.uint8)   # Very low blue

    # --- Burn overlay: severity-coded ---
    # Severe → bright red
    severe = burn_mask & (severity_map == 3)
    rgb[severe] = [255, 50, 50]

    # Moderate → orange-red
    moderate = burn_mask & (severity_map == 2)
    rgb[moderate] = [255, 140, 50]

    # Low → yellow
    low = burn_mask & (severity_map == 1)
    rgb[low] = [255, 220, 80]

    # --- Invalid pixels → dark ---
    if valid_mask is not None:
        rgb[~valid_mask] = [20, 20, 20]

    logger.info(f"Visualization created: {h}×{w} RGB image")

    return rgb
