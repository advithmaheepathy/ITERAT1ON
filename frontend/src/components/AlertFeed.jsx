import React from 'react'

const typeIcons = {
  drought: '🔥',
  flood: '🌊',
  pest: '🐛',
}

const severityBadge = {
  critical: 'badge-critical',
  warning: 'badge-warning',
  info: 'badge-info',
}

function timeAgo(timestamp) {
  const diff = Date.now() - new Date(timestamp).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function AlertFeed({ alerts }) {
  return (
    <div className="glass-card p-5 flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Live Alert Feed
        </h2>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <span className="text-[10px] text-red-400 font-medium uppercase tracking-wide">Live</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2 max-h-[400px] pr-1">
        {alerts.map((alert, i) => (
          <div
            key={alert.id + '-' + i}
            className="p-3 rounded-xl bg-slate-800/60 border border-slate-700/40 hover:border-slate-600/60 transition-all duration-200 animate-slide-up"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            {/* Top row */}
            <div className="flex items-start justify-between mb-1.5">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-base flex-shrink-0">{typeIcons[alert.type] || '⚠️'}</span>
                <span className="text-xs font-semibold text-white truncate">{alert.district}</span>
              </div>
              <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full flex-shrink-0 ${severityBadge[alert.severity] || severityBadge.info}`}>
                {alert.severity}
              </span>
            </div>

            {/* Issue */}
            <p className="text-[11px] text-slate-300 mb-2 leading-relaxed pl-6">
              {alert.issue}
            </p>

            {/* Meta row */}
            <div className="flex items-center gap-3 pl-6 text-[10px] text-slate-500">
              <span>{alert.crop}</span>
              <span>•</span>
              <span>{alert.hectares.toLocaleString()} ha</span>
              <span>•</span>
              <span className="font-mono">{alert.confidence}%</span>
              <span className="ml-auto text-slate-600">{timeAgo(alert.timestamp)}</span>
            </div>
          </div>
        ))}

        {alerts.length === 0 && (
          <div className="text-center py-8 text-slate-500 text-sm">
            No active alerts — all regions nominal
          </div>
        )}
      </div>
    </div>
  )
}
