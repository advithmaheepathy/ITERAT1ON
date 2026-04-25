# Satellite-Based Crop Stress Detection Pipeline

## Overview
Real pipeline for detecting crop stress using Sentinel-2 NDVI computed from actual band data (B4=Red, B8=NIR).

**No fake data. No hardcoded values. Every metric is derived from actual pixel computation.**

---

## What This Does — and What It Doesn't

### What IS real:
- NDVI computation from actual Sentinel-2 GeoTIFF band pixels
- Per-tile statistical aggregation (mean, std, min, max)
- Stress classification from computed thresholds
- JSON output derived entirely from computed results
- Cloud masking using SCL band (if available)

### What is NOT included (and why):
- **TerraMind integration**: TerraMind (IBM's geospatial foundation model) requires access to their hosted API/weights. It's valid for cloud gap-filling or temporal interpolation. See `TERRAMIND_NOTE.md` for exact integration pattern. It is NOT included here because faking its outputs would violate the project rules.
- **Real-time streaming**: This is a batch pipeline. No real-time claims.
- **Trend analysis**: Requires ≥2 timestamps. The pipeline supports it if you provide multi-date data.

---

## Project Structure

```
crop_stress_detection/
├── README.md
├── TERRAMIND_NOTE.md
├── environment.yml              # Conda environment spec
├── configs/
│   └── pipeline_config.yaml     # Thresholds, tile size, paths
├── data/
│   ├── raw/                     # Put downloaded Sentinel-2 .SAFE folders here
│   ├── processed/               # Extracted band GeoTIFFs go here
│   └── tiles/                   # Per-tile NDVI rasters
├── models/                      # For TerraMind weights (if used)
├── outputs/                     # Final JSON results
├── logs/                        # Processing logs
└── src/
    ├── download_data.py         # Guide + sentinel-hub / Copernicus download
    ├── preprocess.py            # Extract bands from .SAFE, cloud mask
    ├── ndvi.py                  # NDVI computation from real pixels
    ├── tiling.py                # Divide AOI into tiles
    ├── stress_classifier.py     # Threshold-based classification
    ├── alert_generator.py       # Per-tile alert logic
    ├── output_writer.py         # Structured JSON writer
    └── run_pipeline.py          # Main entry point
```

---

## Step 1: Environment Setup

```bash
conda env create -f environment.yml
conda activate crop_stress
```

---

## Step 2: Get Real Sentinel-2 Data

See `src/download_data.py` for full instructions. Quick summary:

**Option A — Copernicus Data Space (Free)**
1. Register at https://dataspace.copernicus.eu/
2. Use OData API or `sentinelsat` to query and download
3. Unzip `.SAFE` folders into `data/raw/`

**Option B — Google Earth Engine (Python API)**
```bash
pip install earthengine-api
earthengine authenticate
```
Then run: `python src/download_data.py --method gee --aoi your_coords.geojson`

---

## Step 3: Run Pipeline

```bash
python src/run_pipeline.py \
    --safe_dir data/raw/S2A_MSIL2A_*.SAFE \
    --output outputs/result.json \
    --tile_size_km 5 \
    --config configs/pipeline_config.yaml
```

---

## Step 4: Validate Output

```bash
python src/run_pipeline.py --validate outputs/result.json
```
Prints intermediate NDVI stats, tile counts, alert breakdown.