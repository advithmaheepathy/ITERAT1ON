import React from 'react'

// Map damage_pct to a stress level for visual styling
function getStressLevel(d) {
  if (d.damage_pct >= 30) return 'high'
  if (d.damage_pct >= 15) return 'medium'
  return 'low'
}

const stressConfig = {
  high: {
    bg: 'bg-red-500/20',
    border: 'border-red-500/50',
    text: 'text-red-400',
    label: 'CRITICAL',
    glow: 'glow-red animate-pulse-glow',
    dot: 'bg-red-500',
  },
  medium: {
    bg: 'bg-yellow-500/15',
    border: 'border-yellow-500/40',
    text: 'text-yellow-400',
    label: 'WARNING',
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
}

export default function DistrictGrid({ districts, onSelect }) {
  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          District Survey Report
        </h2>
        <span className="text-xs text-slate-500 font-mono">{districts.length} regions</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {districts.map((d) => {
          const level = getStressLevel(d)
          const cfg = stressConfig[level]
          return (
            <button
              key={d.id}
              onClick={() => onSelect(d)}
              className={`
                relative group p-4 rounded-xl border transition-all duration-300
                ${cfg.bg} ${cfg.border}
                hover:scale-[1.03] hover:brightness-110
                ${level === 'high' ? cfg.glow : ''}
                text-left cursor-pointer
              `}
            >
              {/* Status dot */}
              <div className={`absolute top-2.5 right-2.5 w-2 h-2 rounded-full ${cfg.dot} ${level === 'high' ? 'animate-pulse' : ''}`} />

              {/* District name */}
              <p className="text-xs font-semibold text-white truncate mb-0.5 pr-4">
                {d.name}
              </p>
              <p className="text-[10px] text-slate-500 truncate mb-1">{d.state}</p>

              {/* Crop */}
              <p className="text-[10px] text-slate-400 truncate mb-2">
                {d.primary_crop}
              </p>

              {/* Damage % */}
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">Damage</span>
                <span className={`text-sm font-bold font-mono ${cfg.text}`}>
                  {d.damage_pct}%
                </span>
              </div>

              {/* Affected area */}
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">Affected</span>
                <span className="text-[10px] font-mono text-slate-400">
                  {d.affected_ha?.toLocaleString()} ha
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
                {d.disaster_type === 'none' ? cfg.label : d.disaster_type.toUpperCase()}
              </p>
            </button>
          )
        })}
      </div>
    </div>
  )
}
