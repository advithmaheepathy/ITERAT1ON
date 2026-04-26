# AgriSat-7 — Crop Stress Alert System

## Project Scope & Honest Disclaimers — PixelToPolicy
*What we built, what we simulated, and what comes next*

- **What is real:** The core idea, the fine-tuned TerraMind LLM, the backend pipeline, and the frontend dashboard are all fully built and functional. The system correctly processes satellite spectral data (B04, B08, B12 bands + computed NDVI/NBR indices) and outputs structured JSON with burn area estimates.
- **Imaginary satellite:** We do not have access to a real satellite. The satellite in our architecture is simulated — inputs are sent as if going to a satellite, TerraMind processes them on the backend, and the JSON response is returned as if downlinked from orbit. This represents the intended production flow.
- **Real dataset — Kangaroo Island fire:** The before/after comparison feature uses actual Sentinel-2 satellite imagery of the Kangaroo Island bushfire. Pressing Start Comparing sends these real files to TerraMind and returns a genuine JSON analysis. The location/date selectors on the UI demonstrate how real satellite inputs would be structured — they are not live queries.
- **Custom Analysis — hardcoded demo data:** The Custom Analysis feature uses hardcoded sample data for demonstration purposes. It does not call TerraMind. It shows how the UI would present on-demand land queries in a production system.
- **Prediction feature — real TerraMind inference:** The Prediction button uses the pre-fire Kangaroo Island dataset and runs actual TerraMind inference to estimate potential burn loss based on pre-fire vegetation indices (NDVI, NBR). This is genuine model output, not hardcoded.
- **Flood & drought — not implemented:** We could not source high-resolution before/after datasets for flood and drought scenarios within the hackathon timeline. The logic and architecture support these — only the training data and final UI output are absent.
- **API — not production-tested:** The API endpoints are architected and documented but not commercially tested due to time constraints. The structure is correct and ready for integration.
- **Current scope — fire only:** This version focuses exclusively on fire/burn damage assessment. The system estimates approximate affected area from satellite spectral data, saving insurance companies the cost and time of manual field surveys after fire events.
- **Why we're showing this:** We believe in building honestly. Every feature shown is either real or clearly marked as a simulation. The satellite architecture, TerraMind integration, and burn detection logic are production-ready in design — the limitations are purely dataset availability and hackathon time constraints, not technical gaps.

A satellite command center dashboard that performs **real burn severity analysis** on Sentinel-2 imagery using dNBR (delta Normalized Burn Ratio). Built for the TakeMe2Space hackathon.

## Quick Start

### Prerequisites
- **Node.js** ≥ 18 and **npm**
- **Python** ≥ 3.10 and **pip**

### 1. Clone & Install

```bash
git clone https://github.com/advithmaheepathy/ITERAT1ON.git
cd ITERAT1ON

# Python dependencies (covers backend + analysis + ML)
pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

### 2. Download & Place Dataset

The Sentinel-2 datasets are **not included** in this repository (~2 GB total). You need two `.SAFE` products:

| Product | Filename |
|---------|----------|
| Pre-fire (S2A) | `S2A_MSIL2A_20191216T004701_N0500_R102_T53HQA_20230619T020958.SAFE` |
| Post-fire (S2B) | `S2B_MSIL2A_20200130T004659_N0500_R102_T53HQA_20230426T105901.SAFE` |

**Default location:** Place both `.SAFE` folders inside `C:\dss\` (Windows) or set the environment variable:

```bash
# Windows (PowerShell)
$env:DSS_DATA_DIR = "D:\your\dataset\folder"

# Linux / macOS
export DSS_DATA_DIR="/path/to/your/dataset/folder"
```

The expected folder structure:
```
C:\dss\                          (or your DSS_DATA_DIR)
├── S2A_MSIL2A_..._T53HQA_....SAFE/
│   └── S2A_MSIL2A_..._T53HQA_....SAFE/
│       └── GRANULE/
│           └── L2A_T53HQA_.../
│               └── IMG_DATA/
│                   ├── R10m/   (B04, B08)
│                   └── R20m/   (B12, SCL)
└── S2B_MSIL2A_..._T53HQA_....SAFE/
    └── S2B_MSIL2A_..._T53HQA_....SAFE/
        └── GRANULE/
            └── ...
```

> **Note:** These are standard Copernicus Data Space downloads. The double-nesting (`X.SAFE/X.SAFE/GRANULE/...`) is the default structure when extracted from the zip.

### 3. Run

**Option A — Standalone inference (no servers needed):**

```bash
# ML prediction only (pre-fire image)
python infer.py --pre "C:/dss/S2A_MSIL2A_.../S2A_..."

