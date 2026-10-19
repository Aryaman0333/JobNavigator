import { AxiosError } from 'axios'
import { handle } from './server.js'

function parseBody(data) {
  if (typeof data !== 'string') return data
  try { return JSON.parse(data) } catch { return data }
}

function fullUrl(config) {
  let url = String(config.url || '')
  const base = config.baseURL ? config.baseURL.replace(/\/$/, '') : ''
  if (base && !/^https?:/.test(url) && !url.startsWith(base + '/')) url = base + (url.startsWith('/') ? '' : '/') + url
  if (config.params) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(config.params)) if (v != null) qs.append(k, String(v))
    const s = qs.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }
  return url
}

// Axios adapter: answers every request from the local server.
export async function demoAdapter(config) {
  const { status, data } = await handle(config.method, fullUrl(config), parseBody(config.data))
  const response = { data, status, statusText: String(status), headers: {}, config, request: {} }
  if (status >= 200 && status < 300) return response
  throw new AxiosError(`Request failed with status code ${status}`,
    status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST, config, response.request, response)
}

// fetch() callers (Persona flush, Settings, versionCheck) go through the same server.
export function installFetchShim() {
  if (typeof window === 'undefined' || window.__jnDemoFetch) return
  const real = window.fetch.bind(window)
  window.__jnDemoFetch = true
  window.fetch = async (input, init = {}) => {
    const raw = typeof input === 'string' ? input : input?.url || String(input)
    let u
    try { u = new URL(raw, window.location.href) } catch { return real(input, init) }
    if (u.origin === window.location.origin && (u.pathname.startsWith('/api') || u.pathname.startsWith('/health'))) {
      const method = init.method || (typeof input !== 'string' && input?.method) || 'GET'
      const { status, data } = await handle(method, u.pathname + u.search, parseBody(init.body))
      return new Response(JSON.stringify(data ?? null), { status, headers: { 'Content-Type': 'application/json' } })
    }
    return real(input, init)
  }
}
