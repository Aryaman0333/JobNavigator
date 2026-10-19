// /resumes/:id/pdf|docx and /cover-letters/:id/pdf. The "PDF" is the rendered template HTML: the editors
// preview it in an iframe and the Download button hands it to the browser's print-to-PDF (see pdf.js).
import { route } from '../server.js'
import { notFound } from './util.js'
import { renderResumeHtml, renderCoverLetterHtml } from '../pdf.js'

const html = (s) => new Blob([s], { type: 'text/html' })
const noWord = { status: 404, data: { detail: 'No Word file prepared for this résumé' } }

export function register() {
  route('GET', '/resumes/:id/pdf', ({ store, params, query }) => {
    const r = store.find('resumes', params.id)
    if (!r) return notFound('Resume')
    return { data: html(renderResumeHtml(query.template || r.template, r.json_data || {}, { pageFormat: query.format || r.page_format })) }
  })

  route('GET', '/cover-letters/:id/pdf', ({ store, params }) => {
    const c = store.find('cover_letters', params.id)
    if (!c) return notFound('Cover letter')
    return { data: html(renderCoverLetterHtml(c.template, c.json_data || {}, { pageFormat: c.page_format })) }
  })

  // Pre-made Word files, one per prepared résumé.
  route('GET', '/resumes/:id/docx', async ({ store, params }) => {
    if (!store.find('resumes', params.id)) return notFound('Resume')
    try {
      const base = (import.meta.env && import.meta.env.BASE_URL) || '/'
      const res = await fetch(`${base}demo-data/docx/${encodeURIComponent(params.id)}.docx`)
      return res.ok ? { data: await res.blob() } : noWord
    } catch { return noWord }
  })
}
