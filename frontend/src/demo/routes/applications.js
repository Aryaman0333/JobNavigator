// /applications: the board, status moves (with the same transition log the backend keeps), interviews.
import { route } from '../server.js'
import { notFound, nowIso, newId } from './util.js'

const VALID = ['applied', 'interview', 'offer', 'rejected']   // backend VALID_STATUSES

// Mirrors backend record_transition(): append {from,to,at,source}, then set the status.
export function recordTransition(app, newStatus, source) {
  if (app.status === newStatus) return app
  return {
    ...app,
    status_transitions: [...(app.status_transitions || []), { from: app.status, to: newStatus, at: nowIso(), source }],
    status: newStatus,
  }
}

// Mirrors revert_transition(): drop the newest move when it is the one being undone.
export function revertTransition(app, backTo) {
  const t = app.status_transitions || []
  const last = t[t.length - 1]
  if (last && last.to === app.status && last.from === backTo) return { ...app, status_transitions: t.slice(0, -1), status: backTo }
  return recordTransition(app, backTo, 'ui')
}

function move(app, patch) {
  let next = app
  const body = { ...patch }
  const undo = !!body.undo
  delete body.undo
  if ('status' in body) {
    if (body.status !== next.status) next = undo ? revertTransition(next, body.status) : recordTransition(next, body.status, 'ui')
    delete body.status
  }
  const allowed = ['notes', 'next_action', 'next_action_date', 'cv_version_used', 'applied_at']
  const changed = next !== app || Object.keys(body).some((k) => allowed.includes(k))
  for (const k of allowed) if (k in body) next = { ...next, [k]: body[k] }
  return changed ? { ...next, updated_at: nowIso() } : next
}

// letters / tailored copies are live joins in the backend
function decorate(store, a) {
  const tailored = store.get('resumes').filter((r) => !r.is_base && String(r.job_id) === String(a.job_id))
    .sort((x, y) => String(y.updated_at).localeCompare(String(x.updated_at)))[0]
  return {
    ...a,
    tailored_resume_id: tailored ? String(tailored.id) : a.tailored_resume_id ?? null,
    tailored_resume_name: tailored ? tailored.name : a.tailored_resume_name ?? null,
    has_cover_letter: a.has_cover_letter || store.get('cover_letters').some((c) => String(c.job_id) === String(a.job_id)),
  }
}

export function register() {
  route('GET', '/applications', ({ store, query }) => {
    let rows = store.get('applications')
    if (query.status) rows = rows.filter((a) => a.status === query.status)
    rows = [...rows].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
    const offset = Math.max(0, parseInt(query.offset, 10) || 0)
    const limit = query.limit === undefined ? 200 : Math.max(0, parseInt(query.limit, 10) || 0)
    return { data: { total: rows.length, applications: rows.slice(offset, offset + limit).map((a) => decorate(store, a)) } }
  })

  route('POST', '/applications/bulk-update', ({ store, body }) => {
    const ids = body?.ids || body?.application_ids || []
    if (!VALID.includes(body?.status)) return { status: 400, data: { detail: `status must be one of ${[...VALID].sort()}` } }
    let updated = 0, skipped = 0
    const not_found = []
    for (const id of ids) {
      const a = store.find('applications', id)
      if (!a) { not_found.push(String(id)); continue }
      if (a.status === body.status) { skipped++; continue }
      store.put('applications', id, move(a, { status: body.status, undo: !!body.undo }))
      updated++
    }
    return { data: { updated, skipped, not_found } }
  })

  route('GET', '/applications/:id', ({ store, params }) => {
    const a = store.find('applications', params.id)
    return a ? { data: decorate(store, a) } : notFound('Application')
  })

  route('PATCH', '/applications/:id', ({ store, params, body }) => {
    const a = store.find('applications', params.id)
    if (!a) return notFound('Application')
    if (body && 'status' in body && !VALID.includes(body.status)) return { status: 400, data: { detail: `status must be one of ${[...VALID].sort()}` } }
    return { data: decorate(store, store.put('applications', params.id, move(a, body || {}))) }
  })

  route('POST', '/applications/:id/interviews', ({ store, params, body }) => {
    const a = store.find('applications', params.id)
    if (!a) return notFound('Application')
    const iv = { id: newId(), what: body?.what || '', when_at: body?.when_at || null, where_text: body?.where_text || null, status: body?.status || 'scheduled', prep: body?.prep || null, created_at: nowIso() }
    store.put('applications', params.id, { ...a, interviews: [...(a.interviews || []), iv] })
    return { status: 201, data: iv }
  })

  route('PATCH', '/applications/interviews/:iid', ({ store, params, body }) => {
    const a = store.get('applications').find((x) => (x.interviews || []).some((i) => String(i.id) === params.iid))
    if (!a) return notFound('Interview')
    let out = null
    const interviews = a.interviews.map((i) => (String(i.id) === params.iid ? (out = { ...i, ...(body || {}), id: i.id }) : i))
    store.put('applications', a.id, { ...a, interviews })
    return { data: out }
  })

  route('DELETE', '/applications/interviews/:iid', ({ store, params }) => {
    const a = store.get('applications').find((x) => (x.interviews || []).some((i) => String(i.id) === params.iid))
    if (!a) return notFound('Interview')
    store.put('applications', a.id, { ...a, interviews: a.interviews.filter((i) => String(i.id) !== params.iid) })
    return { data: { ok: true } }
  })
}
