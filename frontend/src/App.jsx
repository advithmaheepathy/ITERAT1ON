import React, { useState } from 'react'
import { analyzeAOI } from './api'
import AOISelector from './components/AOISelector'
import ApiServicesModal from './components/ApiServicesModal'


export default function App() {
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisResult, setAnalysisResult] = useState(null)
  const [showApiModal, setShowApiModal] = useState(false)
  const [lastPayload, setLastPayload] = useState(null)

  const handleAnalyze = async (payload) => {
    setAnalyzing(true)
    setAnalysisResult(null)
    setLastPayload(payload)
    try {
      const result = await analyzeAOI(payload)
      setAnalysisResult({ ...result, displayConfig: payload.customOutputs })
    } catch (err) {
      console.error('Analysis failed:', err)
      setAnalysisResult({ status: 'error', message: err.message })
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <div className="min-h-screen bg-gh-bg relative overflow-x-hidden">
      <div className="relative z-10 min-h-screen flex flex-col">
        {/* ═══════ Header ═══════ */}
        <header className="sticky top-0 z-40 bg-gh-panel border-b border-gh-border shadow-sm">
          <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded bg-[#1c2128] border border-gh-border flex items-center justify-center">
                <svg className="w-6 h-6 text-gh-text" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
                </svg>
              </div>
              <div>
                <h1 className="text-lg font-sans font-bold text-gh-text tracking-widest uppercase flex items-center">
                  AgriSat-7 <span className="text-gh-muted ml-1">Cmd_Center</span>
                  <span className="ml-3 text-[10px] font-mono font-medium text-gh-success bg-[#1c2128] px-2 py-0.5 rounded-sm border border-gh-border flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-gh-success"></span>
                    SYS_ONLINE
                  </span>
                </h1>
                <p className="text-[10px] text-gh-muted font-mono tracking-widest mt-0.5">
                  OP_MODE: LEO_SURVEY · MODEL: VISION_TRANSFORMER_V2
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowApiModal(true)}
              id="api-services-btn"
              className="flex items-center gap-2 px-4 py-2 rounded text-xs font-sans font-bold tracking-wider text-gh-text transition-colors border border-gh-border hover:border-gh-muted hover:bg-[#1c2128] uppercase"
            >
              <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
              </svg>
              <span>Uplink API</span>
            </button>
          </div>
        </header>

        {/* ═══════ Main Content ═══════ */}
        <main className="max-w-[1600px] w-full mx-auto px-4 sm:px-6 py-6 flex-1 flex flex-col lg:flex-row gap-6">
          
          {/* Telemetry Sidebar */}
          <aside className="w-full lg:w-[360px] shrink-0">
            <TelemetryPanel isAnalyzing={analyzing} payload={lastPayload} />
          </aside>

          {/* Core Workspace */}
          <div className="flex-1 space-y-6 min-w-0">
            <section>
              <AOISelector onAnalyze={handleAnalyze} isAnalyzing={analyzing} />
            </section>

            {/* ─── Analysis Result ─── */}
            {analysisResult && analysisResult.status === 'analysis_complete' && (
              <section className="animate-fade-in">
                <AnalysisResultPanel result={analysisResult} onClose={() => setAnalysisResult(null)} />
              </section>
            )}
          </div>
        </main>

        <footer className="text-center py-4 border-t border-gh-border mt-auto relative z-10 bg-gh-bg">
          <p className="text-[10px] font-mono text-gh-muted tracking-widest uppercase">
            AgriSat-7 Ground Station · SECURE UPLINK ESTABLISHED · {new Date().getFullYear()}
          </p>
        </footer>

        {/* ═══════ API Services Modal ═══════ */}
        {showApiModal && (
          <ApiServicesModal onClose={() => setShowApiModal(false)} />
        )}
      </div>
    </div>
  )
}

function HWRow({ label, value }) {
  return (
    <div className="flex justify-between items-start gap-2">
      <span className="text-[10px] uppercase tracking-wider text-gh-muted shrink-0">{label}</span>
      <span className="text-xs text-gh-text font-mono text-right">{value}</span>
    </div>
  )
}

