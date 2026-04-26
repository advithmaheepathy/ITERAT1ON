"""
AgriSat-7 — Satellite Crop Insurance Survey System
Replaces traditional human surveyors with onboard AI inference.
"""
import json, random, math, secrets, os, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AgriSat-7 Crop Survey API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DATA_PATH = Path(__file__).parent / "data.json"
API_KEYS_PATH = Path(__file__).parent / "api_keys.json"


# ─── API Key Management ───────────────────────────────────────────
def _load_or_create_api_key() -> str:
    """Load the API key from disk, or generate and persist a new one."""
    if API_KEYS_PATH.exists():
        with open(API_KEYS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("api_key"):
                return data["api_key"]
    key = f"agrisat7_{secrets.token_hex(24)}"
    with open(API_KEYS_PATH, "w", encoding="utf-8") as f:
        json.dump({"api_key": key, "created_at": datetime.now(timezone.utc).isoformat()}, f, indent=2)
    return key


API_SECRET = _load_or_create_api_key()


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Dependency that validates the X-API-Key header."""
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key

def load_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_mock_dnbr(size=300):
    """Generate a synthetic dNBR array with some burn clusters."""
    # Base noise (mostly unburned)
    dnbr = np.random.normal(0, 0.05, (size, size))
    
    # Create some burn hotspots
    for _ in range(8):
        cx, cy = random.randint(0, size), random.randint(0, size)
        radius = random.randint(15, 60)
        y, x = np.ogrid[-cx:size-cx, -cy:size-cy]
        mask = x**2 + y**2 <= radius**2
        dnbr[mask] += np.random.uniform(0.2, 0.9, mask.sum())
    
    return dnbr


@app.get("/dashboard")
def get_dashboard():
    """Full dashboard: hardware specs, economics, all districts."""
    data = load_data()
    hw = data["satellite_hardware"]
    eco = data["survey_economics"]
    districts = data["districts"]

    total_farmland = sum(d["total_farmland_ha"] for d in districts)
    total_affected = sum(d["affected_ha"] for d in districts)
    total_surveyed = sum(d["surveyed_ha"] for d in districts)
    trad_cost = total_farmland * eco["traditional_cost_per_ha"]
    sat_cost = total_farmland * eco["satellite_cost_per_ha"]

    # Generate synthetic dNBR and downsampled burn map
    dnbr = generate_mock_dnbr(size=400)
    burn_map = np.zeros_like(dnbr, dtype=int)
    burn_map[(dnbr >= 0.1) & (dnbr < 0.3)] = 1
    burn_map[(dnbr >= 0.3) & (dnbr < 0.6)] = 2
    burn_map[dnbr >= 0.6] = 3
    
    # Downsample for frontend (400x400 -> 40x40 grid if ::10)
    burn_map_small = burn_map[::10, ::10]

    return {
        "satellite_hardware": hw,
        "survey_economics": eco,
        "districts": districts,
        "burn_map": burn_map_small.tolist(),
        "totals": {
            "total_farmland_ha": total_farmland,
            "total_surveyed_ha": total_surveyed,
            "total_affected_ha": total_affected,
            "avg_damage_pct": round(total_affected / total_farmland * 100, 1) if total_farmland else 0,
            "district_count": len(districts),
            "traditional_cost_inr": trad_cost,
            "satellite_cost_inr": sat_cost,
            "cost_saved_inr": trad_cost - sat_cost,
            "traditional_time_days": eco["traditional_days_per_district"] * len(districts),
            "satellite_time_min": eco["satellite_minutes_per_district"] * len(districts),
        },
    }


@app.get("/district/{district_id}")
def get_district(district_id: str):
    """Single district survey report."""
    data = load_data()
    eco = data["survey_economics"]
    for d in data["districts"]:
        if d["id"] == district_id:
            trad = d["total_farmland_ha"] * eco["traditional_cost_per_ha"]
            sat = d["total_farmland_ha"] * eco["satellite_cost_per_ha"]
            return {
                **d,
                "economics": {
                    "traditional_cost_inr": trad,
                    "satellite_cost_inr": sat,
                    "cost_saved_inr": trad - sat,
                    "traditional_time_days": eco["traditional_days_per_district"],
                    "satellite_time_min": eco["satellite_minutes_per_district"],
                },
            }
    raise HTTPException(404, f"District '{district_id}' not found")


@app.get("/search")
def search_districts(q: str = Query("", min_length=0)):
    """Search districts by name, state, crop, or disaster type."""
    data = load_data()
    q_lower = q.lower().strip()
    if not q_lower:
        return data["districts"]
    results = []
    for d in data["districts"]:
        searchable = f"{d['name']} {d['state']} {d['primary_crop']} {d.get('secondary_crop','')} {d['disaster_type']}".lower()
        if q_lower in searchable:
            results.append(d)
    return results


@app.get("/coordinates")
def find_by_coordinates(lat: float = Query(...), lng: float = Query(...)):
    """Find the nearest district to given coordinates."""
    data = load_data()
    best, best_dist = None, float("inf")
    for d in data["districts"]:
        dist = math.sqrt((d["lat"] - lat) ** 2 + (d["lng"] - lng) ** 2)
        if dist < best_dist:
            best, best_dist = d, dist
    if best and best_dist < 3.0:
        eco = data["survey_economics"]
        trad = best["total_farmland_ha"] * eco["traditional_cost_per_ha"]
        sat = best["total_farmland_ha"] * eco["satellite_cost_per_ha"]
        return {
            **best,
            "distance_deg": round(best_dist, 3),
            "economics": {
                "traditional_cost_inr": trad,
                "satellite_cost_inr": sat,
                "cost_saved_inr": trad - sat,
            },
        }
    raise HTTPException(404, "No surveyed district found near those coordinates")


ZONE_TEMPLATES = {
    "drought": [
        "Severe drought — {pct}% farmland destroyed, crop wilted",
        "Soil moisture critical at {sm}% — irrigation failure",
        "Groundwater depleted — bore wells dry, no recovery",
    ],
    "flood": [
        "Active flood — {pct}% farmland submerged",
        "Waterlogging {days}+ days — root rot confirmed",
        "River breach — sediment deposit destroying crops",
    ],
    "pest": [
        "Pest infestation — {pct}% crop destroyed by bollworm",
        "Virus signature in spectral bands — spreading across mandals",
        "Fungal blight — humidity {hum}% enabling rapid spread",
    ],
    "none": [
        "Minor anomaly — monitoring required, no action needed",
    ],
}


@app.post("/simulate-pass")
def simulate_pass():
    """Simulate a satellite pass — re-scan all districts."""
    data = load_data()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for d in data["districts"]:
        # Drift NDVI
        drift = round(random.uniform(-0.04, 0.04), 3)
        d["ndvi"] = round(max(0.15, min(0.95, d["ndvi"] + drift)), 2)

        # Re-derive damage from NDVI
        if d["ndvi"] < 0.30:
            d["damage_pct"] = round(random.uniform(50, 70), 1)
            d["disaster_type"] = "drought"
        elif d["ndvi"] < 0.45:
            d["damage_pct"] = round(random.uniform(25, 45), 1)
        elif d["ndvi"] < 0.60:
            d["damage_pct"] = round(random.uniform(10, 25), 1)
        else:
            d["damage_pct"] = round(random.uniform(2, 10), 1)

        d["affected_ha"] = int(d["total_farmland_ha"] * d["damage_pct"] / 100)
        d["surveyed_ha"] = d["total_farmland_ha"]
        d["confidence"] = round(max(65, min(99, d["confidence"] + random.uniform(-2, 2))), 1)
        d["soil_moisture_pct"] = max(5, min(98, d["soil_moisture_pct"] + random.randint(-4, 4)))
        d["tiles_processed"] += random.randint(10, 50)

        # Regenerate affected zones
        dtype = d["disaster_type"]
        templates = ZONE_TEMPLATES.get(dtype, ZONE_TEMPLATES["none"])
        zone_count = 3 if d["damage_pct"] > 30 else 2 if d["damage_pct"] > 15 else (1 if d["damage_pct"] > 5 else 0)
        zones = []
        for _ in range(zone_count):
            zlat = round(d["lat"] + random.uniform(-0.20, 0.20), 4)
            zlng = round(d["lng"] + random.uniform(-0.20, 0.20), 4)
            tmpl = random.choice(templates)
            label = tmpl.format(pct=int(d["damage_pct"]), sm=d["soil_moisture_pct"], days=random.randint(2, 7), hum=random.randint(80, 95))
            zones.append({
                "lat": zlat, "lng": zlng,
                "radius_km": random.randint(5, 16),
                "severity": "critical" if d["damage_pct"] > 25 else "warning" if d["damage_pct"] > 10 else "info",
                "label": label,
            })
        d["affected_zones"] = zones

    save_data(data)
    return {"status": "survey_complete", "timestamp": now, "districts_scanned": len(data["districts"])}


@app.post("/analyze")
def analyze_aoi(payload: dict):
    """
    Accept an AOI bounding box and run analysis.
    Expected payload:
    {
        "aoi": {
            "type": "bbox",
            "coordinates": {
                "top_left": [lat, lon],
                "top_right": [lat, lon],
                "bottom_left": [lat, lon],
                "bottom_right": [lat, lon]
            }
        },
        "analysis": "burn_detection"
    }
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    aoi = payload.get("aoi", {})
    analysis_type = payload.get("analysis", "burn_detection")
    coords = aoi.get("coordinates", {})

    # Validate
    required_keys = ["top_left", "top_right", "bottom_left", "bottom_right"]
    for k in required_keys:
        if k not in coords:
            raise HTTPException(400, f"Missing coordinate: {k}")
        if not isinstance(coords[k], list) or len(coords[k]) != 2:
            raise HTTPException(400, f"Invalid coordinate format for {k}: expected [lat, lon]")

    tl = coords["top_left"]
    br = coords["bottom_right"]

    # Compute bbox metrics
    lat_diff = abs(tl[0] - br[0])
    lon_diff = abs(br[1] - tl[1])
    avg_lat = (tl[0] + br[0]) / 2
    km_lat = lat_diff * 111
    km_lon = lon_diff * 111 * math.cos(math.radians(avg_lat))
    area_sq_km = km_lat * km_lon
    area_ha = area_sq_km * 100
    center_lat = round(avg_lat, 6)
    center_lon = round((tl[1] + br[1]) / 2, 6)

    # If custom analysis, return selected metrics instead of burn detection
    if analysis_type == "custom":
        # Load the mock JSON
        mock_file_path = os.path.join(os.path.dirname(__file__), "custom_mock_data.json")
        try:
            with open(mock_file_path, "r") as f:
                mock_data = json.load(f)
        except Exception as e:
            mock_data = {"results": {}, "summary": {}}

        custom_outputs = payload.get("customOutputs", {})
        custom_metrics = {}
        
        # Map frontend flags to JSON keys
        mapping = {
            "showNdvi": ("NDVI", "ndvi"),
            "showNdwi": ("NDWI", "ndwi"),
            "showNbr": ("NBR", "nbr"),
            "showLst": ("LST", "lst"),
            "showLulc": ("LULC", "lulc"),
            "showSmi": ("Soil Moisture Index", "soil_moisture_index"),
            "showCloud": ("Cloud Cover & Masking", "cloud_masking"),
            "showBiomass": ("Biomass & Carbon", "biomass_carbon"),
        }

        for flag, (display_name, json_key) in mapping.items():
            if custom_outputs.get(flag) and json_key in mock_data.get("results", {}):
                custom_metrics[display_name] = mock_data["results"][json_key]

        return {
            "status": "analysis_complete",
            "timestamp": now,
            "aoi": {
                "type": aoi.get("type", "bbox"),
                "coordinates": coords,
                "center": [center_lat, center_lon],
                "area_ha": round(area_ha, 1),
                "area_sq_km": round(area_sq_km, 2),
            },
            "analysis": "custom",
            "result": {
                "custom_metrics": custom_metrics,
                "summary": mock_data.get("summary", {})
            }
        }

    # Execute the external crop stress detection script
    script_path = Path(__file__).parent.parent / "crop_stress_detection" / "src" / "burn_analysis_v3.py"
    output_json_path = Path(__file__).parent.parent / "crop_stress_detection" / "outputs" / "burn_result_v3.json"
    
    # Dataset directory — configurable via DSS_DATA_DIR env var, defaults to C:/dss
    dss_dir = Path(os.environ.get("DSS_DATA_DIR", "C:/dss"))
    before_safe = dss_dir / "S2A_MSIL2A_20191216T004701_N0500_R102_T53HQA_20230619T020958.SAFE" / "S2A_MSIL2A_20191216T004701_N0500_R102_T53HQA_20230619T020958.SAFE"
    after_safe = dss_dir / "S2B_MSIL2A_20200130T004659_N0500_R102_T53HQA_20230426T105901.SAFE" / "S2B_MSIL2A_20200130T004659_N0500_R102_T53HQA_20230426T105901.SAFE"

    if not before_safe.exists() or not after_safe.exists():
        raise HTTPException(400, f"Sentinel-2 datasets not found in '{dss_dir}'. Set the DSS_DATA_DIR environment variable to the folder containing the .SAFE directories. See README for details.")

    try:
        # Run the script synchronously
        script_cwd = Path(__file__).parent.parent / "crop_stress_detection"
        # Force UTF-8 encoding so Unicode box-drawing chars don't crash on Windows cp1252
        script_env = os.environ.copy()
        script_env["PYTHONIOENCODING"] = "utf-8"
        subprocess.run([
            "python", str(script_path),
            "--pre", str(before_safe),
            "--post", str(after_safe),
            "--output", str(output_json_path)
        ], check=True, capture_output=True, cwd=str(script_cwd), env=script_env)
        
        # Read the generated JSON
        if output_json_path.exists():
            with open(output_json_path, "r", encoding="utf-8") as f:
                script_result = json.load(f)
        else:
            raise HTTPException(500, "Script executed but no JSON output was found.")
            
    except subprocess.CalledProcessError as e:
        print(f"Script Error: {e.stderr.decode()}")
        raise HTTPException(500, "Failed to execute crop stress detection script.")

    return {
        "status": "analysis_complete",
        "timestamp": now,
        "aoi": {
            "type": aoi.get("type", "bbox"),
            "coordinates": coords,
            "center": [center_lat, center_lon],
            "area_ha": round(area_ha, 1),
            "area_sq_km": round(area_sq_km, 2),
        },
        "analysis": analysis_type,
        "result": script_result
    }


# ═══════════════════════════════════════════════════════════════════
#  PUBLIC API v1 — Key-authenticated endpoints for integrations
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/key")
def get_api_key():
    """Return the API secret (used by the frontend popup). No auth required."""
    return {
        "api_key": API_SECRET,
        "usage": "Include this key in the X-API-Key header for all /api/v1/* requests.",
        "base_url": "/api/v1",
    }


@app.get("/api/v1/districts", dependencies=[Depends(verify_api_key)])
def api_list_districts():
    """List all surveyed districts."""
    data = load_data()
    return {
        "status": "ok",
        "count": len(data["districts"]),
        "districts": data["districts"],
    }


@app.get("/api/v1/district/{district_id}", dependencies=[Depends(verify_api_key)])
def api_get_district(district_id: str):
    """Get a single district by ID."""
    data = load_data()
    eco = data["survey_economics"]
    for d in data["districts"]:
        if d["id"] == district_id:
            trad = d["total_farmland_ha"] * eco["traditional_cost_per_ha"]
            sat = d["total_farmland_ha"] * eco["satellite_cost_per_ha"]
            return {
                "status": "ok",
                **d,
                "economics": {
                    "traditional_cost_inr": trad,
                    "satellite_cost_inr": sat,
                    "cost_saved_inr": trad - sat,
                },
            }
    raise HTTPException(404, f"District '{district_id}' not found")


@app.get("/api/v1/query", dependencies=[Depends(verify_api_key)])
def api_query_bbox(
    top_lat: float = Query(..., description="Northern latitude of bounding box"),
    top_lng: float = Query(..., description="Eastern longitude of bounding box"),
    bottom_lat: float = Query(..., description="Southern latitude of bounding box"),
    bottom_lng: float = Query(..., description="Western longitude of bounding box"),
    ndvi: bool = Query(False, description="Include NDVI analysis"),
    ndwi: bool = Query(False, description="Include NDWI analysis"),
    nbr: bool = Query(False, description="Include NBR analysis"),
    lst: bool = Query(False, description="Include LST analysis"),
    lulc: bool = Query(False, description="Include LULC analysis"),
    smi: bool = Query(False, description="Include Soil Moisture Index"),
    cloud: bool = Query(False, description="Include Cloud Cover & Masking"),
    biomass: bool = Query(False, description="Include Biomass & Carbon"),
):
    """
    Query crop stress data within a bounding box defined by four coordinates.

    Provide the top-left (top_lat, bottom_lng) and bottom-right (bottom_lat, top_lng)
    corners. Optionally enable analysis parameters via boolean flags.

    Returns districts inside the bbox and selected metric analysis.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Validate bbox
    north = max(top_lat, bottom_lat)
    south = min(top_lat, bottom_lat)
    east = max(top_lng, bottom_lng)
    west = min(top_lng, bottom_lng)

    if north == south or east == west:
        raise HTTPException(400, "Bounding box has zero area — provide distinct coordinates")

    # Compute area
    lat_diff = abs(north - south)
    lon_diff = abs(east - west)
    avg_lat = (north + south) / 2
    km_lat = lat_diff * 111
    km_lon = lon_diff * 111 * math.cos(math.radians(avg_lat))
    area_sq_km = km_lat * km_lon
    area_ha = area_sq_km * 100
    center_lat = round(avg_lat, 6)
    center_lon = round((east + west) / 2, 6)

    # Find districts inside the bbox
    data = load_data()
    eco = data["survey_economics"]
    districts_inside = []
    for d in data["districts"]:
        if south <= d["lat"] <= north and west <= d["lng"] <= east:
            trad = d["total_farmland_ha"] * eco["traditional_cost_per_ha"]
            sat = d["total_farmland_ha"] * eco["satellite_cost_per_ha"]
            districts_inside.append({
                **d,
                "economics": {
                    "traditional_cost_inr": trad,
                    "satellite_cost_inr": sat,
                    "cost_saved_inr": trad - sat,
                },
            })

    # Build selected parameter analysis
    param_flags = {
        "ndvi": ndvi, "ndwi": ndwi, "nbr": nbr, "lst": lst,
        "lulc": lulc, "soil_moisture_index": smi,
        "cloud_masking": cloud, "biomass_carbon": biomass,
    }
    any_param = any(param_flags.values())
    analysis_results = {}

    if any_param:
        mock_file = Path(__file__).parent / "custom_mock_data.json"
        try:
            with open(mock_file, "r", encoding="utf-8") as f:
                mock_data = json.load(f)
        except Exception:
            mock_data = {"results": {}, "summary": {}}

        display_names = {
            "ndvi": "NDVI", "ndwi": "NDWI", "nbr": "NBR", "lst": "LST",
            "lulc": "LULC", "soil_moisture_index": "Soil Moisture Index",
            "cloud_masking": "Cloud Cover & Masking", "biomass_carbon": "Biomass & Carbon",
        }
        for key, enabled in param_flags.items():
            if enabled and key in mock_data.get("results", {}):
                analysis_results[display_names[key]] = mock_data["results"][key]

    response = {
        "status": "ok",
        "timestamp": now,
        "aoi": {
            "type": "bbox",
            "coordinates": {
                "top_left": [north, west],
                "top_right": [north, east],
                "bottom_left": [south, west],
                "bottom_right": [south, east],
            },
            "center": [center_lat, center_lon],
            "area_ha": round(area_ha, 1),
            "area_sq_km": round(area_sq_km, 2),
        },
        "districts_found": len(districts_inside),
        "districts": districts_inside,
    }

    if any_param:
        mock_summary = {}
        try:
            mock_summary = mock_data.get("summary", {})
        except Exception:
            pass
        response["analysis"] = {
            "parameters_requested": [k for k, v in param_flags.items() if v],
            "results": analysis_results,
            "summary": mock_summary,
        }

    return response
