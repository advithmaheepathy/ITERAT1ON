import React, { useState, useEffect, useCallback } from 'react'
import { fetchDashboard, simulatePass } from './api'
import MetricCard from './components/MetricCard'
import DistrictGrid from './components/DistrictGrid'
import Modal from './components/Modal'
import SatelliteMap from './components/SatelliteMap'
import BurnMap from './components/BurnMap'

function timeAgo(isoString) {
  if (!isoString) return '—'
  const diff = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min${mins > 1 ? 's' : ''} ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs} hr${hrs > 1 ? 's' : ''} ago`
}

function formatINR(val) {
  if (val >= 10000000) return `₹${(val / 10000000).toFixed(1)} Cr`
  if (val >= 100000) return `₹${(val / 100000).toFixed(1)} L`
  return `₹${val.toLocaleString('en-IN')}`
}

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [selectedDistrict, setSelectedDistrict] = useState(null)
  const [focusedDistrict, setFocusedDistrict] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [tick, setTick] = useState(0)

  const loadDashboard = useCallback(async () => {
    try {
      const d = await fetchDashboard()
      setData(d)
      setLastUpdated(new Date().toISOString())
    } catch (err) {
      console.error('Failed to load dashboard:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadDashboard() }, [loadDashboard])
  useEffect(() => {
    const interval = setInterval(() => setTick(t => t + 1), 30000)
    return () => clearInterval(interval)
  }, [])

  const handleScan = async () => {
    setScanning(true)
    try {
      await simulatePass()
      await new Promise(r => setTimeout(r, 2000))
      await loadDashboard()
    } catch (err) {
      console.error('Scan failed:', err)
    } finally {
      setScanning(false)
    }
  }

  const handleDistrictSelect = (district) => {
    setFocusedDistrict(district)
    setSelectedDistrict(district)
  }

  const handleMapSelect = (district) => {
    setFocusedDistrict(district)
    if (district) setSelectedDistrict(district)
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="spinner mx-auto mb-4" style={{ width: 40, height: 40, borderWidth: 3 }} />
          <p className="text-sm text-slate-400">Connecting to ground station...</p>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-red-400">Failed to connect to AgriSat-7 ground station</p>
      </div>
    )
  }

  const { satellite_hardware: hw, totals, districts, survey_economics: eco } = data

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
                {hw.name}
                <span className="ml-2 text-[10px] font-medium text-emerald-400 bg-emerald-500/15 px-2 py-0.5 rounded-full border border-emerald-500/30">
                  {hw.status}
                </span>
              </h1>
              <p className="text-[10px] text-slate-500">
                {hw.orbit} · {hw.ai_model}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden sm:block text-right">
              <p className="text-[10px] text-slate-500">Last updated</p>
              <p className="text-xs text-slate-400 font-mono">{timeAgo(lastUpdated)}</p>
            </div>
            <button onClick={handleScan} disabled={scanning}
              className="scan-button px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all duration-300 flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed">
              {scanning ? (
                <><div className="spinner" /><span>Scanning...</span></>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 3.75H6A2.25 2.25 0 003.75 6v1.5M16.5 3.75H18A2.25 2.25 0 0120.25 6v1.5M20.25 16.5V18A2.25 2.25 0 0118 20.25h-1.5M3.75 16.5V18A2.25 2.25 0 006 20.25h1.5M12 8.25v7.5M8.25 12h7.5" />
                  </svg>
                  <span>Run Satellite Survey</span>
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* ═══════ Main Content ═══════ */}
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6 space-y-6">
        {scanning && (
          <div className="glass-card p-4 flex items-center gap-3 border-indigo-500/30 bg-indigo-500/5 animate-fade-in">
            <div className="spinner" style={{ borderTopColor: '#818cf8' }} />
            <div>
              <p className="text-sm font-medium text-indigo-300">Satellite survey in progress</p>
              <p className="text-xs text-slate-500">Onboard AI scanning farmland — identifying crop damage via spectral analysis...</p>
            </div>
          </div>
        )}

        {/* ─── Top Metric Cards ─── */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard type="tiles" title="Total Farmland Surveyed"
            value={`${(totals.total_surveyed_ha / 1000).toFixed(0)}K ha`}
            subtitle={`${totals.district_count} districts covered`} />
          <MetricCard type="alerts" title="Farmland Affected"
            value={`${(totals.total_affected_ha / 1000).toFixed(0)}K ha`}
            subtitle={`${totals.avg_damage_pct}% avg damage`} />
          <MetricCard type="data" title="Cost Saved vs Surveyors"
            value={formatINR(totals.cost_saved_inr)}
            subtitle={`Surveyor: ${formatINR(totals.traditional_cost_inr)} → Satellite: ${formatINR(totals.satellite_cost_inr)}`} />
          <MetricCard type="confidence" title="Time Saved"
            value={`${totals.traditional_time_days - Math.ceil(totals.satellite_time_min / 60 / 24)} days`}
            subtitle={`Surveyor: ${totals.traditional_time_days} days → Satellite: ${totals.satellite_time_min} min`} />
        </section>

        {/* ─── Satellite Map (HERO) ─── */}
        <section>
          <SatelliteMap
            districts={districts}
            focusedDistrict={focusedDistrict}
            onSelectDistrict={handleMapSelect}
          />
        </section>

        {/* ─── District Grid + Hardware Panel ─── */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <DistrictGrid districts={districts} onSelect={handleDistrictSelect} />
          </div>
          <div className="lg:col-span-1 space-y-4">
            {/* Hardware Specs */}
            <div className="glass-card p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300 mb-4">
                🛰️ Satellite Hardware
              </h2>
              <div className="space-y-2.5">
                <HWRow label="Processor" value={hw.processor} />
                <HWRow label="AI Model" value={hw.ai_model} />
                <HWRow label="Spectral Bands" value={hw.spectral_bands.join(', ')} />
                <HWRow label="Resolution" value={`${hw.spatial_resolution_m}m/px`} />
                <HWRow label="Coverage Rate" value={`${hw.coverage_rate_ha_per_min.toLocaleString()} ha/min`} />
                <HWRow label="Swath Width" value={`${hw.swath_width_km} km`} />
                <HWRow label="Orbit" value={hw.orbit} />
                <HWRow label="Revisit" value={`Every ${hw.revisit_hours} hrs`} />
                <HWRow label="Crop ID Accuracy" value={`${hw.crop_id_accuracy_pct}%`} />
                <HWRow label="Inference Speed" value={`${hw.inference_speed_tiles_per_sec} tiles/sec`} />
              </div>
            </div>

            {/* Survey Economics */}
            <div className="glass-card p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300 mb-4">
                💰 Cost Comparison
              </h2>
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-400">Traditional Surveyor</span>
                  <span className="text-sm font-bold text-red-400 font-mono">₹{eco.traditional_cost_per_ha}/ha</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-400">Satellite Survey</span>
                  <span className="text-sm font-bold text-emerald-400 font-mono">₹{eco.satellite_cost_per_ha}/ha</span>
                </div>
                <div className="border-t border-slate-700/40 pt-2 flex justify-between items-center">
                  <span className="text-xs text-slate-400">Savings per hectare</span>
                  <span className="text-sm font-bold text-indigo-400 font-mono">
                    ₹{eco.traditional_cost_per_ha - eco.satellite_cost_per_ha}/ha
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-400">Time per district</span>
                  <span className="text-xs text-slate-300">
                    <span className="text-red-400 line-through">{eco.traditional_days_per_district} days</span>
                    {' → '}
                    <span className="text-emerald-400 font-bold">{eco.satellite_minutes_per_district} min</span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ─── Burn Severity Map Section ─── */}
        <section className="mt-8">
          <BurnMap map={data.burn_map} />
        </section>

        <footer className="text-center py-6 border-t border-slate-800/40">
          <p className="text-[11px] text-slate-600">
            AgriSat-7 Ground Station · Satellite Crop Insurance Survey System · {new Date().getFullYear()}
          </p>
        </footer>
      </main>

      {selectedDistrict && (
        <Modal district={selectedDistrict} onClose={() => setSelectedDistrict(null)} />
      )}
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
