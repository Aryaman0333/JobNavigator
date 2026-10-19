// /jobs: the feed list, facets, one posting, save/skip, and the cached posting page.
import { route } from '../server.js'
import { activeRuns } from './monitor.js'
import { csv, page, patchRow, notFound, newId, nowIso } from './util.js'

const SCORE_BANDS = [70, 80, 90]

const score = (j) => (typeof j.best_score === 'number' ? j.best_score : (typeof j.best_cv_score === 'number' ? j.best_cv_score : 0))

// Rows are stored in the backend's serialized shape; the live parts (tailored
// résumé link, in-flight ops) are derived from the other collections.
function decorate(store, j) {
  const tailored = store.get('resumes').filter((r) => !r.is_base && String(r.job_id) === String(j.id))
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0]
  const mine = activeRuns().filter((r) => String(r.target_job_id) === String(j.id))
  return {
    ...j,
    has_tailored_resume: !!tailored,
    tailored_resume_id: tailored ? String(tailored.id) : null,
    in_flight: mine.map((r) => r.job_type),
    in_flight_detail: mine.map((r) => ({ job_type: r.job_type, meta: r.meta })),
  }
}

function filtered(jobs, q) {
  let rows = jobs
  const status = csv(q.status); if (status.length) rows = rows.filter((j) => status.includes(j.status))
  const company = csv(q.company).map((c) => c.toLowerCase()); if (company.length) rows = rows.filter((j) => company.includes(String(j.company || '').toLowerCase()))
  const source = csv(q.source); if (source.length) rows = rows.filter((j) => source.includes(j.source))
  const verdict = csv(q.h1b_verdict); if (verdict.length) rows = rows.filter((j) => verdict.includes(j.h1b_verdict))
  if (q.min_score !== undefined) rows = rows.filter((j) => score(j) >= Number(q.min_score))
  if (q.max_score !== undefined) rows = rows.filter((j) => score(j) <= Number(q.max_score))
  if (q.saved !== undefined) rows = rows.filter((j) => !!j.saved === (q.saved === 'true' || q.saved === '1'))
  if (q.remote !== undefined) rows = rows.filter((j) => !!j.remote === (q.remote === 'true' || q.remote === '1'))
  if (q.title_search) rows = rows.filter((j) => String(j.title || '').toLowerCase().includes(q.title_search.toLowerCase()))
  if (q.min_salary !== undefined) rows = rows.filter((j) => (j.salary_max ?? 0) >= Number(q.min_salary))
  if (q.max_salary !== undefined) rows = rows.filter((j) => (j.salary_min ?? Infinity) <= Number(q.max_salary))
  if (q.search_id) rows = rows.filter((j) => String(j.search_id) === q.search_id)
  const arr = csv(q.arrangement)
  if (arr.length) {
    rows = rows.filter((j) => arr.some((a) => (a === 'unknown'
      ? j.arr_remote == null && j.arr_hybrid == null && j.arr_onsite == null
      : j['arr_' + a] === true)))
  }
  return rows
}

const SORTS = {
  date: (a, b) => String(b.discovered_at).localeCompare(String(a.discovered_at)),
  score: (a, b) => score(b) - score(a),
  salary: (a, b) => (b.salary_max ?? -1) - (a.salary_max ?? -1),
  company: (a, b) => String(a.company).localeCompare(String(b.company)),
}

const counts = (rows, key) => {
  const m = new Map()
  for (const r of rows) { const v = r[key]; if (v != null && v !== '') m.set(v, (m.get(v) || 0) + 1) }
  return m
}

// A reader-style page for postings that have no snapshot.
const descriptionPage = (j) => {
  const esc = (s) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
  return `<!doctype html><meta charset="utf-8"><body style="font-family:system-ui,sans-serif;line-height:1.55;max-width:760px;margin:24px auto;padding:0 20px;color:#222">`
    + `<h2 style="margin:0 0 4px">${esc(j.title)}</h2><div style="color:#666;margin-bottom:18px">${esc(j.company)}${j.location ? ' · ' + esc(j.location) : ''}</div>`
    + `<div style="white-space:pre-wrap">${esc(j.description || 'No description saved.')}</div></body>`
}

async function snapshotFor(id) {
  try {
    const base = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.BASE_URL) || '/'
    const res = await fetch(`${base}demo-data/snapshots/${id}.html`)
    if (!res.ok) return null
    const text = await res.text()
    return text && !/id="root"/.test(text) ? text : null
  } catch { return null }
}

