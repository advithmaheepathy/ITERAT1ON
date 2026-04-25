import React, { useState, useEffect, useCallback } from 'react'
import { fetchDashboard, simulatePass } from './api'
import MetricCard from './components/MetricCard'
import DistrictGrid from './components/DistrictGrid'
import AlertFeed from './components/AlertFeed'
import NDVITrend from './components/NDVITrend'
import Modal from './components/Modal'
import SatelliteMap from './components/SatelliteMap'

function timeAgo(isoString) {
  if (!isoString) return '—'
  const diff = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min${mins > 1 ? 's' : ''} ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs} hr${hrs > 1 ? 's' : ''} ago`
}

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [selectedDistrict, setSelectedDistrict] = useState(null)   // modal
  const [focusedDistrict, setFocusedDistrict] = useState(null)     // map focus
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

  useEffect(() => {
    loadDashboard()
  }, [loadDashboard])

  // Update "time ago" every 30 seconds
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

  // When a district tile is clicked: focus map + open modal
  const handleDistrictSelect = (district) => {
    setFocusedDistrict(district)
    setSelectedDistrict(district)
  }

  // When a district is clicked on the map: focus + open modal
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

  const { satellite, summary, districts, alerts, ndvi_overview } = data

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
                {satellite.name}
                <span className="ml-2 text-[10px] font-medium text-emerald-400 bg-emerald-500/15 px-2 py-0.5 rounded-full border border-emerald-500/30">
                  {satellite.status}
                </span>
              </h1>
              <p className="text-[10px] text-slate-500">
                {satellite.orbit} · {satellite.altitude_km} km · Pass #{satellite.passes_today}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden sm:block text-right">
              <p className="text-[10px] text-slate-500">Last updated</p>
              <p className="text-xs text-slate-400 font-mono">{timeAgo(lastUpdated)}</p>
            </div>

            <button
              onClick={handleScan}
              disabled={scanning}
              className="scan-button px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all duration-300 flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {scanning ? (
                <>
                  <div className="spinner" />
                  <span>Scanning...</span>
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 3.75H6A2.25 2.25 0 003.75 6v1.5M16.5 3.75H18A2.25 2.25 0 0120.25 6v1.5M20.25 16.5V18A2.25 2.25 0 0118 20.25h-1.5M3.75 16.5V18A2.25 2.25 0 006 20.25h1.5M12 8.25v7.5M8.25 12h7.5" />
                  </svg>
                  <span>Run Satellite Scan</span>
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* ═══════ Main Content ═══════ */}
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Scanning overlay */}
        {scanning && (
          <div className="glass-card p-4 flex items-center gap-3 border-indigo-500/30 bg-indigo-500/5 animate-fade-in">
            <div className="spinner" style={{ borderTopColor: '#818cf8' }} />
            <div>
              <p className="text-sm font-medium text-indigo-300">Satellite pass in progress</p>
              <p className="text-xs text-slate-500">Onboard AI processing spectral bands — compressing insights for downlink...</p>
            </div>
          </div>
        )}

        {/* ─── Top Metric Cards ─── */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard type="tiles" title="Tiles Scanned Today" value={summary.tiles_scanned.toLocaleString()} subtitle={`${summary.coverage_percent}% coverage area`} />
          <MetricCard type="alerts" title="Stress Alerts Fired" value={summary.stress_alerts} subtitle="Active warnings & critical" />
          <MetricCard type="data" title="Data Downlinked" value={`${summary.data_downlinked_kb} KB`} subtitle={`${summary.raw_data_saved_gb} GB raw saved onboard`} />
          <MetricCard type="confidence" title="Avg Confidence" value={`${summary.average_confidence}%`} subtitle="Onboard inference accuracy" />
        </section>

        {/* ─── Satellite Map (HERO) ─── */}
        <section>
          <SatelliteMap
            districts={districts}
            focusedDistrict={focusedDistrict}
            onSelectDistrict={handleMapSelect}
          />
        </section>

        {/* ─── District Grid + Alert Feed ─── */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <DistrictGrid districts={districts} onSelect={handleDistrictSelect} />
          </div>
          <div className="lg:col-span-1">
            <AlertFeed alerts={alerts} />
          </div>
        </section>

        {/* ─── NDVI Trend ─── */}
        <section>
          <NDVITrend ndviOverview={ndvi_overview} />
        </section>

        {/* ─── Footer ─── */}
        <footer className="text-center py-6 border-t border-slate-800/40">
          <p className="text-[11px] text-slate-600">
            AgriSat-7 Ground Station · Simulated Onboard AI Crop Intelligence · {new Date().getFullYear()}
          </p>
        </footer>
      </main>

      {/* ─── Modal ─── */}
      {selectedDistrict && (
        <Modal district={selectedDistrict} onClose={() => setSelectedDistrict(null)} />
      )}
    </div>
  )
}
