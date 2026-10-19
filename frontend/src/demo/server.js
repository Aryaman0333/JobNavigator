// The demo "backend": a route table answering what the dashboard asks of /api.
import { getStore } from './store.js'

const routes = []

const compile = (pattern) => pattern.split('/').filter(Boolean)

// route('GET', '/jobs/:id', ({ params, query, body, store }) => ({ status?, data }))
export function route(method, pattern, handler) {
  routes.push({ method: method.toUpperCase(), parts: compile(pattern), handler })
}

export function clearRoutes() { routes.length = 0 }

function match(method, parts) {
  for (const r of routes) {
    if (r.method !== method || r.parts.length !== parts.length) continue
    const params = {}
    let ok = true
    for (let i = 0; i < parts.length && ok; i++) {
      const p = r.parts[i]
      if (p[0] === ':') params[p.slice(1)] = decodeURIComponent(parts[i])
      else if (p !== parts[i]) ok = false
    }
    if (ok) return { r, params }
  }
  return null
}

export async function handle(method, url, body) {
  method = String(method || 'GET').toUpperCase()
  const u = new URL(url, 'http://demo.local')
  const path = u.pathname.replace(/^\/api(?=\/|$)/, '')
  const parts = path.split('/').filter(Boolean)
  const query = Object.fromEntries(u.searchParams.entries())
  const hit = match(method, parts)
  if (hit) {
    const out = await hit.r.handler({ params: hit.params, query, body, store: getStore() })
    return { status: out?.status ?? 200, data: out?.data }
  }
  if (method === 'GET' || method === 'HEAD') {
    const last = parts[parts.length - 1] || ''
    return { status: 200, data: last.endsWith('s') ? [] : {} }
  }
  return { status: 403, data: { detail: 'Disabled in the demo' } }
}
