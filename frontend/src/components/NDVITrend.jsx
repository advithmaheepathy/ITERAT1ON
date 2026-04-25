import React from 'react'

function getBarColor(value) {
  if (value >= 0.7) return 'bg-emerald-500'
  if (value >= 0.5) return 'bg-yellow-500'
  return 'bg-red-500'
}

function getLabel(value) {
  if (value >= 0.7) return { text: 'Healthy', color: 'text-emerald-400' }
  if (value >= 0.5) return { text: 'Moderate', color: 'text-yellow-400' }
  return { text: 'Stress', color: 'text-red-400' }
}

export default function NDVITrend({ ndviOverview }) {
  const labels = ndviOverview?.labels || ['4 Weeks Ago', '2 Weeks Ago', 'This Week']
  const values = ndviOverview?.values || [0, 0, 0]

  // Determine overall trend
  const trend = values[2] > values[0] ? 'improving' : values[2] < values[0] ? 'declining' : 'stable'
  const trendConfig = {
    improving: { icon: '↗', text: 'Improving', color: 'text-emerald-400' },
    declining: { icon: '↘', text: 'Declining', color: 'text-red-400' },
    stable: { icon: '→', text: 'Stable', color: 'text-yellow-400' },
  }

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          NDVI Trend Overview
        </h2>
        <span className={`text-xs font-semibold flex items-center gap-1 ${trendConfig[trend].color}`}>
          <span className="text-base">{trendConfig[trend].icon}</span>
          {trendConfig[trend].text}
        </span>
      </div>

      <div className="space-y-4">
        {labels.map((label, i) => {
          const val = values[i]
          const barColor = getBarColor(val)
          const status = getLabel(val)
          const widthPercent = Math.max(8, (val / 1.0) * 100)

          return (
            <div key={label} className="group">
              {/* Label row */}
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-slate-400">{label}</span>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-medium ${status.color}`}>{status.text}</span>
                  <span className="text-sm font-bold font-mono text-white">{val.toFixed(2)}</span>
                </div>
              </div>

              {/* Bar */}
              <div className="h-3 bg-slate-700/40 rounded-full overflow-hidden">
                <div
                  className={`ndvi-bar h-full ${barColor}`}
                  style={{
                    width: `${widthPercent}%`,
                    opacity: i === 2 ? 1 : 0.7,
                    boxShadow: i === 2 ? `0 0 12px ${val >= 0.7 ? 'rgba(34,197,94,0.4)' : val >= 0.5 ? 'rgba(234,179,8,0.4)' : 'rgba(239,68,68,0.4)'}` : 'none',
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-5 pt-4 border-t border-slate-700/40">
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
          <span className="text-[10px] text-slate-500">≥ 0.70 Healthy</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-yellow-500" />
          <span className="text-[10px] text-slate-500">0.50 – 0.69</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500" />
          <span className="text-[10px] text-slate-500">&lt; 0.50 Stress</span>
        </div>
      </div>
    </div>
  )
}
