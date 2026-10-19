// Installs the in-browser demo server: prepared data -> store -> routes -> Axios adapter + fetch shim.
import axios from 'axios'
import api from '../api.js'
import { shiftDates } from './dates.js'
import { loadStore } from './store.js'
import { demoAdapter, installFetchShim } from './adapter.js'
import { registerAll } from './routes/index.js'

export async function installDemo() {
  const base = import.meta.env.BASE_URL || '/'
  const res = await fetch(`${base}demo-data/data.json`)
  const raw = await res.json()
  // dates shift with today, so the stored-state version comes from the unshifted file
  const seed = raw.reference_date ? shiftDates(raw, raw.reference_date, new Date()) : raw
  loadStore(seed, String(raw.version ?? raw.reference_date ?? '1'))
  registerAll()
  api.defaults.adapter = demoAdapter
  axios.defaults.adapter = demoAdapter   // plain axios calls (session sync, login) must not leave the page either
  installFetchShim()
}
