import React, { useState } from 'react'
import { analyzeAOI } from './api'
import AOISelector from './components/AOISelector'


export default function App() {
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisResult, setAnalysisResult] = useState(null)

  const handleAnalyze = async (payload) => {
    setAnalyzing(true)
    setAnalysisResult(null)
    try {
      const result = await analyzeAOI(payload)
      setAnalysisResult(result)
    } catch (err) {
      console.error('Analysis failed:', err)
      setAnalysisResult({ status: 'error', message: err.message })
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <div className="min-h-screen scan-line-effect">
      {/* ═══════ Header ═══════ */}
      <header className="sticky top-0 z-40 bg-slate-950/80 backdrop-blur-xl border-b border-slate-800/60">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-bold text-white tracking-tight">
                AgriSat-7
                <span className="ml-2 text-[10px] font-medium text-emerald-400 bg-emerald-500/15 px-2 py-0.5 rounded-full border border-emerald-500/30">
                  Online
                </span>
              </h1>
              <p className="text-[10px] text-slate-500">
                LEO · VisionTransformer
              </p>
            </div>
          </div>
        </div>
      </header>

      {/* ═══════ Main Content ═══════ */}
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* ─── AOI Selector ─── */}
        <section>
          <AOISelector onAnalyze={handleAnalyze} isAnalyzing={analyzing} />
        </section>

        {/* ─── Analysis Result ─── */}
        {analysisResult && analysisResult.status === 'analysis_complete' && (
          <section className="animate-fade-in">
            <AnalysisResultPanel result={analysisResult} onClose={() => setAnalysisResult(null)} />
          </section>
        )}

        <footer className="text-center py-6 border-t border-slate-800/40 mt-12">
          <p className="text-[11px] text-slate-600">
            AgriSat-7 Ground Station · Satellite Crop Insurance Survey System · {new Date().getFullYear()}
          </p>
        </footer>
      </main>
    </div>
  )
}

function HWRow({ label, value }) {
  return (
    <div className="flex justify-between items-start gap-2">
      <span className="text-[10px] uppercase tracking-wider text-slate-500 shrink-0">{label}</span>
      <span className="text-xs text-slate-300 font-mono text-right">{value}</span>
    </div>
  )
}

function AnalysisResultPanel({ result, onClose }) {
  const { aoi, result: r } = result
  const sev = r.summary.severity_distribution

  const sevBars = [
    { key: 'severe', label: 'Severe', color: 'bg-red-500', ...sev.severe },
    { key: 'moderate', label: 'Moderate', color: 'bg-orange-500', ...sev.moderate_severity },
    { key: 'low', label: 'Low', color: 'bg-yellow-500', ...sev.low_severity },
    { key: 'unburned', label: 'Unburned', color: 'bg-emerald-500', ...sev.unburned },
  ]

  return (
    <div className="glass-card p-5 border-amber-500/30">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-red-500 to-orange-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z" />
            </svg>
          </div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
            Burn Detection Result
          </h2>
          <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
            Complete
          </span>
        </div>
        <button onClick={onClose} className="w-7 h-7 rounded-lg bg-slate-700/50 hover:bg-slate-600/60 flex items-center justify-center transition-colors">
          <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* AOI Info */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Area of Interest</p>
          <div className="space-y-1.5">
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <p className="text-[9px] text-slate-500 uppercase">Area</p>
              <p className="text-sm font-bold text-white font-mono">{aoi.area_ha.toLocaleString()} ha</p>
            </div>
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <p className="text-[9px] text-slate-500 uppercase">Center</p>
              <p className="text-xs font-mono text-emerald-400">{aoi.center[0]}°N, {aoi.center[1]}°E</p>
            </div>
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <p className="text-[9px] text-slate-500 uppercase">Confidence</p>
              <p className="text-sm font-bold text-indigo-400 font-mono">{r.summary.confidence}%</p>
            </div>
          </div>
        </div>

        {/* Burn Summary */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Burn Summary</p>
          <div className="grid grid-cols-2 gap-1.5">
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <p className="text-[9px] text-slate-500 uppercase">Burned Area</p>
              <p className="text-sm font-bold text-red-400 font-mono">{r.summary.burned_area_ha.toLocaleString()} ha</p>
            </div>
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <p className="text-[9px] text-slate-500 uppercase">Burned %</p>
              <p className="text-sm font-bold text-red-400 font-mono">{(r.summary.burned_fraction * 100).toFixed(1)}%</p>
            </div>
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <p className="text-[9px] text-slate-500 uppercase">dNBR Mean</p>
              <p className="text-xs font-mono text-amber-400">{r.dnbr_statistics.mean}</p>
            </div>
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <p className="text-[9px] text-slate-500 uppercase">dNBR Max</p>
              <p className="text-xs font-mono text-red-400">{r.dnbr_statistics.max}</p>
            </div>
          </div>
        </div>

        {/* Severity Distribution */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Severity Distribution</p>
          <div className="space-y-2">
            {sevBars.map(s => (
              <div key={s.key}>
                <div className="flex justify-between text-[10px] mb-0.5">
                  <span className="text-slate-400">{s.label}</span>
                  <span className="text-slate-300 font-mono">{s.pct}% · {s.area_ha.toLocaleString()} ha</span>
                </div>
                <div className="h-2 bg-slate-700/50 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full transition-all duration-700 ${s.color}`} style={{ width: `${Math.max(s.pct, 1)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
