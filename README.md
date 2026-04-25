# Crop Stress Alert System

A satellite-based crop stress detection and alert system that combines real Sentinel-2 NDVI analysis with an interactive dashboard for agricultural monitoring and insurance surveying.

## Architecture

```
crop-stress-alert-system/
├── backend/                     # FastAPI REST API (survey simulation + dashboard data)
├── frontend/                    # React + Vite dashboard (Leaflet maps, charts)
└── crop_stress_detection/       # Sentinel-2 NDVI pipeline (real satellite data processing)
```

### Backend
FastAPI server providing district-level crop survey data, satellite pass simulation, and search/coordinate lookup endpoints.

- **Stack**: Python, FastAPI, Uvicorn
- **Run**: `cd backend && pip install -r requirements.txt && uvicorn main:app --reload`

### Frontend
Interactive dashboard with satellite map, district grid, NDVI trends, and alert feed.

- **Stack**: React 18, Vite, Tailwind CSS, Leaflet, Axios
- **Run**: `cd frontend && npm install && npm run dev`

### Crop Stress Detection
Real pipeline for detecting crop stress using Sentinel-2 NDVI computed from actual band data (B04=Red, B08=NIR). No fake data — every metric is derived from actual pixel computation.

- **Stack**: Python, Rasterio, NumPy, GDAL
- **Setup**: `cd crop_stress_detection && conda env create -f environment.yml && conda activate crop_stress`
- **Run**: `python src/run_pipeline.py --safe_dir data/raw/<YOUR_SAFE_FOLDER> --output outputs/result.json`
- See [`crop_stress_detection/README.md`](crop_stress_detection/README.md) for full details.

## Data

Sentinel-2 satellite imagery (`.SAFE` folders, GeoTIFFs) is **not included** in this repository due to size. See `crop_stress_detection/src/download_data.py` for download instructions.
