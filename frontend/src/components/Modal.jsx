import React from 'react'

function getStressLevel(d) {
  if (d.damage_pct >= 30) return 'high'
  if (d.damage_pct >= 15) return 'medium'
  return 'low'
}

const stressColors = {
  high: 'text-red-400',
  medium: 'text-yellow-400',
  low: 'text-emerald-400',
}

function InfoBlock({ label, value, color, mono, small }) {
  return (
    <div className={`${small ? 'p-2' : 'p-3'} rounded-xl bg-slate-800/50 border border-slate-700/30`}>
      <p className={`${small ? 'text-[9px]' : 'text-[10px]'} uppercase tracking-wider text-slate-500 mb-0.5`}>{label}</p>
      <p className={`${small ? 'text-xs' : 'text-sm'} font-semibold ${color || 'text-white'} ${mono ? 'font-mono' : ''} truncate`}>{value}</p>
    </div>
  )
}

function getBadge(level) {
  if (level === 'high') return 'bg-red-500/20 text-red-400 border-red-500/30'
  if (level === 'medium') return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
  return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
}

function getDot(level) {
  if (level === 'high') return 'bg-red-400'
  if (level === 'medium') return 'bg-yellow-400'
  return 'bg-emerald-400'
}

function getLabel(level, disaster) {
  if (disaster && disaster !== 'none') return disaster.toUpperCase()
  if (level === 'low') return 'HEALTHY'
  return level.toUpperCase() + ' STRESS'
}

function formatINR(val) {
  if (val >= 10000000) return `₹${(val / 10000000).toFixed(1)} Cr`
  if (val >= 100000) return `₹${(val / 100000).toFixed(1)} L`
  return `₹${val.toLocaleString('en-IN')}`
}

export default function Modal({ district: d, onClose }) {
  if (!d) return null
  const level = getStressLevel(d)
  const sc = stressColors[level] || 'text-slate-400'

  // Compute economics inline
  const tradCost = d.total_farmland_ha * 800
  const satCost = d.total_farmland_ha * 12
  const saved = tradCost - satCost

  return (
    <div className="modal-overlay animate-fade-in" onClick={onClose}>
      <div className="glass-card w-full max-w-lg mx-4 p-0 animate-slide-up overflow-hidden max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="relative px-6 py-5 border-b border-slate-700/50">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-lg font-bold text-white">{d.name}</h2>
              <p className="text-xs text-slate-400 mt-0.5">{d.state}</p>
            </div>
            <button onClick={onClose} className="w-8 h-8 rounded-lg bg-slate-700/50 hover:bg-slate-600/60 flex items-center justify-center transition-colors">
              <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className={`mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border ${getBadge(level)}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${getDot(level)}`} />
            {getLabel(level, d.disaster_type)}
          </div>
        </div>

        {/* Survey Data */}
        <div className="px-6 py-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <InfoBlock label="Primary Crop" value={d.primary_crop} />
            <InfoBlock label="NDVI Value" value={d.ndvi?.toFixed(2)} color={sc} mono />
            <InfoBlock label="Confidence" value={`${d.confidence}%`} mono />
            <InfoBlock label="Damage" value={`${d.damage_pct}% farmland`} color={sc} />
          </div>

          <div className="border-t border-slate-700/40" />

          <div className="grid grid-cols-3 gap-3">
            <InfoBlock label="Total Farmland" value={`${d.total_farmland_ha?.toLocaleString()} ha`} small />
            <InfoBlock label="Surveyed" value={`${d.surveyed_ha?.toLocaleString()} ha`} small />
            <InfoBlock label="Affected" value={`${d.affected_ha?.toLocaleString()} ha`} small color={sc} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <InfoBlock label="Soil Moisture" value={`${d.soil_moisture_pct}%`} small />
            <InfoBlock label="Last Rainfall" value={`${d.last_rainfall_mm} mm`} small />
            <InfoBlock label="Tiles Processed" value={d.tiles_processed} small mono />
          </div>

          {d.secondary_crop && (
            <div className="grid grid-cols-2 gap-3">
              <InfoBlock label="Secondary Crop" value={d.secondary_crop} small />
              <InfoBlock label="Disaster Type" value={d.disaster_type === 'none' ? 'None' : d.disaster_type.toUpperCase()} small />
            </div>
          )}

          {/* Cost Comparison */}
          <div className="border-t border-slate-700/40" />
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">💰 Survey Cost Comparison</p>
            <div className="grid grid-cols-3 gap-3">
              <InfoBlock label="Surveyor Cost" value={formatINR(tradCost)} color="text-red-400" small />
              <InfoBlock label="Satellite Cost" value={formatINR(satCost)} color="text-emerald-400" small />
              <InfoBlock label="Money Saved" value={formatINR(saved)} color="text-indigo-400" small />
            </div>
            <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
              <span>⏱ Surveyor: <span className="text-red-400">21 days</span></span>
              <span>→</span>
              <span>Satellite: <span className="text-emerald-400 font-bold">4 min</span></span>
            </div>
          </div>

          {/* Coordinates */}
          <div className="border-t border-slate-700/40" />
          <div className="flex items-center justify-between">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Coordinates</p>
            <p className="text-xs font-mono text-emerald-400">{d.lat}°N, {d.lng}°E</p>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-slate-700/50 bg-slate-800/30">
          <button onClick={onClose} className="w-full py-2.5 rounded-xl bg-slate-700/60 hover:bg-slate-600/70 text-sm font-medium text-slate-300 transition-colors">Close</button>
        </div>
      </div>
    </div>
  )
}
