import React, { useState, useRef, useEffect } from 'react'
import L from 'leaflet'
import { MapContainer, TileLayer, FeatureGroup, useMap } from 'react-leaflet'
import { EditControl } from 'react-leaflet-draw'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw/dist/leaflet.draw.css'

/**
 * Fixes the "rectangle stuck at edge" bug by adding Auto-Pan.
 * 
 * Leaflet-draw does not support panning the map while drawing a shape.
 * So if you drag to the edge of the map div, the rectangle gets stuck
 * and cannot extend further. This component detects when the mouse is near
 * the edge during a draw, and automatically pans the map.
 */
function AutoPanForwarder() {
  const map = useMap()

  useEffect(() => {
    let toolActive = false
    let isDragging = false
    let panInterval = null
    let lastEvent = null
    const container = map.getContainer()

    const onToolEnable = () => { toolActive = true }
    const onToolDisable = () => { 
      toolActive = false
      stopDrag()
    }

    const startDrag = () => {
      if (toolActive) isDragging = true
    }

    const stopDrag = () => {
      isDragging = false
      if (panInterval) {
        clearInterval(panInterval)
        panInterval = null
      }
    }

    const onMouseMove = (e) => {
      if (!isDragging) return
      lastEvent = e
      
      const rect = container.getBoundingClientRect()
      const edge = 40 // pixels from edge to trigger pan
      let dx = 0, dy = 0
      
      if (e.clientX < rect.left + edge) dx = -15
      else if (e.clientX > rect.right - edge) dx = 15
      
      if (e.clientY < rect.top + edge) dy = -15
      else if (e.clientY > rect.bottom - edge) dy = 15
      
      if (dx !== 0 || dy !== 0) {
        if (!panInterval) {
          panInterval = setInterval(() => {
            map.panBy([dx, dy], { animate: false })
            
            // Forward a synthetic mousemove so the drawing updates while panning
            if (lastEvent) {
              const x = lastEvent.clientX - rect.left
              const y = lastEvent.clientY - rect.top
              const cp = L.point(x, y)
              map.fire('mousemove', {
                latlng: map.containerPointToLatLng(cp),
                layerPoint: map.containerPointToLayerPoint(cp),
                containerPoint: cp,
                originalEvent: lastEvent
              })
            }
          }, 30)
        }
      } else {
        if (panInterval) {
          clearInterval(panInterval)
          panInterval = null
        }
      }
    }

    map.on('draw:drawstart', onToolEnable)
    map.on('draw:drawstop', onToolDisable)
    map.on('draw:created', onToolDisable)
    container.addEventListener('mousedown', startDrag, { capture: true })
    
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', stopDrag)

    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', stopDrag)
      map.off('draw:drawstart', onToolEnable)
      map.off('draw:drawstop', onToolDisable)
      map.off('draw:created', onToolDisable)
      container.removeEventListener('mousedown', startDrag, { capture: true })
      if (panInterval) clearInterval(panInterval)
    }
  }, [map])

  return null
}

