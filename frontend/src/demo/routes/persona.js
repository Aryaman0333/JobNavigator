// /persona: one persona per account, edited node by node (the editor autosaves).
import { route } from '../server.js'
import { nowIso } from './util.js'

const NODES = ['contact', 'work_auth', 'demographics', 'compensation', 'preferences', 'resume_content', 'qa_bank']

export function register() {
  route('GET', '/persona', ({ store }) => {
    const p = store.get('persona')
    return { data: Array.isArray(p) ? {} : p }
  })

  route('PATCH', '/persona', ({ store, body }) => {
    const unknown = Object.keys(body || {}).filter((k) => !NODES.includes(k))
    if (unknown.length) return { status: 400, data: { detail: `Unknown persona node(s): ${unknown.sort()}` } }
    const cur = store.get('persona')
    const next = { ...(Array.isArray(cur) ? {} : cur), ...body, updated_at: nowIso() }
    store.set('persona', next)
    return { data: next }
  })
}
