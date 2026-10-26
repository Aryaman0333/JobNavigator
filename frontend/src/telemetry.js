// Telemetry from the browser (docs/superpowers/specs/2026-10-26-telemetry-design.md).
// Only when the owner chose Yes (`full`): Umami's script with auto-track off, page views with ids
// replaced and no query, and the named events below. Every field takes only a value from its list
// (or a short id / a bucket); anything else is dropped, so no typed text, name or URL can be sent.
import api from './api'
import { IS_DEMO } from './demoHooks'

const ID = /^[a-z0-9_:.-]{1,32}$/
export const EVENTS = {
  session_start: { appearance: ['light', 'dark', 'system'], theme: 'id', device: ['phone', 'tablet', 'desktop'] },
  telemetry_chosen: { level: ['full', 'essentials'] },
  job_saved: { from: ['card', 'panel', 'shortcut'] },
  job_skipped: { from: ['card', 'panel', 'shortcut'] },
  job_opened: { link_kind: ['direct', 'board', 'easy_apply', 'none'] },
  feed_shortcut: { key: ['j', 'k', 's', 'x', 'e', 'o', 'f', 'g', 'ArrowDown', 'ArrowUp', 'Enter'] },
  feed_filter_used: { filter: 'id' },
  search_created: { mode: 'id' },
  search_run: { mode: 'id' },
  search_tested: { mode: 'id', results: 'bucket' },
  company_added: { ats: 'id' },
  company_scraped: { ats: 'id' },
  status_changed: { from: 'id', to: 'id' },
  tailor_started: { depth: ['light', 'full', 'off'], from: ['job', 'pasted'] },
  score_run: { depth: ['light', 'full'] },
  resume_exported: { format: ['pdf', 'docx', 'html'], template: 'id' },
  letter_generated: { voice: 'id' },
  letter_exported: { format: ['pdf', 'docx', 'html'] },
  persona_section_edited: { section: 'id' },
  settings_section_saved: { section: 'id' },
  theme_changed: { appearance: ['light', 'dark', 'system'], theme: 'id' },
}

const HOSTNAME = 'jobnavigator'
const MAX_EVENTS = 300
const DEDUPE_MS = 3000

let enabled = false
let sent = 0
const recent = new Map()

export function bucket(n) {
  const v = Number(n) || 0
  if (v <= 0) return '0'
  if (v === 1) return '1'
  if (v <= 5) return '2_5'
  if (v <= 20) return '6_20'
  if (v <= 100) return '21_100'
  return '101_plus'
}

// '/resumes/4f1c…' → '/resumes/:id'; query and hash never leave.
export function normalizePath(path) {
  const p = String(path || '/').split(/[?#]/)[0]
  const parts = p.split('/').map(seg => (
    /^[0-9a-f-]{16,}$/i.test(seg) || /^\d+$/.test(seg) || (seg.length >= 8 && /\d/.test(seg) && /^[A-Za-z0-9_-]+$/.test(seg))
      ? ':id' : seg))
  return parts.join('/') || '/'
}

export function sanitize(name, data) {
  const spec = EVENTS[name]
  if (!spec) return null
  const out = {}
  for (const [key, rule] of Object.entries(spec)) {
    const v = data?.[key]
    if (v === undefined || v === null) continue
    if (Array.isArray(rule)) { if (rule.includes(v)) out[key] = v }
    else if (rule === 'bucket') out[key] = bucket(v)
    else if (rule === 'id') { const s = String(v).toLowerCase(); if (ID.test(s)) out[key] = s }
  }
  return out
}

function send(build) {
  try { if (window.umami && typeof window.umami.track === 'function') window.umami.track(build) } catch { /* never break the app */ }
}

function base(props) {
  return { ...props, hostname: HOSTNAME, url: normalizePath(window.location.pathname), referrer: '', title: '' }
}

export function track(name, data) {
  if (!enabled || sent >= MAX_EVENTS) return
  const clean = sanitize(name, data)
  if (!clean) return
  const key = name + JSON.stringify(clean)
  const now = Date.now()
  const last = recent.get(key)
  recent.set(key, now)
  if (last && now - last < DEDUPE_MS) return
  sent++
  send(props => ({ ...base(props), name, data: clean }))
}

export function trackPage(pathname) {
  if (!enabled || sent >= MAX_EVENTS) return
  sent++
  send(props => ({ ...base(props), url: normalizePath(pathname) }))
}

const doNotTrack = () => {
  try { return navigator.doNotTrack === '1' || window.doNotTrack === '1' } catch { return false }
}

// Once per load: loads Umami's script only at `full`, with a website id, not in the demo, and not
// when the browser asks not to be tracked. Returns the /telemetry answer (the choice UI reads it).
export async function initTelemetry() {
  let state = null
  try { state = (await api.get('/telemetry')).data } catch { return null }
  if (IS_DEMO || !state?.umami || state.level !== 'full' || doNotTrack() || enabled) return state
  const s = document.createElement('script')
  s.defer = true
  s.src = `${state.umami.host}/script.js`
  s.setAttribute('data-website-id', state.umami.website_id)
  s.setAttribute('data-host-url', state.umami.host)
  s.setAttribute('data-auto-track', 'false')
  s.setAttribute('data-do-not-track', 'true')
  document.head.appendChild(s)
  enabled = true
  return state
}

export function __resetTelemetry() { enabled = false; sent = 0; recent.clear() }
export function __enableForTests() { enabled = true }
