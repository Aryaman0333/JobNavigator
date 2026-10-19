// In-browser rendering of the real résumé / cover-letter templates (nunjucks standing in for Jinja)
// and the browser's print-to-PDF.
import nunjucks from 'nunjucks/browser/nunjucks.js'
import { RESUME_TEMPLATES, COVER_LETTER_TEMPLATES } from './templates.js'

const escapeHtml = (s) => String(s ?? '').replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]))

// Same as the backend's `bold` filter: escape, then **x** -> <b>x</b>.
const bold = (text) => escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')

// Jinja -> nunjucks for the few constructs the templates use that nunjucks spells differently.
function toNunjucks(src) {
  return src.replace(/\{[{%][\s\S]*?[}%]\}/g, (tag) => tag
    .replace(/\.startswith\(/g, '.startsWith(')
    .replace(/\.append\(/g, '.push(')
    .replace(/\.items\(\)/g, '')
    .replace(/~/g, '+'))
}

const env = new nunjucks.Environment(null, { autoescape: false })
env.addFilter('bold', bold)

const compiled = {}
function compile(kind, id, sources) {
  const key = `${kind}:${id}`
  if (!compiled[key]) {
    const src = sources[id] ?? Object.values(sources)[0]
    if (src === undefined) throw new Error(`No ${kind} template "${id}"`)
    compiled[key] = new nunjucks.Template(toNunjucks(src), env, key, true)
  }
  return compiled[key]
}

// Mirrors the backend's _render_safe_links: string contact items, no script-capable project / publication links.
const UNSAFE = ['javascript', 'vbscript', 'data', 'file', 'blob']
const text = (v) => (v == null ? '' : typeof v === 'string' ? v : String(v))
function printableLink(url) {
  const m = /^([a-zA-Z][a-zA-Z0-9+.\-]*):/.exec(text(url).replace(/[\x00-\x20\x7f]/g, '')) // eslint-disable-line no-control-regex
  return m && UNSAFE.includes(m[1].toLowerCase()) ? '' : text(url)
}
// Jinja treats an empty list or dict as false, JS (and so nunjucks) does not: leave those keys out.
function prune(v) {
  if (Array.isArray(v)) return v.map(prune)
  if (v && typeof v === 'object') {
    const out = {}
    for (const [k, x] of Object.entries(v)) {
      const p = prune(x)
      const empty = (Array.isArray(p) && !p.length) || (p && typeof p === 'object' && !Array.isArray(p) && !Object.keys(p).length)
      if (!empty) out[k] = p
    }
    return out
  }
  return v
}

function safeContent(json) {
  const out = {}
  for (const [k, v] of Object.entries(prune(json || {}))) if (!k.startsWith('_')) out[k] = v
  const h = out.header
  if (h && typeof h === 'object' && !Array.isArray(h)) {
    const items = Array.isArray(h.contact_items) ? h.contact_items : []
    out.header = { ...h, contact_items: items.filter((i) => i && typeof i === 'object')
      .map((i) => ({ ...i, text: text(i.text), url: text(i.url) })) }
  }
  for (const key of ['projects', 'publications']) {
    if (Array.isArray(out[key])) out[key] = out[key].map((e) => (e && typeof e === 'object' && e.url ? { ...e, url: printableLink(e.url) } : e))
  }
  return out
}

const fmtOf = (opts) => (opts && opts.pageFormat) || 'letter'

export function renderResumeHtml(templateId, resumeJson, opts) {
  return compile('resume', templateId, RESUME_TEMPLATES)
    .render({ ...safeContent(resumeJson), page_format: fmtOf(opts), fonts_base: '', fonts: {} })
}

export function renderCoverLetterHtml(templateId, letterJson, opts) {
  return compile('letter', templateId, COVER_LETTER_TEMPLATES)
    .render({ ...safeContent(letterJson), page_format: fmtOf(opts), fonts: {} })
}

const FONT_WAIT_MS = 3000

// Print `html` through a hidden iframe. The iframe is removed afterwards, also when print throws or is cancelled.
export function printHtml(html) {
  return new Promise((resolve) => {
    const frame = document.createElement('iframe')
    frame.setAttribute('aria-hidden', 'true')
    frame.setAttribute('tabindex', '-1')
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden'
    document.body.appendChild(frame)
    let done = false
    const cleanup = () => { if (!done) { done = true; frame.remove() } }
    ;(async () => {
      try {
        const win = frame.contentWindow
        win.document.open(); win.document.write(html); win.document.close()
        try { await Promise.race([win.document.fonts?.ready, new Promise((r) => setTimeout(r, FONT_WAIT_MS))]) } catch { /* print anyway */ }
        win.addEventListener('afterprint', cleanup)
        setTimeout(cleanup, 120000)   // Firefox prints after print() returns; a cancelled dialog still ends up here
        win.focus()
        win.print()
        resolve(true)
      } catch {
        cleanup()
        resolve(false)
      }
    })()
  })
}

export function blobText(b) {
  if (typeof b === 'string') return Promise.resolve(b)
  if (b && typeof b.text === 'function') return b.text()
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = rej; r.readAsText(b) })
}
