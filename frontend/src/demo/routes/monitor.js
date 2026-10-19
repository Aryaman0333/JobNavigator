// /monitor/*: the registry of running jobs (in memory) plus finished-run history.
// Prepared AI actions (routes/ai.js) add and end entries here.
import { route } from '../server.js'
import { newId, nowIso, page, csv } from './util.js'

const running = []
const finished = []

export const activeRuns = () => running

export function addRun({ job_type, scope_key = null, target_job_id = null, company_id = null, trigger = 'manual', meta = null }) {
  const run = { run_id: newId(), job_type, trigger, started_at: nowIso(), scope_key, target_job_id, company_id, meta }
  running.push(run)
  return run.run_id
}

export function endRun(runId, { status = 'completed', result_summary = null, error = null } = {}) {
  const i = running.findIndex((r) => r.run_id === runId)
  if (i < 0) return null
  const [r] = running.splice(i, 1)
  const done = { ...r, id: r.run_id, status, finished_at: nowIso(), result_summary, error,
    duration_seconds: Math.round((Date.now() - Date.parse(r.started_at)) / 100) / 10 }
  finished.unshift(done)
  return done
}

export function clearRuns() { running.length = 0; finished.length = 0 }

const runView = (r) => ({
  run_id: r.run_id, job_type: r.job_type, trigger: r.trigger, started_at: r.started_at,
  elapsed_seconds: Math.round((Date.now() - Date.parse(r.started_at)) / 100) / 10,
  scope_key: r.scope_key, target_job_id: r.target_job_id, company_id: r.company_id,
})

const historyRow = (r) => ({
  id: String(r.id), job_type: r.job_type, trigger: r.trigger || 'manual', status: r.status,
  started_at: r.started_at, finished_at: r.finished_at, duration_seconds: r.duration_seconds ?? null,
  result_summary: r.result_summary ?? null, error: r.error ?? null, meta: r.meta ?? null,
})

export function register() {
  route('GET', '/monitor/active', () => ({ data: running.map(runView) }))

  route('GET', '/monitor/in-flight', ({ query }) => {
    const wanted = query.job_ids ? new Set(csv(query.job_ids)) : null
    const out = {}
    for (const r of running) {
      if (!r.target_job_id || (wanted && !wanted.has(r.target_job_id))) continue
      ;(out[r.target_job_id] = out[r.target_job_id] || []).push(query.detail ? { job_type: r.job_type, meta: r.meta } : r.job_type)
    }
    return { data: out }
  })

  route('GET', '/monitor/finished', ({ query }) => {
    const wanted = query.job_ids ? new Set(csv(query.job_ids)) : null
    const since = query.since ? Number(query.since) : null
    return {
      data: finished
        .filter((r) => r.target_job_id && (!wanted || wanted.has(r.target_job_id)))
        .filter((r) => since == null || Date.parse(r.finished_at) >= since)
        .map((r) => ({ target_job_id: r.target_job_id, job_type: r.job_type, status: r.status, finished_at: r.finished_at })),
    }
  })

  const all = (store) => [...finished.map(historyRow), ...(store.get('runs') || [])]
    .sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))

  route('GET', '/monitor/history', ({ query, store }) => {
    let rows = all(store)
    if (query.job_type) rows = rows.filter((r) => r.job_type === query.job_type)
    if (query.status) rows = rows.filter((r) => r.status === query.status)
    return { data: page(rows, query, 30) }
  })

  route('GET', '/monitor/run/:id', ({ params, store }) => {
    const r = all(store).find((x) => String(x.id) === params.id)
    return r ? { data: r } : { status: 404, data: { detail: 'Run not found' } }
  })
}
