// /cover-letters: list, one letter, edits.
import { route } from '../server.js'
import { notFound, nowIso, patchRow } from './util.js'

const EDITABLE = ['name', 'template', 'page_format', 'json_data', 'job_id', 'resume_id', 'voice', 'length']

// Display context is a live join in the backend (job, application stage, source résumé).
function view(store, cl, withData) {
  const job = store.find('jobs', cl.job_id)
  const stage = [...store.get('applications')].filter((a) => String(a.job_id) === String(cl.job_id))
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0]?.status ?? null
  const src = store.find('resumes', cl.resume_id)
  const { json_data, ...rest } = cl
  return {
    ...rest,
    source_name: src?.name || (cl.from_persona ? 'Persona' : null),
    company: job?.company ?? null, title: job?.title ?? null, job_url: job?.url ?? null,
    job_status: job?.status ?? null, stage, has_application: !!stage,
    ...(withData ? { json_data: json_data || {} } : {}),
  }
}

export function register() {
  route('GET', '/cover-letters/templates', ({ store }) => ({ data: store.get('cover_letter_templates') }))

  route('GET', '/cover-letters', ({ store, query }) => {
    let rows = [...store.get('cover_letters')].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
    if (query.job_id) rows = rows.filter((c) => String(c.job_id) === query.job_id)
    return { data: rows.map((c) => view(store, c, false)) }
  })

  route('GET', '/cover-letters/:id', ({ store, params }) => {
    const c = store.find('cover_letters', params.id)
    return c ? { data: view(store, c, true) } : notFound('Cover letter')
  })

  route('PATCH', '/cover-letters/:id', ({ store, params, body }) => {
    const patch = Object.fromEntries(Object.entries(body || {}).filter(([k]) => EDITABLE.includes(k)))
    const c = patchRow(store, 'cover_letters', params.id, { ...patch, updated_at: nowIso() })
    return c ? { data: view(store, c, true) } : notFound('Cover letter')
  })

  route('GET', '/cover-letters/:id/tracer-stats', () => ({ data: {} }))
}
