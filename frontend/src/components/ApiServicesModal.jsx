import React, { useState, useEffect } from 'react'
import { fetchApiKey } from '../api'

const CODE_TABS = ['cURL', 'Python', 'JavaScript']

export default function ApiServicesModal({ onClose }) {
  const [apiKey, setApiKey] = useState(null)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)
  const [activeTab, setActiveTab] = useState('cURL')
  const [copiedCode, setCopiedCode] = useState(false)

  useEffect(() => {
    fetchApiKey()
      .then(data => setApiKey(data.api_key))
      .catch(() => setApiKey('Error loading key'))
      .finally(() => setLoading(false))
  }, [])

  const copyToClipboard = (text, setter) => {
    navigator.clipboard.writeText(text).then(() => {
      setter(true)
      setTimeout(() => setter(false), 2000)
    })
  }

  const baseUrl = 'http://localhost:8000'

  const codeExamples = {
    cURL: `curl -X GET "${baseUrl}/api/v1/query?\\
  top_lat=17.4&top_lng=79.7&\\
  bottom_lat=16.7&bottom_lng=78.85&\\
  ndvi=true&lst=true" \\
  -H "X-API-Key: ${apiKey || '<YOUR_API_KEY>'}"`,

    Python: `import requests

API_KEY = "${apiKey || '<YOUR_API_KEY>'}"
BASE_URL = "${baseUrl}"

response = requests.get(
    f"{BASE_URL}/api/v1/query",
    params={
        "top_lat": 17.4,
        "top_lng": 79.7,
        "bottom_lat": 16.7,
        "bottom_lng": 78.85,
        "ndvi": True,
        "lst": True,
    },
    headers={"X-API-Key": API_KEY}
)

data = response.json()
print(f"Districts found: {data['districts_found']}")
print(f"Area: {data['aoi']['area_ha']} ha")`,

    JavaScript: `const API_KEY = "${apiKey || '<YOUR_API_KEY>'}";
const BASE_URL = "${baseUrl}";

const params = new URLSearchParams({
  top_lat: 17.4,
  top_lng: 79.7,
  bottom_lat: 16.7,
  bottom_lng: 78.85,
  ndvi: true,
  lst: true,
});

const res = await fetch(
  \`\${BASE_URL}/api/v1/query?\${params}\`,
  { headers: { "X-API-Key": API_KEY } }
);

const data = await res.json();
console.log("Districts:", data.districts_found);
console.log("Area:", data.aoi.area_ha, "ha");`,
  }

  const sampleResponse = `{
  "status": "ok",
  "timestamp": "2026-04-25T17:00:00Z",
  "aoi": {
    "type": "bbox",
    "coordinates": {
      "top_left": [17.4, 78.85],
      "top_right": [17.4, 79.7],
      "bottom_left": [16.7, 78.85],
      "bottom_right": [16.7, 79.7]
    },
    "center": [17.05, 79.275],
    "area_ha": 69825.4,
    "area_sq_km": 698.25
  },
  "districts_found": 1,
  "districts": [ { "id": "d001", "name": "Nalgonda", ... } ],
  "analysis": {
    "parameters_requested": ["ndvi", "lst"],
    "results": {
      "NDVI": { "mean": 0.45, "min": 0.1, "max": 0.85, ... },
      "LST": { "mean_celsius": 32.6, ... }
    },
    "summary": { "overall_condition": "moderate stress", ... }
  }
}`

  const endpoints = [
    {
      method: 'GET',
      path: '/api/v1/key',
      auth: 'None',
      desc: 'Retrieve your API secret key',
    },
    {
      method: 'GET',
      path: '/api/v1/query',
      auth: 'X-API-Key',
      desc: 'Query bbox with custom parameters',
    },
    {
      method: 'GET',
      path: '/api/v1/districts',
      auth: 'X-API-Key',
      desc: 'List all surveyed districts',
    },
    {
      method: 'GET',
      path: '/api/v1/district/{id}',
      auth: 'X-API-Key',
      desc: 'Get single district by ID',
    },
  ]

  const queryParams = [
    { name: 'top_lat', type: 'float', required: true, desc: 'Northern latitude' },
    { name: 'top_lng', type: 'float', required: true, desc: 'Eastern longitude' },
    { name: 'bottom_lat', type: 'float', required: true, desc: 'Southern latitude' },
    { name: 'bottom_lng', type: 'float', required: true, desc: 'Western longitude' },
    { name: 'ndvi', type: 'bool', required: false, desc: 'NDVI vegetation index' },
    { name: 'ndwi', type: 'bool', required: false, desc: 'NDWI water index' },
    { name: 'nbr', type: 'bool', required: false, desc: 'NBR burn ratio' },
    { name: 'lst', type: 'bool', required: false, desc: 'Land surface temperature' },
    { name: 'lulc', type: 'bool', required: false, desc: 'Land use / land cover' },
    { name: 'smi', type: 'bool', required: false, desc: 'Soil moisture index' },
    { name: 'cloud', type: 'bool', required: false, desc: 'Cloud cover & masking' },
    { name: 'biomass', type: 'bool', required: false, desc: 'Biomass & carbon stock' },
  ]

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="api-modal-container flat-panel !rounded w-[95vw] max-w-[900px] max-h-[90vh] overflow-hidden flex flex-col animate-fade-in"
        onClick={e => e.stopPropagation()}
      >
        {/* ─── Header ─── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gh-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-[#1c2128] border border-gh-border flex items-center justify-center">
              <svg className="w-5 h-5 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
              </svg>
            </div>
            <div>
              <h2 className="text-sm font-bold text-gh-text tracking-tight">API Services</h2>
              <p className="text-[10px] text-gh-muted">AgriSat-7 Public API · v1</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded bg-[#1c2128] border border-gh-border hover:border-gh-muted flex items-center justify-center transition-colors"
          >
            <svg className="w-4 h-4 text-gh-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* ─── Scrollable Content ─── */}
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-6 api-modal-scroll">

          {/* ═══ API Key Section ═══ */}
          <div className="p-4 rounded bg-gh-bg border border-gh-border">
            <div className="flex items-center gap-2 mb-3">
              <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
              </svg>
              <h3 className="text-xs font-bold text-gh-text uppercase tracking-widest">Your API Secret</h3>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex-1 bg-[#1c2128] rounded px-4 py-2.5 font-mono text-sm text-gh-success border border-gh-border overflow-x-auto whitespace-nowrap">
                {loading ? (
                  <span className="text-gh-muted animate-pulse">Loading...</span>
                ) : (
                  apiKey
                )}
              </div>
              <button
                onClick={() => copyToClipboard(apiKey, setCopied)}
                disabled={loading}
                className="api-copy-btn shrink-0 px-3 py-2.5 rounded bg-[#238636] hover:bg-[#2ea043] text-gh-text text-xs font-semibold transition-all duration-200 flex items-center gap-1.5 disabled:opacity-50"
              >
                {copied ? (
                  <>
                    <svg className="w-3.5 h-3.5 text-gh-text" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    <span className="text-gh-text">Copied!</span>
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
                    </svg>
                    <span>Copy</span>
                  </>
                )}
              </button>
            </div>
            <p className="text-[10px] text-gh-muted mt-2">
              Include this key in the <code className="text-gh-accent bg-[#1c2128] px-1 rounded border border-gh-border">X-API-Key</code> header for all authenticated requests.
            </p>
          </div>

          {/* ═══ Endpoints Table ═══ */}
          <div>
            <h3 className="text-xs font-bold text-gh-text uppercase tracking-widest mb-3 flex items-center gap-2">
              <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m9.86-2.54a4.5 4.5 0 00-6.364-6.364L4.5 8.25l4.5 4.5" />
              </svg>
              Available Endpoints
            </h3>
            <div className="overflow-x-auto rounded border border-gh-border">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-gh-bg border-b border-gh-border">
                    <th className="px-4 py-2.5 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Method</th>
                    <th className="px-4 py-2.5 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Endpoint</th>
                    <th className="px-4 py-2.5 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Auth</th>
                    <th className="px-4 py-2.5 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {endpoints.map((ep, i) => (
                    <tr key={i} className="border-b border-gh-border hover:bg-gh-bg transition-colors">
                      <td className="px-4 py-2.5">
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm badge-success">
                          {ep.method}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-gh-accent">{ep.path}</td>
                      <td className="px-4 py-2.5 text-[11px] text-gh-muted">{ep.auth}</td>
                      <td className="px-4 py-2.5 text-[11px] text-gh-text">{ep.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* ═══ Query Parameters ═══ */}
          <div>
            <h3 className="text-xs font-bold text-gh-text uppercase tracking-widest mb-3 flex items-center gap-2">
              <svg className="w-4 h-4 text-gh-warning" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
              </svg>
              Query Parameters <span className="text-[10px] text-gh-muted font-normal normal-case ml-1">(/api/v1/query)</span>
            </h3>
            <div className="overflow-x-auto rounded border border-gh-border">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-gh-bg border-b border-gh-border">
                    <th className="px-4 py-2 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Param</th>
                    <th className="px-4 py-2 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Type</th>
                    <th className="px-4 py-2 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Required</th>
                    <th className="px-4 py-2 text-[10px] uppercase tracking-wider text-gh-muted font-semibold">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {queryParams.map((p, i) => (
                    <tr key={i} className="border-b border-gh-border hover:bg-gh-bg transition-colors">
                      <td className="px-4 py-2 font-mono text-xs text-gh-warning">{p.name}</td>
                      <td className="px-4 py-2 text-[11px] text-gh-muted">{p.type}</td>
                      <td className="px-4 py-2">
                        {p.required ? (
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-sm badge-danger">REQ</span>
                        ) : (
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-sm bg-[#1c2128] text-gh-muted border border-gh-border">OPT</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-[11px] text-gh-text">{p.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* ═══ Code Examples ═══ */}
          <div>
            <h3 className="text-xs font-bold text-gh-text uppercase tracking-widest mb-3 flex items-center gap-2">
              <svg className="w-4 h-4 text-gh-success" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
              </svg>
              Usage Examples
            </h3>

            {/* Tabs */}
            <div className="flex gap-1 mb-3 bg-gh-bg p-1 rounded w-fit border border-gh-border">
              {CODE_TABS.map(tab => (
                <button
                  key={tab}
                  onClick={() => { setActiveTab(tab); setCopiedCode(false) }}
                  className={`px-3 py-1.5 rounded-sm text-xs font-semibold transition-all duration-200 ${
                    activeTab === tab
                      ? 'bg-gh-panel text-gh-text border border-gh-border shadow-sm'
                      : 'text-gh-muted hover:text-gh-text border border-transparent'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            {/* Code Block */}
            <div className="relative group">
              <pre className="api-code-block bg-[#0D1117] border border-gh-border rounded p-4 overflow-x-auto text-xs leading-relaxed font-mono text-gh-text">
                <code>{codeExamples[activeTab]}</code>
              </pre>
              <button
                onClick={() => copyToClipboard(codeExamples[activeTab], setCopiedCode)}
                className="api-copy-btn absolute top-3 right-3 px-2.5 py-1.5 rounded bg-[#1c2128] hover:bg-gh-border border border-gh-border text-[10px] font-semibold text-gh-muted hover:text-gh-text transition-all duration-200 opacity-0 group-hover:opacity-100 flex items-center gap-1"
              >
                {copiedCode ? (
                  <>
                    <svg className="w-3 h-3 text-gh-success" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    <span className="text-gh-success">Copied!</span>
                  </>
                ) : (
                  <>
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
                    </svg>
                    Copy
                  </>
                )}
              </button>
            </div>
          </div>

          {/* ═══ Sample Response ═══ */}
          <div>
            <h3 className="text-xs font-bold text-gh-text uppercase tracking-widest mb-3 flex items-center gap-2">
              <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              Sample Response <span className="text-[10px] text-gh-muted font-normal normal-case ml-1">(GET /api/v1/query)</span>
            </h3>
            <pre className="api-code-block bg-[#0D1117] border border-gh-border rounded p-4 overflow-x-auto text-xs leading-relaxed font-mono text-gh-text max-h-[300px]">
              <code>{sampleResponse}</code>
            </pre>
          </div>

          {/* ═══ Automation Note ═══ */}
          <div className="p-4 rounded bg-[#1c2128] border border-gh-border">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded bg-gh-bg border border-gh-border flex items-center justify-center shrink-0 mt-0.5">
                <svg className="w-4 h-4 text-gh-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                </svg>
              </div>
              <div>
                <p className="text-xs font-semibold text-gh-text mb-1">Use in Automations</p>
                <p className="text-[11px] text-gh-muted leading-relaxed">
                  This API is designed for integration with external systems — IoT dashboards, alerting pipelines,
                  crop insurance automation, government portals, or any platform that needs real-time crop stress data.
                  All responses are in JSON format with consistent structure.
                </p>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
