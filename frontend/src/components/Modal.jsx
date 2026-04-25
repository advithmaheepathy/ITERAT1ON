import React from 'react'

const stressColors = {
  high: 'text-red-400',
  medium: 'text-yellow-400',
  low: 'text-emerald-400',
  cloudy: 'text-blue-400',
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
  if (level === 'cloudy') return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
  return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
}

function getDot(level) {
  if (level === 'high') return 'bg-red-400'
  if (level === 'medium') return 'bg-yellow-400'
  if (level === 'cloudy') return 'bg-blue-400'
  return 'bg-emerald-400'
}

function getLabel(level) {
  if (level === 'low') return 'Healthy'
  if (level === 'cloudy') return 'Cloud Cover'
  return level + ' stress'
}

export default function Modal({ district, onClose }) {
  if (!district) return null
  const sc = stressColors[district.stress_level] || 'text-slate-400'

  return (
    <div className="modal-overlay animate-fade-in" onClick={onClose}>
      <div className="glass-card w-full max-w-lg mx-4 p-0 animate-slide-up overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="relative px-6 py-5 border-b border-slate-700/50">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-lg font-bold text-white">{district.name}</h2>
              <p className="text-xs text-slate-400 mt-0.5">{district.state}</p>
            </div>
            <button onClick={onClose} className="w-8 h-8 rounded-lg bg-slate-700/50 hover:bg-slate-600/60 flex items-center justify-center transition-colors">
              <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className={`mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border ${getBadge(district.stress_level)}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${getDot(district.stress_level)}`} />
            {getLabel(district.stress_level)}
          </div>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <InfoBlock label="Crop Type" value={district.crop} />
            <InfoBlock label="NDVI Value" value={district.ndvi.toFixed(2)} color={sc} mono />
            <InfoBlock label="Confidence" value={`${district.confidence}%`} mono />
            <InfoBlock label="Affected Area" value={`${district.affected_hectares.toLocaleString()} ha`} />
          </div>
          <div className="border-t border-slate-700/40" />
          <div className="grid grid-cols-3 gap-3">
            <InfoBlock label="Total Area" value={`${district.total_hectares.toLocaleString()} ha`} small />
            <InfoBlock label="Soil Moisture" value={`${district.soil_moisture}%`} small />
            <InfoBlock label="Cloud Cover" value={`${district.cloud_cover}%`} small />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <InfoBlock label="Last Rainfall" value={`${district.last_rainfall_mm} mm`} small />
            <InfoBlock label="Tiles Scanned" value={district.tiles_scanned} small mono />
            <InfoBlock label="Issues" value={district.issues?.length > 0 ? district.issues.join(', ') : 'None'} small />
          </div>

          {district.ndvi_trend && (
            <>
              <div className="border-t border-slate-700/40" />
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">NDVI Micro-Trend</p>
                <div className="flex items-end gap-2 h-12">
                  {district.ndvi_trend.map((val, i) => {
                    const height = Math.max(12, (val / 1.0) * 100)
                    const color = val >= 0.7 ? 'bg-emerald-500' : val >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'
                    return (
                      <div key={i} className="flex-1 flex flex-col items-center gap-1">
                        <span className="text-[9px] font-mono text-slate-400">{val.toFixed(2)}</span>
                        <div className={`w-full rounded-t-md transition-all duration-500 ${color}`} style={{ height: `${height}%` }} />
                      </div>
                    )
                  })}
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-[8px] text-slate-600">4w ago</span>
                  <span className="text-[8px] text-slate-600">2w ago</span>
                  <span className="text-[8px] text-slate-600">Now</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-slate-700/50 bg-slate-800/30">
          <button onClick={onClose} className="w-full py-2.5 rounded-xl bg-slate-700/60 hover:bg-slate-600/70 text-sm font-medium text-slate-300 transition-colors">Close</button>
        </div>
      </div>
    </div>
  )
}