# Full analysis (both images)
python infer.py --pre "C:/dss/S2A_MSIL2A_.../S2A_..." --post "C:/dss/S2B_MSIL2A_.../S2B_..."
```

**Option B — Dashboard UI (interactive map):**

Open two terminals:

```bash
# Terminal 1 — Backend API (port 8000)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Terminal 2 — Frontend Dev Server (port 5173)
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser.

### 4. Use

1. Draw a rectangle on the map using the tool in the top-right corner.
2. **Start Comparing** — Full burn severity analysis using both pre/post images (~90s)
3. **Predict Damage** — ML-powered damage forecast using only the pre-fire image (~30s)
4. **Custom Analysis** — Select individual spectral parameters to analyze
5. View the summary results. Click **Advanced Details** to see the full JSON output.

### 5. Fine-Tune ML Models (Optional)

The ML models are pre-trained and saved in `crop_stress_detection/models/`. To re-train:

```bash
cd crop_stress_detection

# 1. Severity Classifier (Random Forest) — validates dNBR with ML
python src/finetune_severity_classifier.py \
  --pre "C:/dss/S2A_.../S2A_..." \
  --post "C:/dss/S2B_.../S2B_..."

# 2. Vegetation Recovery Predictor — predicts damage from pre-fire only
python src/finetune_vegetation_recovery.py \
  --pre "C:/dss/S2A_.../S2A_..." \
  --post "C:/dss/S2B_.../S2B_..."
```

---

## Architecture

```
crop-stress-alert-system/
├── backend/                     # FastAPI REST API
│   ├── main.py                  # All endpoints + subprocess trigger
│   └── requirements.txt         # Python dependencies
├── frontend/                    # React + Vite dashboard
│   ├── src/App.jsx              # Main dashboard layout
│   └── src/components/          # AOISelector, ApiServicesModal, etc.
└── crop_stress_detection/       # Sentinel-2 analysis engine
    ├── src/
    │   ├── burn_analysis_v3.py                # dNBR burn analysis (USGS standard)
    │   ├── predict_damage.py                  # ML damage prediction (pre-fire only)
    │   ├── finetune_severity_classifier.py    # RF fine-tuning script
    │   ├── finetune_vegetation_recovery.py    # Vegetation predictor fine-tuning
    │   └── preprocess.py                      # Band loading, cloud masking
    ├── models/                  # Saved ML models (.joblib)
    ├── outputs/                 # Generated JSON results
    └── environment.yml          # Conda env (alternative to pip)
```

## How It Works

### Burn Detection (Start Comparing)
1. **Backend** receives the AOI bounding box via `/analyze` endpoint
2. **Subprocess** executes `burn_analysis_v3.py` with both Sentinel-2 datasets
3. **Script** loads B04 (Red), B08 (NIR), B12 (SWIR) bands from both dates
4. **Computes** NBR for each date, then dNBR = NBR_pre − NBR_post
5. **Classifies** severity using USGS Key et al. (2006) standard thresholds
6. **Returns** JSON with statistics, severity distribution, and NDVI change

### ML Damage Prediction (Predict Damage)
1. Uses **only the pre-fire image** — no post-fire data needed
2. Loads a **fine-tuned Gradient Boosting model** (trained on real Sentinel-2 data)
3. Extracts spectral features (B04, B08, B12, NDVI, NBR) from 100K sampled pixels
4. **Predicts vegetation damage** (delta NDVI) for each pixel
5. Returns predicted damage level, distribution, and confidence metrics

### ML Fine-Tuning
- **Severity Classifier**: Random Forest trained on 150K pixels, 99.99% accuracy — validates that dNBR is the dominant predictor of burn severity
- **Vegetation Recovery**: Gradient Boosting regressor, R²=0.47, 88.1% category accuracy — predicts damage from pre-fire spectral features alone

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DSS_DATA_DIR` | `C:/dss` | Path to folder containing the two `.SAFE` dataset directories |

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, Rasterio, NumPy
- **Frontend:** React 18, Vite, Tailwind CSS, Leaflet, Axios
- **ML:** scikit-learn (Random Forest, Gradient Boosting), joblib
- **Analysis:** dNBR burn severity (USGS standard), NDVI vegetation change
- **Data:** Sentinel-2 L2A (Copernicus Data Space)
