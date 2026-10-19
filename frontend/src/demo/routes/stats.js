// Stats screen: counts, timeline, score spread, funnel flows, LLM spend, activity.
import { route } from '../server.js'
import { page } from './util.js'

const best = (j) => {
  const nums = Object.values(j.cv_scores || {}).filter((v) => typeof v === 'number')
  return nums.length ? Math.max(...nums) : null
}

export function register() {
  route('GET', '/stats', ({ store }) => {
    const jobs = store.get('jobs'), apps = store.get('applications')
    const application_statuses = {}
    for (const a of apps) application_statuses[a.status] = (application_statuses[a.status] || 0) + 1
    return {
      data: {
        total_jobs: jobs.length, new_jobs: jobs.filter((j) => j.status === 'new').length,
        saved_jobs: jobs.filter((j) => j.status === 'saved').length, total_applications: apps.length, application_statuses,
      },
    }
  })

  route('GET', '/stats/timeline', ({ store, query }) => {
    const days = Number(query.days ?? 30)
    const cutoff = Date.now() - days * 864e5
    const byDay = new Map()
    for (const j of store.get('jobs')) {
      const t = Date.parse(j.discovered_at)
      if (!(t >= cutoff)) continue
      const d = new Date(t).toISOString().slice(0, 10)
      const r = byDay.get(d) || { date: d, total: 0, new: 0, saved: 0, applied: 0, skipped: 0, filtered: 0 }
      r.total++
      const key = { new: 'new', saved: 'saved', applied: 'applied', skip: 'skipped', ignored: 'filtered' }[j.status]
      if (key) r[key]++
      byDay.set(d, r)
    }
    return { data: [...byDay.values()].sort((a, b) => a.date.localeCompare(b.date)) }
  })

  route('GET', '/stats/score-distribution', ({ store, query }) => {
    const buckets = { '0-20': 0, '21-40': 0, '41-60': 0, '61-80': 0, '81-100': 0 }
    const bests = [], tailored = []
    for (const j of store.get('jobs')) {
      const b = best(j)
      if (b === null) continue
      bests.push(b)
      if (typeof j.cv_scores.Tailored === 'number') tailored.push(j.cv_scores.Tailored)
      buckets[b <= 20 ? '0-20' : b <= 40 ? '21-40' : b <= 60 ? '41-60' : b <= 80 ? '61-80' : '81-100']++
    }
    const rows = Object.entries(buckets).map(([range, count]) => ({ range, count }))
    if (!(query.detail === 'true' || query.detail === '1')) return { data: rows }
    const avg = (a) => (a.length ? Math.round((a.reduce((x, y) => x + y, 0) / a.length) * 10) / 10 : null)
    return { data: { buckets: rows, scored_count: bests.length, avg: avg(bests), tailored_count: tailored.length, tailored_avg: avg(tailored) } }
  })

  route('GET', '/stats/sankey', ({ store }) => {
    const flows = new Map()
    for (const a of store.get('applications')) {
      for (const t of a.status_transitions || []) {
        if (!t.to) continue
        const k = `${t.from || 'new'}\u0000${t.to}`
        flows.set(k, (flows.get(k) || 0) + 1)
      }
    }
    return { data: [...flows.entries()].map(([k, value]) => { const [source, target] = k.split('\u0000'); return { source, target, value } }) }
  })

  route('GET', '/stats/llm-costs', ({ store, query }) => {
    const seed = store.get('llm_costs')
    const base = Array.isArray(seed) ? { total_calls: 0, total_cost_usd: 0, by_purpose: [] } : seed
    return { data: { ...base, window_days: Number(query.days ?? 7) } }
  })

  route('GET', '/activity-log', ({ store, query }) => {
    let rows = [...store.get('activity_log')].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
    if (query.type) rows = rows.filter((r) => r.type === query.type)
    if (query.company) rows = rows.filter((r) => String(r.company || '').toLowerCase().includes(query.company.toLowerCase()))
    return { data: page(rows, query, 50) }
  })

  route('GET', '/health/entities', () => ({ data: { companies: [], searches: [] } }))
}