function AnalysisResultPanel({ result, onClose }) {
  const { aoi, result: r, analysis } = result

  // Render Custom Analysis Results
  if (analysis === 'custom') {
    const customMetrics = r.custom_metrics || {}
    
    return (
      <div className="flat-panel p-5 animate-fade-in">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded bg-[#1c2128] border border-gh-border flex items-center justify-center">
              <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
              </svg>
            </div>
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gh-text">
              Custom Parameters Result
            </h2>
            <span className="badge-success text-[10px] font-bold uppercase px-2 py-0.5 rounded-sm">
              Complete
            </span>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded bg-[#1c2128] border border-gh-border hover:border-gh-muted flex items-center justify-center transition-colors">
            <svg className="w-3.5 h-3.5 text-gh-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Custom Summary Section */}
        {r.summary && r.summary.overall_condition && (
          <div className="mb-6 p-4 rounded bg-[#1c2128] border border-gh-border">
            <div className="flex items-center justify-between mb-3">
               <h3 className="text-xs font-bold text-gh-text uppercase tracking-widest">Executive Summary</h3>
               <span className="text-[10px] uppercase font-bold px-2 py-1 rounded bg-gh-bg border border-gh-border text-gh-accent">
                 Confidence: {r.summary.confidence_score}%
               </span>
            </div>
            <p className="text-sm text-gh-text mb-3">
              Overall Condition: <span className="font-bold text-gh-warning capitalize">{r.summary.overall_condition}</span>
            </p>
            <div className="space-y-1">
              {r.summary.key_findings?.map((finding, idx) => (
                <div key={idx} className="flex items-start gap-2">
                  <span className="text-gh-warning mt-0.5">•</span>
                  <span className="text-xs text-gh-text">{finding}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Detailed Metrics Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Object.entries(customMetrics).map(([key, data]) => {
            const { interpretation, ...stats } = data
            return (
              <div key={key} className="p-4 rounded bg-[#1c2128] border border-gh-border hover:border-gh-muted transition-colors flex flex-col h-full">
                <p className="text-xs uppercase tracking-widest text-gh-accent font-bold mb-3 border-b border-gh-border pb-2">{key}</p>
                
                <div className="space-y-2 mb-4 flex-grow">
                  {Object.entries(stats).map(([statKey, statVal]) => (
                    <div key={statKey} className="flex justify-between items-center bg-gh-bg p-2 rounded border border-gh-border">
                      <span className="text-[10px] text-gh-muted uppercase tracking-wider">{statKey.replace(/_/g, ' ')}</span>
                      <span className="text-xs font-bold text-gh-text font-mono">{typeof statVal === 'number' ? statVal.toLocaleString() : String(statVal)}</span>
                    </div>
                  ))}
                </div>
                
                {interpretation && (
                  <div className="mt-auto pt-3 border-t border-gh-border">
                    <p className="text-[10px] text-gh-warning font-semibold mb-1 uppercase tracking-wider">Interpretation</p>
                    <p className="text-[11px] text-gh-text leading-relaxed">{interpretation}</p>
                  </div>
                )}
              </div>
            )
          })}
          {Object.keys(customMetrics).length === 0 && (
            <div className="col-span-full py-8 text-center text-gh-muted text-sm">
              No parameters were selected for analysis.
            </div>
          )}
        </div>
      </div>
    )
  }

  // Standard Burn Detection Results
  const sev = r.summary?.severity_distribution || {}
  const sevBars = [
    { key: 'severe', label: 'Severe', color: 'bg-gh-danger', ...sev.severe },
    { key: 'moderate', label: 'Moderate', color: 'bg-[#ff7b72]', ...sev.moderate_severity },
    { key: 'low', label: 'Low', color: 'bg-gh-warning', ...sev.low_severity },
    { key: 'unburned', label: 'Unburned', color: 'bg-gh-success', ...sev.unburned },
  ]

  return (
    <div className="flat-panel p-5 animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded bg-[#1c2128] border border-gh-border flex items-center justify-center">
            <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z" />
            </svg>
          </div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gh-text">
            Burn Detection Result
          </h2>
          <span className="badge-success text-[10px] font-bold uppercase px-2 py-0.5 rounded-sm">
            Complete
          </span>
        </div>
        <button onClick={onClose} className="w-7 h-7 rounded bg-[#1c2128] border border-gh-border hover:border-gh-muted flex items-center justify-center transition-colors">
          <svg className="w-3.5 h-3.5 text-gh-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* AOI Info */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-gh-muted font-semibold">Area of Interest</p>
          <div className="space-y-1.5">
            <div className="p-2 rounded bg-[#1c2128] border border-gh-border">
              <p className="text-[9px] text-gh-muted uppercase">Area</p>
              <p className="text-sm font-bold text-gh-text font-mono">{aoi.area_ha?.toLocaleString()} ha</p>
            </div>
            <div className="p-2 rounded bg-[#1c2128] border border-gh-border">
              <p className="text-[9px] text-gh-muted uppercase">Center</p>
              <p className="text-xs font-mono text-gh-accent">{aoi.center?.[0]}°N, {aoi.center?.[1]}°E</p>
            </div>
            <div className="p-2 rounded bg-[#1c2128] border border-gh-border">
              <p className="text-[9px] text-gh-muted uppercase">Confidence</p>
              <p className="text-sm font-bold text-gh-text font-mono">{r.summary?.confidence}%</p>
            </div>
          </div>
        </div>

        {/* Burn Summary */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-gh-muted font-semibold">Burn Summary</p>
          <div className="grid grid-cols-2 gap-1.5">
            <div className="p-2 rounded bg-[#1c2128] border border-gh-border">
              <p className="text-[9px] text-gh-muted uppercase">Burned Area</p>
              <p className="text-sm font-bold text-gh-danger font-mono">{r.summary?.burned_area_ha?.toLocaleString()} ha</p>
            </div>
            <div className="p-2 rounded bg-[#1c2128] border border-gh-border">
              <p className="text-[9px] text-gh-muted uppercase">Burned %</p>
              <p className="text-sm font-bold text-gh-danger font-mono">{(r.summary?.burned_fraction * 100).toFixed(1)}%</p>
            </div>
            <div className="p-2 rounded bg-[#1c2128] border border-gh-border">
              <p className="text-[9px] text-gh-muted uppercase">dNBR Mean</p>
              <p className="text-xs font-mono text-gh-warning">{r.dnbr_statistics?.mean}</p>
            </div>
            <div className="p-2 rounded bg-[#1c2128] border border-gh-border">
              <p className="text-[9px] text-gh-muted uppercase">dNBR Max</p>
              <p className="text-xs font-mono text-gh-danger">{r.dnbr_statistics?.max}</p>
            </div>
          </div>
        </div>

        {/* Severity Distribution */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-gh-muted font-semibold">Severity Distribution</p>
          <div className="space-y-2">
            {sevBars.map(s => (
              <div key={s.key}>
                <div className="flex justify-between text-[10px] mb-0.5">
                  <span className="text-gh-muted">{s.label}</span>
                  <span className="text-gh-text font-mono">{s.pct || 0}% · {s.area_ha?.toLocaleString() || 0} ha</span>
                </div>
                <div className="h-2 bg-[#1c2128] rounded-sm overflow-hidden border border-gh-border">
                  <div className={`h-full transition-all duration-700 ${s.color}`} style={{ width: `${Math.max(s.pct || 0, 1)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function TelemetryPanel({ isAnalyzing, payload }) {
  return (
    <div className="flat-panel p-5 h-full min-h-[400px] flex flex-col gap-6">
      <div className="flex items-center justify-between border-b border-gh-border pb-3">
        <h2 className="text-sm font-sans font-bold uppercase tracking-widest text-gh-text flex items-center gap-2">
          <svg className="w-4 h-4 text-gh-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 15L12 18.75 15.75 15m-7.5-6L12 5.25 15.75 9" />
          </svg>
          Telemetry & Bandwidth
        </h2>
        <div className={`w-2 h-2 rounded-full ${isAnalyzing ? 'bg-gh-warning animate-pulse' : 'bg-gh-success'}`}></div>
      </div>

      <div className="flex-1 flex flex-col gap-5">
        {/* Connection Status */}
        <div className="bg-gh-bg rounded p-4 border border-gh-border">
          <p className="text-[10px] text-gh-muted uppercase font-sans tracking-widest mb-3">Sat-Link Bandwidth</p>
          <div className="flex justify-between items-end mb-1">
            <span className="text-xs text-gh-muted font-mono">Uplink (TX)</span>
            <span className="text-sm text-gh-success font-mono font-bold">24.8 Mbps</span>
          </div>
          <div className="w-full h-1.5 bg-[#1c2128] border border-gh-border rounded-sm mb-4 overflow-hidden">
            <div className={`h-full bg-gh-success transition-all duration-1000 ${isAnalyzing ? 'w-[85%]' : 'w-[20%]'}`}></div>
          </div>
          <div className="flex justify-between items-end mb-1">
            <span className="text-xs text-gh-muted font-mono">Downlink (RX)</span>
            <span className="text-sm text-gh-accent font-mono font-bold">{isAnalyzing ? '284.5' : '12.4'} Mbps</span>
          </div>
          <div className="w-full h-1.5 bg-[#1c2128] border border-gh-border rounded-sm overflow-hidden">
            <div className={`h-full bg-gh-accent transition-all duration-1000 ${isAnalyzing ? 'w-[95%]' : 'w-[10%]'}`}></div>
          </div>
        </div>

        {/* Orbit Info Grid */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-gh-bg rounded p-3 border border-gh-border">
            <p className="text-[9px] text-gh-muted font-sans uppercase tracking-widest">Orbit</p>
            <p className="text-xs text-gh-text font-mono mt-1">LEO_SYNC</p>
          </div>
          <div className="bg-gh-bg rounded p-3 border border-gh-border">
            <p className="text-[9px] text-gh-muted font-sans uppercase tracking-widest">Altitude</p>
            <p className="text-xs text-gh-text font-mono mt-1">540.2 km</p>
          </div>
          <div className="bg-gh-bg rounded p-3 border border-gh-border">
            <p className="text-[9px] text-gh-muted font-sans uppercase tracking-widest">Velocity</p>
            <p className="text-xs text-gh-text font-mono mt-1">7.66 km/s</p>
          </div>
          <div className="bg-gh-bg rounded p-3 border border-gh-border">
            <p className="text-[9px] text-gh-muted font-sans uppercase tracking-widest">Signal Latency</p>
            <p className="text-xs text-gh-warning font-mono mt-1">24 ms</p>
          </div>
        </div>

        {/* Animation Area (Replaced with Flat Status Terminal) */}
        <div className="flex-1 mt-2 min-h-[180px] bg-[#0D1117] rounded border border-[#30363D] relative flex flex-col p-4 font-mono text-[10px] uppercase text-gh-muted shadow-inner overflow-hidden">
          <div className="flex justify-between mb-4 border-b border-[#30363D] pb-2 shrink-0">
            <span>Terminal Uplink</span>
            <span className={isAnalyzing ? 'text-gh-warning' : 'text-gh-success'}>
              {isAnalyzing ? 'ACTIVE_SCAN' : 'STANDBY'}
            </span>
          </div>
          
          {isAnalyzing ? (
            <div className="flex-1 overflow-y-auto pr-1 custom-scrollbar text-gh-text gap-1 text-xs">
              <p>&gt; Establishing secure handshake...</p>
              <p>&gt; Connection established.</p>
              <p className="mt-2 text-gh-accent">&gt; TX_PAYLOAD_INIT:</p>
              <pre className="text-[10px] text-gh-accent whitespace-pre-wrap leading-tight mt-1 mb-2 border border-[#30363D] bg-[#161B22] p-2 rounded">
                {payload ? JSON.stringify(payload, null, 2) : '{...}'}
              </pre>
              <p>&gt; Requesting high-res optical data.</p>
              <p className="text-gh-accent animate-pulse">&gt; Receiving chunks (RX)...</p>
            </div>
          ) : (
            <div className="flex-1 flex flex-col justify-end text-gh-muted opacity-50">
              <p>&gt; Awaiting command...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
