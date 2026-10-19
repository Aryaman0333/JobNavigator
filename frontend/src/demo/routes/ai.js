// Prepared AI actions. Scoring, tailoring, cover letters and autofill answer 202 {run_id}, show up on
// /monitor/active under the same scope key the real endpoint uses for 1.5-3 s, then write the
// prepared result (seed `prepared[job_id]`) into the store and clear the entry.
//
// prepared[job_id] = {
//   scores:       { "<résumé name>": { score, report } },   report = one scoring_report entry
//   tailored:     { name, base_id?, json_data, score? },
//   cover_letter: { name, resume_id?, template?, voice?, length?, json_data },
//   autofill:     { "<question, lower case>": "answer", _default?: "answer" },
// }
import { route } from '../server.js'
import { addRun, endRun, activeRuns } from './monitor.js'
import { newId, nowIso } from './util.js'

export const NOT_PREPARED = 'Prepared for the featured jobs only'
const MIN_MS = 1500
const MAX_MS = 3000

const delay = () => MIN_MS + Math.floor(Math.random() * (MAX_MS - MIN_MS + 1))
const preparedFor = (store, jobId) => (store.get('prepared') || {})[jobId]
const noPrep = () => ({ status: 200, data: { detail: NOT_PREPARED } })

// Starts a prepared run; `finish()` writes the result when the timer fires.
function start({ jobType, scopeKey, jobId, meta = null, finish, extra = {} }) {
  if (activeRuns().some((r) => r.job_type === jobType && r.scope_key === scopeKey)) {
    return { status: 409, data: { detail: `${jobType} is already running` } }
  }
  const run_id = addRun({ job_type: jobType, scope_key: scopeKey, target_job_id: jobId ? String(jobId) : null, meta })
  setTimeout(() => {
    try { finish(); endRun(run_id, { status: 'completed', result_summary: 'Prepared result' }) }
    catch (e) { endRun(run_id, { status: 'failed', error: String(e?.message || e) }) }
  }, delay())
  return { status: 202, data: { run_id, status: 'running', ...extra } }
}

function applyScores(store, jobId, prep, { cvIds, depth }) {
  const job = store.find('jobs', jobId)
  if (!job) return
  const wanted = Array.isArray(cvIds) && cvIds.length
    ? new Set(cvIds.map((id) => store.find('resumes', id)?.name).filter(Boolean)) : null
  const cv_scores = { ...(job.cv_scores || {}) }
  const scoring_report = { ...(job.scoring_report || {}) }
  for (const [name, entry] of Object.entries(prep.scores || {})) {
    if (wanted && !wanted.has(name)) continue
    const score = typeof entry === 'number' ? entry : entry.score
    cv_scores[name] = score
    if (depth !== 'light' && entry && typeof entry === 'object' && entry.report) scoring_report[name] = entry.report
  }
  const numeric = Object.entries(cv_scores).filter(([, v]) => typeof v === 'number')
  const [best_cv, best_score] = numeric.length ? numeric.reduce((a, b) => (b[1] > a[1] ? b : a)) : [null, 0]
  store.put('jobs', jobId, {
    ...job, cv_scores, best_cv, best_score, best_cv_score: best_score,
    scoring_report: Object.keys(scoring_report).length ? scoring_report : null,
  })
}

function applyTailored(store, jobId, baseId, prep) {
  const base = store.find('resumes', baseId)
  const t = prep.tailored
  // a tailored copy for this job already exists, so the new one supersedes it
  for (const r of store.get('resumes')) if (!r.is_base && String(r.job_id) === String(jobId)) store.remove('resumes', r.id)
  const at = nowIso()
  store.put('resumes', newId(), {
    name: t.name, is_base: false, parent_id: baseId === 'persona' ? null : (base ? String(base.id) : t.base_id ?? null),
    job_id: String(jobId), template: base?.template || 'inter', page_format: base?.page_format || 'letter',
    created_at: at, updated_at: at, json_data: t.json_data,
  })
  if (typeof t.score === 'number') {
    const job = store.find('jobs', jobId)
    if (job) store.put('jobs', jobId, { ...job, cv_scores: { ...(job.cv_scores || {}), Tailored: t.score } })
  }
}

function applyCoverLetter(store, jobId, body, prep) {
  const c = prep.cover_letter
  const at = nowIso()
  const existing = body.cover_letter_id && store.find('cover_letters', body.cover_letter_id)
  if (existing) {
    store.put('cover_letters', existing.id, { ...existing, json_data: c.json_data, updated_at: at })
    return
  }
  store.put('cover_letters', newId(), {
    name: c.name, job_id: String(jobId), resume_id: body.resume_id === 'persona' ? null : String(body.resume_id),
    template: body.template || c.template || 'inter', page_format: body.page_format || 'letter',
    voice: body.voice || c.voice || null, length: body.length || c.length || 'standard',
    from_persona: body.resume_id === 'persona', created_at: at, updated_at: at, json_data: c.json_data,
  })
}

export function register() {
  route('POST', '/analyze/:id', ({ store, params, query, body }) => {
    const prep = preparedFor(store, params.id)
    if (!prep || !prep.scores) return noPrep()
    const cvIds = body?.cv_ids
    const depth = query.depth || 'full'
    const names = Object.keys(prep.scores)
    return start({
      jobType: 'analyze_job', jobId: params.id,
      scopeKey: cvIds?.length ? `${params.id}:${[...cvIds].sort().join(',')}` : params.id,
      meta: { resume_names: names, depth }, extra: { job_id: params.id },
      finish: () => applyScores(store, params.id, prep, { cvIds, depth }),
    })
  })

  route('POST', '/resumes/tailor', ({ store, body }) => {
    const jobId = body?.job_id
    const prep = jobId ? preparedFor(store, jobId) : null
    if (!prep || !prep.tailored) return noPrep()
    const base = store.find('resumes', body.base_resume_id)
    const replaces = store.get('resumes').some((r) => !r.is_base && String(r.job_id) === String(jobId))
    return start({
      jobType: 'tailor_resume', jobId, scopeKey: `${body.base_resume_id}:${jobId}`,
      meta: { base_name: base?.name || 'Persona', replaces }, extra: { chain_score: 'off' },
      finish: () => applyTailored(store, jobId, body.base_resume_id, prep),
    })
  })

  route('POST', '/cover-letters/generate', ({ store, body }) => {
    const jobId = body?.job_id
    const prep = jobId ? preparedFor(store, jobId) : null
    if (!prep || !prep.cover_letter) return noPrep()
    return start({
      jobType: 'generate_cover_letter', jobId,
      scopeKey: body.cover_letter_id ? `cl:${body.cover_letter_id}` : `cl:${body.resume_id}:${jobId}`,
      finish: () => applyCoverLetter(store, jobId, body, prep),
    })
  })

  // Extension autofill: the answer for the featured job's form comes from the prepared map.
  route('POST', '/autofill/answer', ({ store, body }) => {
    const jobId = body?.job_id
    const prep = jobId ? preparedFor(store, jobId) : null
    const map = prep?.autofill
    if (!map || !Object.keys(map).length) return noPrep()
    const q = String(body.question || body.label || '').trim().toLowerCase()
    const answer = map[q] ?? map._default ?? ''
    return start({
      jobType: 'autofill', jobId, scopeKey: `autofill:${jobId}:${q}`,
      extra: { answer, trimmed: false, max_chars: body.max_chars ?? null },
      finish: () => {},
    })
  })
}
