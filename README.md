# AgriSat-7 — Crop Stress Alert System

A satellite command center dashboard that performs **real burn severity analysis** on Sentinel-2 imagery using dNBR (delta Normalized Burn Ratio). Built for the TakeMe2Space hackathon.

## Quick Start

### Prerequisites
- **Node.js** ≥ 18 and **npm**
- **Python** ≥ 3.10 and **pip**

### 1. Clone & Install

```bash
git clone https://github.com/advithmaheepathy/crop-stress-alert-system.git
cd crop-stress-alert-system

# Backend
cd backend
pip install -r requirements.txt
cd ..

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

Open **two terminals**:

```bash
# Terminal 1 — Backend API (port 8000)
cd backend
uvicorn main:app --reload

# Terminal 2 — Frontend Dev Server (port 5173)
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser.

### 4. Use

1. Draw a rectangle on the map using the tool in the top-right corner.
2. Click **Start Comparing** to run the real burn severity analysis.
3. Wait ~60–90 seconds while the script processes 120M+ pixels.
4. View the summary results. Click **Advanced Details** to see the full JSON output.

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
    │   ├── burn_analysis_v3.py  # Main analysis script (dNBR, USGS standard)
    │   └── preprocess.py        # Band loading, cloud masking, resampling
    ├── outputs/                 # Generated JSON results
    └── environment.yml          # Conda env (alternative to pip)
```

## How It Works

When you click **Start Comparing**, the system:

1. **Backend** receives the AOI bounding box via `/analyze` endpoint
2. **Subprocess** executes `burn_analysis_v3.py` with the two Sentinel-2 datasets
3. **Script** loads B04 (Red), B08 (NIR), B12 (SWIR) bands from both dates
4. **Computes** NBR for each date, then dNBR = NBR_pre − NBR_post
5. **Classifies** severity using USGS Key et al. (2006) standard thresholds
6. **Returns** a comprehensive JSON with statistics, severity distribution, and NDVI change
7. **Frontend** renders the summary with severity bars + expandable advanced details

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DSS_DATA_DIR` | `C:/dss` | Path to folder containing the two `.SAFE` dataset directories |

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, Rasterio, NumPy
- **Frontend:** React 18, Vite, Tailwind CSS, Leaflet, Axios
- **Analysis:** dNBR burn severity (USGS standard), NDVI vegetation change
- **Data:** Sentinel-2 L2A (Copernicus Data Space)
