"""
AgriSat-7 — Satellite Crop Insurance Survey System
Replaces traditional human surveyors with onboard AI inference.
"""
import json, random, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AgriSat-7 Crop Survey API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DATA_PATH = Path(__file__).parent / "data.json"

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
