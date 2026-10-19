// /searches: the list, countries, pause/resume and edits. Running a search is disabled (default 403).
import { route } from '../server.js'
import { notFound, patchRow, nowIso } from './util.js'

export function register() {
  route('GET', '/searches/countries', ({ store }) => ({ data: store.get('countries') }))
  route('GET', '/searches', ({ store }) => ({
    data: [...store.get('searches')].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at))),
  }))
  route('PATCH', '/searches/:id', ({ store, params, body }) => {
    const s = patchRow(store, 'searches', params.id, body || {})
    return s ? { data: s } : notFound('Search')
  })
  route('POST', '/searches/:id/acknowledge', ({ store, params }) => {
    const s = patchRow(store, 'searches', params.id, { warning_acknowledged_at: nowIso(), warning_acknowledged: true })
    return s ? { data: { ok: true } } : notFound('Search')
  })
}
