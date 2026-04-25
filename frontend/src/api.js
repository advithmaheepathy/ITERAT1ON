import axios from 'axios'

const API_BASE = 'http://localhost:8000'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

/** Fetch full dashboard payload */
export const fetchDashboard = () => api.get('/dashboard').then(r => r.data)

/** Fetch single district details */
export const fetchDistrict = (id) => api.get(`/district/${id}`).then(r => r.data)

/** Trigger a simulated satellite pass */
export const simulatePass = () => api.post('/simulate-pass').then(r => r.data)

/** Send AOI bounding box for burn analysis */
export const analyzeAOI = (payload) => api.post('/analyze', payload).then(r => r.data)
