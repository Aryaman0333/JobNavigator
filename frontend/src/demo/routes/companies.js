// /companies: the list (with live application counts), edits, acknowledge. Scraping is disabled (default 403).
import { route } from '../server.js'
import { notFound, patchRow, nowIso } from './util.js'

export function register() {
  route('GET', '/companies', ({ store, query }) => {
    const apps = store.get('applications')
    let rows = store.get('companies')
    if (query.active !== undefined) rows = rows.filter((c) => !!c.active === (query.active === 'true' || query.active === '1'))
    if (query.tier !== undefined) rows = rows.filter((c) => String(c.tier) === query.tier)
    const count = (c) => {
      const names = [c.name, ...(c.aliases || [])].map((n) => String(n).toLowerCase())
      return apps.filter((a) => names.includes(String(a.company || '').toLowerCase())).length
    }
    return {
      data: [...rows]
        .sort((a, b) => (a.tier ?? 99) - (b.tier ?? 99) || String(a.name).localeCompare(String(b.name)))
        .map((c) => ({ ...c, application_count: count(c) })),
    }
  })
  route('PATCH', '/companies/:id', ({ store, params, body }) => {
    const c = patchRow(store, 'companies', params.id, body || {})
    return c ? { data: c } : notFound('Company')
  })
  route('POST', '/companies/:id/acknowledge', ({ store, params }) => {
    const c = patchRow(store, 'companies', params.id, { warning_acknowledged_at: nowIso(), warning_acknowledged: true })
    return c ? { data: { ok: true } } : notFound('Company')
  })
}