export function register() {
  route('GET', '/jobs', ({ store, query }) => {
    const rows = filtered(store.get('jobs'), query).sort(SORTS[query.sort_by] || SORTS.date)
    const brief = query.brief === '1' || query.brief === 'true'
    const out = page(rows, query, 50).map((j) => {
      const d = decorate(store, j)
      if (brief) { delete d.description; delete d.scoring_report; delete d.h1b_jd_snippet }
      return d
    })
    return { data: { total: rows.length, jobs: out } }
  })

  route('GET', '/jobs/feed-stats', ({ store }) => {
    const jobs = store.get('jobs')
    const start = new Date(); start.setUTCHours(0, 0, 0, 0)
    return {
      data: {
        arrived_today: jobs.filter((j) => Date.parse(j.discovered_at) >= start.getTime()).length,
        unscored: jobs.filter((j) => ['new', 'saved'].includes(j.status) && !Object.keys(j.cv_scores || {}).length).length,
      },
    }
  })

  route('GET', '/jobs/unscored-ids', ({ store }) => ({
    data: { ids: store.get('jobs').filter((j) => ['new', 'saved'].includes(j.status) && !Object.keys(j.cv_scores || {}).length).map((j) => String(j.id)) },
  }))

  route('GET', '/jobs/facets', ({ store, query }) => {
    const rows = filtered(store.get('jobs'), query)
    const named = (m) => [...m.entries()].map(([name, count]) => ({ name, count }))
    return {
      data: {
        companies: named(counts(rows, 'company')).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)),
        sources: named(counts(rows, 'source')).sort((a, b) => a.name.localeCompare(b.name)),
        h1b_verdicts: named(counts(rows, 'h1b_verdict')),
        statuses: named(counts(rows, 'status')).sort((a, b) => a.name.localeCompare(b.name)),
        locations: [],   // the demo feed has no place filter
        arrangements: ['remote', 'hybrid', 'onsite', 'unknown'].map((name) => ({
          name,
          count: rows.filter((j) => (name === 'unknown' ? j.arr_remote == null && j.arr_hybrid == null && j.arr_onsite == null : j['arr_' + name] === true)).length,
        })),
        score_bands: SCORE_BANDS.map((n) => ({ name: String(n), count: rows.filter((j) => score(j) >= n).length })),
      },
    }
  })

  route('POST', '/jobs/bulk-update', ({ store, body }) => {
    const ids = body?.job_ids || []
    const allowed = ['status', 'seen', 'saved']
    const patch = Object.fromEntries(Object.entries(body?.updates || {}).filter(([k]) => allowed.includes(k)))
    let updated = 0
    const not_found = []
    for (const id of ids) { if (patchRow(store, 'jobs', id, patch)) updated++; else not_found.push(String(id)) }
    return { data: { updated, not_found } }
  })

  route('GET', '/jobs/:id', ({ store, params }) => {
    const j = store.find('jobs', params.id)
    return j ? { data: decorate(store, j) } : notFound('Job')
  })

  route('PATCH', '/jobs/:id', ({ store, params, body }) => {
    const j = store.find('jobs', params.id)
    if (!j) return notFound('Job')
    const patch = Object.fromEntries(Object.entries(body || {}).filter(([k]) => ['seen', 'saved', 'status'].includes(k)))
    const next = patchRow(store, 'jobs', params.id, patch)
    let createdApp = null
    if (patch.status === 'applied' && !store.get('applications').some((a) => String(a.job_id) === String(j.id))) {
      const at = nowIso()
      createdApp = store.put('applications', newId(), {
        job_id: String(j.id), status: 'applied', applied_at: at, cv_version_used: null, notes: null, next_action: null,
        next_action_date: null, last_email_received: null, last_email_snippet: null,
        status_transitions: [{ from: null, to: 'applied', at, source: 'ui' }], updated_at: at,
        company: j.company, company_canonical: j.company, title: j.title, url: j.url, best_cv: j.best_cv ?? null,
        short_id: j.short_id ?? null, location: j.location ?? null, salary_min: j.salary_min ?? null,
        salary_max: j.salary_max ?? null, source: j.source ?? null, has_cached_page: true,
        discovered_at: j.discovered_at ?? null, tailored_resume_id: null, tailored_resume_name: null,
        has_cover_letter: false, interviews: [],
      })
    }
    return { data: { ...decorate(store, next), created_application_id: createdApp ? String(createdApp.id) : null, created_company_id: null } }
  })

  // The snapshot of a featured posting, else the saved description.
  route('GET', '/jobs/:id/cached-page', async ({ store, params }) => {
    const j = store.find('jobs', params.id)
    if (!j) return notFound('Job')
    const featured = !!(store.get('prepared') || {})[params.id]
    const html = featured ? await snapshotFor(params.id) : null
    return { data: html || descriptionPage(j) }
  })

  // Nothing is framed from the original site in the demo.
  route('GET', '/jobs/:id/frame-check', () => ({ data: { embeddable: false } }))
}
