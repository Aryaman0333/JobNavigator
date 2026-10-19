// Installs the in-browser demo server: prepared data -> store -> Axios adapter + fetch shim.
import api from '../api.js'
import { loadStore } from './store.js'
import { demoAdapter, installFetchShim } from './adapter.js'

export async function installDemo() {
  const base = import.meta.env.BASE_URL || '/'
  const res = await fetch(`${base}demo-data/data.json`)
  const seed = await res.json()
  loadStore(seed, String(seed.version ?? seed.reference_date ?? '1'))
  api.defaults.adapter = demoAdapter
  installFetchShim()
}
