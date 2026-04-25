import React from 'react'

const stressConfig = {
  high: {
    bg: 'bg-red-500/20',
    border: 'border-red-500/50',
    text: 'text-red-400',
    label: 'HIGH STRESS',
    glow: 'glow-red animate-pulse-glow',
    dot: 'bg-red-500',
  },
  medium: {
    bg: 'bg-yellow-500/15',
    border: 'border-yellow-500/40',
    text: 'text-yellow-400',
    label: 'MODERATE',
    glow: 'glow-yellow',
    dot: 'bg-yellow-500',
  },
  low: {
    bg: 'bg-emerald-500/15',
    border: 'border-emerald-500/40',
    text: 'text-emerald-400',
    label: 'HEALTHY',
    glow: 'glow-green',
    dot: 'bg-emerald-500',
  },
  cloudy: {
    bg: 'bg-blue-500/15',
    border: 'border-blue-500/40',
    text: 'text-blue-400',
    label: 'CLOUD COVER',
    glow: 'glow-blue',
    dot: 'bg-blue-500',
  },
}

export default function DistrictGrid({ districts, onSelect }) {
  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          District Heatmap
        </h2>
        <span className="text-xs text-slate-500 font-mono">{districts.length} regions</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {districts.map((d) => {
          const cfg = stressConfig[d.stress_level] || stressConfig.low
          return (
            <button
              key={d.id}
              onClick={() => onSelect(d)}
              className={`
                relative group p-4 rounded-xl border transition-all duration-300
                ${cfg.bg} ${cfg.border}
                hover:scale-[1.03] hover:brightness-110
                ${d.stress_level === 'high' ? cfg.glow : ''}
                text-left cursor-pointer
              `}
            >
              {/* Status dot */}
              <div className={`absolute top-2.5 right-2.5 w-2 h-2 rounded-full ${cfg.dot} ${d.stress_level === 'high' ? 'animate-pulse' : ''}`} />

              {/* District name */}
              <p className="text-xs font-semibold text-white truncate mb-1 pr-4">
                {d.name}
              </p>

              {/* Crop */}
              <p className="text-[10px] text-slate-400 truncate mb-2">
                {d.crop}
              </p>

              {/* NDVI */}
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">NDVI</span>
                <span className={`text-sm font-bold font-mono ${cfg.text}`}>
                  {d.ndvi.toFixed(2)}
                </span>
              </div>

              {/* Confidence bar */}
              <div className="mt-2 h-1 bg-slate-700/50 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    d.confidence > 85 ? 'bg-emerald-500' : d.confidence > 70 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${d.confidence}%` }}
                />
              </div>

              {/* Status label */}
              <p className={`text-[9px] font-bold uppercase tracking-widest mt-2 ${cfg.text}`}>
                {cfg.label}
              </p>
            </button>
          )
        })}
      </div>
    </div>
  )
}