export default function AOISelector({ onAnalyze, isAnalyzing }) {
  const [aoiCoords, setAoiCoords] = useState(null)
  const [drawnLayer, setDrawnLayer] = useState(null)
  const [showConfig, setShowConfig] = useState(false)
  const [customMode, setCustomMode] = useState(false)
  const [dates, setDates] = useState({ before: '', after: '' })
  const [outputs, setOutputs] = useState({
    showNdvi: false, showNdwi: false, showNbr: false, showLst: false,
    showLulc: false, showSmi: false, showCloud: false, showBiomass: false
  })
  const featureGroupRef = useRef(null)

  const handleCreated = (e) => {
    const { layer } = e
    // Remove previous rectangle if any
    if (featureGroupRef.current) {
      featureGroupRef.current.clearLayers()
      featureGroupRef.current.addLayer(layer)
    }
    setDrawnLayer(layer)

    const bounds = layer.getBounds()
    const coords = {
      top_left:     [parseFloat(bounds.getNorth().toFixed(6)), parseFloat(bounds.getWest().toFixed(6))],
      top_right:    [parseFloat(bounds.getNorth().toFixed(6)), parseFloat(bounds.getEast().toFixed(6))],
      bottom_left:  [parseFloat(bounds.getSouth().toFixed(6)), parseFloat(bounds.getWest().toFixed(6))],
      bottom_right: [parseFloat(bounds.getSouth().toFixed(6)), parseFloat(bounds.getEast().toFixed(6))],
    }
    setAoiCoords(coords)
    setShowConfig(false)
  }

  const handleDeleted = () => {
    setAoiCoords(null)
    setDrawnLayer(null)
    setShowConfig(false)
  }

  const handleEdited = (e) => {
    const layers = e.layers
    layers.eachLayer((layer) => {
      const bounds = layer.getBounds()
      setAoiCoords({
        top_left:     [parseFloat(bounds.getNorth().toFixed(6)), parseFloat(bounds.getWest().toFixed(6))],
        top_right:    [parseFloat(bounds.getNorth().toFixed(6)), parseFloat(bounds.getEast().toFixed(6))],
        bottom_left:  [parseFloat(bounds.getSouth().toFixed(6)), parseFloat(bounds.getWest().toFixed(6))],
        bottom_right: [parseFloat(bounds.getSouth().toFixed(6)), parseFloat(bounds.getEast().toFixed(6))],
      })
    })
  }

  const handleAnalyzeClick = () => {
    if (aoiCoords && onAnalyze) {
      onAnalyze({
        aoi: {
          type: 'bbox',
          coordinates: aoiCoords,
        },
        date_range: customMode ? null : dates,
        customOutputs: customMode ? outputs : null,
        analysis: customMode ? 'custom' : 'burn_detection',
      })
      setShowConfig(false)
    }
  }

  const areaHa = aoiCoords
    ? (() => {
        const latDiff = Math.abs(aoiCoords.top_left[0] - aoiCoords.bottom_left[0])
        const lonDiff = Math.abs(aoiCoords.top_right[1] - aoiCoords.top_left[1])
        // Approximate: 1° lat ≈ 111km, 1° lon ≈ 111km * cos(lat)
        const avgLat = (aoiCoords.top_left[0] + aoiCoords.bottom_left[0]) / 2
        const kmLat = latDiff * 111
        const kmLon = lonDiff * 111 * Math.cos((avgLat * Math.PI) / 180)
        return (kmLat * kmLon * 100).toFixed(0) // km² → ha
      })()
    : null

  return (
    <div className="flat-panel relative">
      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded bg-[#1c2128] border border-gh-border flex items-center justify-center">
            <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
          </div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gh-text">
            AOI Selector — Draw Area of Interest
          </h2>
        </div>
        <div className="flex items-center gap-3">
          {aoiCoords && (
            <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-sm badge-info animate-fade-in">
              {parseInt(areaHa).toLocaleString()} ha selected
            </span>
          )}
        </div>
      </div>

      {/* Map */}
      <div className="h-[450px] w-full relative" style={{ zIndex: 0 }}>
        <MapContainer
          center={[20.5, 79.0]}
          zoom={5}
          minZoom={2}
          className="h-full w-full"
          style={{ background: '#0D1117' }}
          zoomControl={false}
        >
          <TileLayer
            attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />
          <AutoPanForwarder />
          <FeatureGroup ref={featureGroupRef}>
            <EditControl
              position="topright"
              onCreated={handleCreated}
              onDeleted={handleDeleted}
              onEdited={handleEdited}
              draw={{
                rectangle: {
                  shapeOptions: {
                    color: '#79C0FF',
                    fillColor: '#79C0FF',
                    fillOpacity: 0.15,
                    weight: 2,
                    dashArray: '6 4',
                  },
                },
                polygon: false,
                circle: false,
                circlemarker: false,
                marker: false,
                polyline: false,
              }}
            />
          </FeatureGroup>
        </MapContainer>

        {/* Draw tool pointer overlay */}
        {!aoiCoords && (
          <div className="absolute top-[14px] right-[52px] z-[1000] animate-pulse pointer-events-none flex items-center gap-2">
            <span className="text-gh-accent text-xs font-bold font-mono tracking-wider bg-gh-bg px-2.5 py-1 rounded border border-gh-border shadow-lg flex items-center gap-2">
              use this <span className="text-lg leading-none">&rarr;</span>
            </span>
          </div>
        )}

        {/* Instructions overlay */}
        {!aoiCoords && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-[1000] flat-panel px-4 py-2.5 !rounded animate-fade-in shadow-md">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-gh-accent shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.042 21.672L13.684 16.6m0 0l-2.51 2.225.569-9.47 5.227 7.917-3.286-.672zM12 2.25V4.5m5.834.166l-1.591 1.591M20.25 10.5H18M7.757 14.743l-1.59 1.59M6 10.5H3.75m4.007-4.243l-1.59-1.59" />
              </svg>
              <p className="text-xs text-gh-muted">
                Click the <span className="text-gh-accent font-semibold">rectangle tool</span> (top-right) → draw an area on the map
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Coordinates + Analyze Button */}
      {aoiCoords && (
        <div className="px-5 py-4 border-t border-gh-border animate-fade-in">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Coordinate Display */}
            <div className="space-y-2">
              <p className="text-[10px] uppercase tracking-widest text-gh-muted font-semibold">Bounding Box Coordinates</p>
              <div className="grid grid-cols-2 gap-2">
                <CoordBadge label="Top Left" coords={aoiCoords.top_left} />
                <CoordBadge label="Top Right" coords={aoiCoords.top_right} />
                <CoordBadge label="Bottom Left" coords={aoiCoords.bottom_left} />
                <CoordBadge label="Bottom Right" coords={aoiCoords.bottom_right} />
              </div>
            </div>

            {/* Action Panel */}
            <div className="flex flex-col justify-center gap-3 relative">
              <div className="flex items-center gap-2 text-xs text-gh-muted">
                <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
                </svg>
                <span>Analysis: <span className="text-gh-accent font-semibold">Burn Detection (dNBR)</span></span>
              </div>

              {!showConfig ? (
                <div className="space-y-2">
                  <button
                    onClick={() => { setShowConfig(true); setCustomMode(false); }}
                    disabled={isAnalyzing}
                    className="w-full py-2.5 rounded text-sm font-semibold text-gh-text transition-colors flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed bg-[#238636] hover:bg-[#2ea043]"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 18a3.75 3.75 0 00.495-7.467 5.99 5.99 0 00-1.925 3.546 5.974 5.974 0 01-2.133-1A3.75 3.75 0 0012 18z" />
                    </svg>
                    <span>Start Comparing</span>
                  </button>
                  <button
                    onClick={() => { setShowConfig(true); setCustomMode(true); }}
                    disabled={isAnalyzing}
                    className="w-full py-2.5 rounded text-sm font-semibold text-gh-text transition-colors flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed border border-gh-border hover:bg-[#1c2128]"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
                    </svg>
                    <span>Custom Analysis</span>
                  </button>
                </div>
              ) : (
                <div className="bg-[#161B22] p-4 rounded border border-[#30363D] animate-fade-in">
                  <div className="flex justify-between items-center mb-3">
                    <p className="text-xs font-semibold text-gh-text">
                      {customMode ? 'Custom Analysis Configuration' : 'Analysis Configuration'}
                    </p>
                    <button onClick={() => setShowConfig(false)} className="text-gh-muted hover:text-gh-text">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                  
                  <div className="space-y-3 mb-4">
                    {!customMode && (
                      <>
                        <div>
                          <label className="block text-[10px] text-gh-muted mb-1">Before Date (Pre-fire)</label>
                          <input 
                            type="date" 
                            value={dates.before}
                            onChange={(e) => setDates(d => ({ ...d, before: e.target.value }))}
                            className="w-full bg-[#0D1117] border border-[#30363D] rounded px-3 py-1.5 text-sm text-gh-text focus:outline-none focus:border-gh-accent transition-colors"
                          />
                        </div>
                        <div>
                          <label className="block text-[10px] text-gh-muted mb-1">After Date (Post-fire)</label>
                          <input 
                            type="date" 
                            value={dates.after}
                            onChange={(e) => setDates(d => ({ ...d, after: e.target.value }))}
                            className="w-full bg-[#0D1117] border border-[#30363D] rounded px-3 py-1.5 text-sm text-gh-text focus:outline-none focus:border-gh-accent transition-colors"
                          />
                        </div>
                      </>
                    )}

                    {customMode && (
                      <div className="pt-2">
                        <label className="block text-[10px] text-gh-muted mb-2">Select Parameters to Analyze</label>
                        <div className="grid grid-cols-2 gap-2">
                          {[
                            { key: 'showNdvi', label: 'NDVI' },
                            { key: 'showNdwi', label: 'NDWI' },
                            { key: 'showNbr', label: 'NBR' },
                            { key: 'showLst', label: 'LST' },
                            { key: 'showLulc', label: 'LULC' },
                            { key: 'showSmi', label: 'Soil Moisture Index' },
                            { key: 'showCloud', label: 'Cloud Cover & Masking' },
                            { key: 'showBiomass', label: 'Biomass & Carbon' },
                          ].map(opt => (
                            <label key={opt.key} className="flex items-center gap-2 cursor-pointer group">
                              <input 
                                type="checkbox" 
                                checked={outputs[opt.key]} 
                                onChange={e => setOutputs(o => ({...o, [opt.key]: e.target.checked}))} 
                                className="accent-gh-accent bg-[#0D1117] border-[#30363D] rounded" 
                              />
                              <span className="text-[10px] sm:text-xs text-gh-text transition-colors">{opt.label}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <button
                    onClick={handleAnalyzeClick}
                    disabled={isAnalyzing || (!customMode && (!dates.before || !dates.after)) || (customMode && !Object.values(outputs).some(v => v))}
                    className="w-full py-2.5 rounded text-sm font-semibold text-gh-text transition-all duration-300 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed bg-[#238636] hover:bg-[#2ea043]"
                  >
                    {isAnalyzing ? (
                      <>
                        <div className="spinner" style={{ borderTopColor: '#79C0FF', width: 14, height: 14, borderWidth: 2 }} />
                        <span>Generating...</span>
                      </>
                    ) : (
                      <span>Get the Report</span>
                    )}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function CoordBadge({ label, coords }) {
  return (
    <div className="px-2.5 py-1.5 rounded bg-[#1c2128] border border-gh-border">
      <p className="text-[9px] uppercase tracking-wider text-gh-muted">{label}</p>
      <p className="text-[11px] font-mono text-gh-accent">{coords[0]}°N, {coords[1]}°E</p>
    </div>
  )
}
