// /resumes: list, the shelf (bases with their tailored copies), one résumé, edits.
import { route } from '../server.js'
import { notFound, nowIso, patchRow } from './util.js'

const STALE_DAYS = 45
const EDITABLE = ['name', 'is_base', 'parent_id', 'job_id', 'template', 'page_format', 'json_data']

const meta = (r) => {
  const { json_data, ...rest } = r   // eslint-disable-line no-unused-vars
  return rest
}

function copyScore(job, name) {
  if (!job) return null
  const cs = job.cv_scores || {}
  for (const k of [name, 'Tailored']) if (typeof cs[k] === 'number') return Math.round(cs[k])
  const nums = Object.values(cs).filter((v) => typeof v === 'number')
  return nums.length ? Math.round(Math.max(...nums)) : null
}

const fresh = (c) => (c.json_data?.experience || []).some((e) => e && e.suggested_bullets && e.suggested_bullets.length)

function shelf(store) {
  const resumes = [...store.get('resumes')].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
  const bases = resumes.filter((r) => r.is_base)
  const copies = resumes.filter((r) => !r.is_base)
  const jobs = new Map(store.get('jobs').map((j) => [String(j.id), j]))
  const appStatus = new Map(), appUpdated = new Map()
  for (const a of [...store.get('applications')].sort((x, y) => String(x.updated_at).localeCompare(String(y.updated_at)))) {
    appStatus.set(String(a.job_id), a.status); appUpdated.set(String(a.job_id), a.updated_at)
  }
  const now = Date.now()
  const reasonOf = (c) => {
    if (appStatus.get(String(c.job_id)) === 'rejected') return 'rejected'
    const days = Math.floor((now - Date.parse(c.updated_at)) / 864e5)
    return days > STALE_DAYS ? `stale ${days}d` : null
  }
  const archivedAt = (c, reason) => (reason === 'rejected' ? appUpdated.get(String(c.job_id)) : null) || c.updated_at || null

  const archived = []
  const group = (clist, baseId) => {
    const out = [], scores = []
    for (const c of clist) {
      const job = jobs.get(String(c.job_id))
      const sc = copyScore(job, c.name)
      if (sc !== null) scores.push(sc)
      const reason = reasonOf(c)
      if (reason) {
        archived.push({ id: String(c.id), name: c.name, base_id: baseId, job_id: c.job_id ? String(c.job_id) : null,
          company: job?.company ?? null, role: job?.title ?? null, why: reason, archived_at: archivedAt(c, reason) })
        continue
      }
      out.push({ id: String(c.id), name: c.name, job_id: c.job_id ? String(c.job_id) : null, company: job?.company ?? null,
        role: job?.title ?? null, score: sc, status: appStatus.get(String(c.job_id)) || job?.status || null,
        fresh: fresh(c), updated_at: c.updated_at || null })
    }
    return { out, scores }
  }
  const avg = (s) => (s.length ? Math.round(s.reduce((x, y) => x + y, 0) / s.length) : null)

  const baseRows = bases.map((b) => {
    const clist = copies.filter((c) => String(c.parent_id) === String(b.id))
    const { out, scores } = group(clist, String(b.id))
    return { id: String(b.id), name: b.name, updated_at: b.updated_at || null, copy_count: out.length,
      archived_count: clist.length - out.length, avg_fit: avg(scores), copies: out }
  })
  const orphans = copies.filter((c) => !c.parent_id)
  const p = group(orphans, null)
  const persona = { copy_count: p.out.length, archived_count: orphans.length - p.out.length, avg_fit: avg(p.scores),
    copies: p.out, updated_at: p.out[0]?.updated_at ?? null }
  archived.sort((a, b) => String(b.archived_at || '').localeCompare(String(a.archived_at || '')))
  return { bases: baseRows, total_copies: copies.length - archived.length, persona, archived, archived_count: archived.length }
}

export function register() {
  route('GET', '/resumes/templates', ({ store }) => ({ data: store.get('resume_templates') }))
  route('GET', '/resumes/shelf', ({ store }) => ({ data: shelf(store) }))

  route('GET', '/resumes', ({ store, query }) => {
    let rows = [...store.get('resumes')].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
    if (query.is_base !== undefined) rows = rows.filter((r) => !!r.is_base === (query.is_base === 'true' || query.is_base === '1'))
    return { data: rows.map(meta) }
  })

  route('GET', '/resumes/:id', ({ store, params }) => {
    const r = store.find('resumes', params.id)
    return r ? { data: { ...meta(r), json_data: r.json_data || {} } } : notFound('Resume')
  })

  route('PATCH', '/resumes/:id', ({ store, params, body }) => {
    const patch = Object.fromEntries(Object.entries(body || {}).filter(([k]) => EDITABLE.includes(k)))
    const r = patchRow(store, 'resumes', params.id, { ...patch, updated_at: nowIso() })
    return r ? { data: { ...meta(r), json_data: r.json_data || {} } } : notFound('Resume')
  })

  route('GET', '/resumes/:id/tracer-stats', () => ({ data: {} }))
}
