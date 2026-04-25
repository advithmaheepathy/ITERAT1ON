import React, { useEffect, useRef, useMemo } from 'react'
import { MapContainer, TileLayer, Polygon, CircleMarker, Popup, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

/* ─── Derive stress level from damage_pct ─── */
function getStressLevel(d) {
  if (d.damage_pct >= 30) return 'high'
  if (d.damage_pct >= 15) return 'medium'
  return 'low'
}

/* ─── Color mappings ─── */
const STRESS_COLORS = {
  high:   { fill: '#ef4444', border: '#dc2626', opacity: 0.25, borderOpacity: 0.8 },
  medium: { fill: '#eab308', border: '#ca8a04', opacity: 0.20, borderOpacity: 0.7 },
  low:    { fill: '#22c55e', border: '#16a34a', opacity: 0.15, borderOpacity: 0.6 },
}

const ZONE_COLORS = {
  critical: { fill: '#ef4444', border: '#991b1b' },
  warning:  { fill: '#f59e0b', border: '#92400e' },
  info:     { fill: '#3b82f6', border: '#1e40af' },
}

/* ─── Fly-to animation when a district is focused ─── */
function FlyToDistrict({ district }) {
  const map = useMap()
  useEffect(() => {
    if (district?.lat && district?.lng) {
      map.flyTo([district.lat, district.lng], 10, { duration: 1.2 })
    }
  }, [district, map])
  return null
}

/* ─── Reset to India-wide view ─── */
function FlyToDefault({ shouldReset }) {
  const map = useMap()
  useEffect(() => {
    if (shouldReset) {
      map.flyTo([22.5, 79.0], 5, { duration: 1.0 })
    }
  }, [shouldReset, map])
  return null
}

/* ─── Main SatelliteMap component ─── */
export default function SatelliteMap({ districts, focusedDistrict, onSelectDistrict }) {
  const mapRef = useRef(null)

  /* Convert boundary arrays to Leaflet polygon format */
  const polygons = useMemo(() => {
    return districts.map(d => ({
      ...d,
      positions: d.boundary
        ? d.boundary.map(([lat, lng]) => [lat, lng])
        : [],
    }))
  }, [districts])

  return (
    <div className="glass-card overflow-hidden relative">
      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-2 z-10 relative">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
            Satellite Imagery — Live View
          </h2>
          {focusedDistrict && (
            <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
              {focusedDistrict.name}, {focusedDistrict.state}
            </span>
          )}
        </div>
        {focusedDistrict && (
          <button
            onClick={() => onSelectDistrict(null)}
            className="text-[10px] text-slate-500 hover:text-slate-300 font-medium uppercase tracking-wider transition-colors flex items-center gap-1"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
            </svg>
            All India View
          </button>
        )}
      </div>

      {/* Map container */}
      <div className="h-[500px] w-full relative" style={{ zIndex: 0 }}>
        <MapContainer
          center={[22.5, 79.0]}
          zoom={5}
          className="h-full w-full"
          style={{ background: '#0a0f1a' }}
          zoomControl={false}
          ref={mapRef}
        >
          {/* Dark satellite-style tile layer */}
          <TileLayer
            attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />

          {/* Fly-to focused district or reset */}
          {focusedDistrict ? (
            <FlyToDistrict district={focusedDistrict} />
          ) : (
            <FlyToDefault shouldReset={!focusedDistrict} />
          )}

          {/* District boundary polygons */}
          {polygons.map(d => {
            if (!d.positions.length) return null
            const colors = STRESS_COLORS[getStressLevel(d)] || STRESS_COLORS.low
            const isFocused = focusedDistrict?.id === d.id

            return (
              <Polygon
                key={d.id}
                positions={d.positions}
                pathOptions={{
                  color: colors.border,
                  fillColor: colors.fill,
                  fillOpacity: isFocused ? colors.opacity + 0.15 : colors.opacity,
                  weight: isFocused ? 3 : 1.5,
                  opacity: isFocused ? 1 : colors.borderOpacity,
                  dashArray: isFocused ? null : '4 4',
                }}
                eventHandlers={{
                  click: () => onSelectDistrict(d),
                }}
              >
                <Popup className="satellite-popup">
                  <div className="text-xs">
                    <p className="font-bold text-sm mb-1">{d.name}</p>
                    <p className="text-gray-500">{d.state} · {d.primary_crop}</p>
                    <div className="mt-2 space-y-0.5">
                      <p>NDVI: <span className="font-mono font-bold">{d.ndvi?.toFixed(2)}</span></p>
                      <p>Damage: <span className="font-bold">{d.damage_pct}%</span></p>
                      <p>Affected: <span className="font-mono">{d.affected_ha?.toLocaleString()} ha</span></p>
                      <p>Confidence: <span className="font-mono">{d.confidence}%</span></p>
                    </div>
                  </div>
                </Popup>
              </Polygon>
            )
          })}

          {/* Affected zone markers (circles) */}
          {polygons.map(d =>
            (d.affected_zones || []).map((zone, zi) => {
              const zc = ZONE_COLORS[zone.severity] || ZONE_COLORS.info
              const isFocused = focusedDistrict?.id === d.id
              const baseRadius = zone.radius_km * 800

              return (
                <CircleMarker
                  key={`${d.id}-zone-${zi}`}
                  center={[zone.lat, zone.lng]}
                  radius={isFocused ? zone.radius_km * 3 : zone.radius_km * 2}
                  pathOptions={{
                    color: zc.border,
                    fillColor: zc.fill,
                    fillOpacity: isFocused ? 0.55 : 0.35,
                    weight: isFocused ? 2.5 : 1.5,
                  }}
                >
                  <Popup>
                    <div className="text-xs">
                      <p className="font-bold text-sm mb-1">⚠ {zone.label}</p>
                      <p className="text-gray-500">{d.name}, {d.state}</p>
                      <p className="mt-1">Severity: <span className="font-bold capitalize">{zone.severity}</span></p>
                      <p>Radius: ~{zone.radius_km} km</p>
                      <p className="font-mono text-gray-400 text-[10px] mt-1">{zone.lat}°N, {zone.lng}°E</p>
                    </div>
                  </Popup>
                </CircleMarker>
              )
            })
          )}
        </MapContainer>

        {/* Map legend overlay */}
        <div className="absolute bottom-3 left-3 z-[1000] glass-card p-3 !rounded-xl">
          <p className="text-[9px] uppercase tracking-widest text-slate-500 mb-2 font-semibold">Legend</p>
          <div className="space-y-1.5">
            <LegendItem color="#ef4444" label="High Stress / Critical" />
            <LegendItem color="#eab308" label="Medium / Warning" />
            <LegendItem color="#22c55e" label="Low / Healthy" />
            <LegendItem color="#3b82f6" label="Cloud Cover" />
          </div>
          <div className="border-t border-slate-700/40 mt-2 pt-2 space-y-1.5">
            <LegendItem color="#ef4444" label="Affected Zone" circle />
            <LegendItem color="#f59e0b" label="Warning Zone" circle />
          </div>
        </div>

        {/* Coordinates overlay for focused district */}
        {focusedDistrict && (
          <div className="absolute top-3 right-3 z-[1000] glass-card p-3 !rounded-xl animate-fade-in">
            <p className="text-[9px] uppercase tracking-widest text-slate-500 mb-1 font-semibold">Coordinates</p>
            <p className="text-xs font-mono text-emerald-400">{focusedDistrict.lat}°N, {focusedDistrict.lng}°E</p>
            <p className="text-[10px] text-slate-400 mt-1">{focusedDistrict.affected_zones?.length || 0} affected zones</p>
          </div>
        )}
      </div>
    </div>
  )
}

function LegendItem({ color, label, circle }) {
  return (
    <div className="flex items-center gap-2">
      {circle ? (
        <div className="w-3 h-3 rounded-full border-2 opacity-80" style={{ borderColor: color, backgroundColor: color + '55' }} />
      ) : (
        <div className="w-4 h-2.5 rounded-sm opacity-70" style={{ backgroundColor: color }} />
      )}
      <span className="text-[10px] text-slate-400">{label}</span>
    </div>
  )
}
