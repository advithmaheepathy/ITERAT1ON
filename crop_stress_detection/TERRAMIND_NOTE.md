# TerraMind Integration Note

## Is TerraMind needed here?

**Short answer: Not for basic NDVI crop stress detection.**

If you have complete, cloud-free Sentinel-2 imagery, computing NDVI from B4/B8 is self-contained.
TerraMind adds value ONLY in specific scenarios described below.

---

## When TerraMind IS Valid to Use

### Use Case 1: Cloud Gap Filling
Sentinel-2 optical bands are unusable under cloud cover. If your AOI has >20% cloud
coverage on the acquisition date, you have missing NDVI pixels.

TerraMind (IBM Prithvi/Geospatial Foundation Model family) can:
- Take multi-temporal context (previous clear-sky acquisitions)
- Reconstruct missing pixels via learned spatial-temporal representations
- Output: estimated surface reflectance for B4/B8 → usable NDVI

### Use Case 2: Temporal Interpolation
If you have data from Day 1 and Day 30 but need Day 15 (e.g., weekly monitoring),
TerraMind can interpolate between known states.

---

## How to Integrate It (if you have access)

```python
# TerraMind requires IBM Prithvi weights from Hugging Face:
# https://huggingface.co/ibm-nasa-geospatial/Prithvi-100M

# Install:
# pip install transformers timm einops

from transformers import AutoModel
import torch
import numpy as np

def fill_cloud_gaps_with_terramind(
    cloudy_patch: np.ndarray,   # shape: (T, C, H, W) - T=time, C=6 HLS bands
    cloud_mask: np.ndarray,      # shape: (H, W), 1=cloud, 0=clear
    model_path: str = "ibm-nasa-geospatial/Prithvi-100M"
) -> np.ndarray:
    """
    Use Prithvi (TerraMind foundation) to reconstruct clouded pixels.
    
    Input tensor format:
      - Uses HLS (Harmonized Landsat-Sentinel) 6-band format:
        [Blue, Green, Red, NIR_Narrow, SWIR1, SWIR2]
      - Sentinel-2 bands map: B2→Blue, B3→Green, B4→Red, B8A→NIR, B11→SWIR1, B12→SWIR2
      - Time dimension: at least 3 clear-sky acquisitions as context
      - Spatial: 224x224 pixel patches (native resolution)
    
    Output:
      - Reconstructed patch: (C, H, W) float32 surface reflectance [0,1]
      - Extract B4 (index 2) and NIR (index 3) for NDVI
    """
    # NOTE: This code requires actual model weights download (~400MB)
    # and Hugging Face access. Not runnable without those.
    
    model = AutoModel.from_pretrained(model_path, trust_remote_code=True)
    model.eval()
    
    # Normalize to [0,1] range expected by Prithvi
    cloudy_patch_norm = cloudy_patch.astype(np.float32) / 10000.0
    
    # Mask clouded pixels to 0 (model learns from context)
    cloudy_patch_norm[:, :, cloud_mask == 1] = 0.0
    
    tensor = torch.from_numpy(cloudy_patch_norm).unsqueeze(0)  # (1, T, C, H, W)
    
    with torch.no_grad():
        reconstructed = model(tensor)  # (1, C, H, W)
    
    return reconstructed.squeeze(0).numpy()
```

## Why It's NOT Included in the Default Pipeline

1. Requires Hugging Face account + model download (~400MB)
2. Requires HLS band format, not raw Sentinel-2 DN values
3. Adds significant complexity for marginal gain on clear-sky imagery
4. The pipeline is CORRECT without it for cloud-free acquisitions

## Decision Logic Built into Pipeline

```python
# In run_pipeline.py:
if cloud_coverage_pct > CONFIG["terramind_threshold"]:  # default: 0.20
    logger.warning(
        f"Cloud coverage {cloud_coverage_pct:.1%} exceeds threshold. "
        f"NDVI results for {tile_id} may be incomplete. "
        f"Consider TerraMind gap-filling — see TERRAMIND_NOTE.md"
    )
    tile_result["terramind_recommended"] = True
    tile_result["valid_pixel_fraction"] = 1.0 - cloud_coverage_pct
```