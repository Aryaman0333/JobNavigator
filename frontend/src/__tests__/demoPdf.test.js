import { describe, it, expect, vi, afterEach } from 'vitest'
import { mkdirSync, writeFileSync } from 'node:fs'
import fixture from '../demo/fixture.json'
import { RESUME_TEMPLATES, COVER_LETTER_TEMPLATES } from '../demo/templates.js'
import { renderResumeHtml, renderCoverLetterHtml, printHtml } from '../demo/pdf.js'
import { clearRoutes, handle } from '../demo/server.js'
import { loadStore } from '../demo/store.js'
import { register } from '../demo/routes/documents.js'

const resume = fixture.resumes[0].json_data
const letter = {
  header: { name: 'Daniel Reyes', contact_items: [{ text: 'daniel@example.com', url: 'mailto:daniel@example.com' }, { text: 'Austin, TX', url: '' }] },
  date: 'October 19, 2026', recipient: { manager: 'Hiring Manager', company: 'Acme', address: '1 Main St' },
  greeting: 'Dear Hiring Manager,', body_paragraphs: ['I **led** growth at Foo & Bar.', 'Second paragraph.'],
  closing: 'Sincerely,', signature: 'Daniel Reyes',
}

describe('demo templates', () => {
  it('bundles the tracked templates without Garamond', () => {
    expect(Object.keys(RESUME_TEMPLATES).sort()).toEqual(['garamond_alt', 'helvetica', 'inter', 'modern', 'montserrat', 'palatino', 'raleway', 'traditional'])
    expect(Object.keys(COVER_LETTER_TEMPLATES)).not.toContain('garamond')
    expect(Object.keys(COVER_LETTER_TEMPLATES).length).toBeGreaterThan(0)
  })

  it.each(Object.keys(RESUME_TEMPLATES))('renders the fixture résumé with %s', (id) => {
    const html = renderResumeHtml(id, resume, { pageFormat: 'letter' })
    expect(html).toContain(resume.header.name)
    expect(html).toContain(resume.experience[0].title)
    if (process.env.DEMO_PARITY_OUT) {
      mkdirSync(process.env.DEMO_PARITY_OUT, { recursive: true })
      writeFileSync(`${process.env.DEMO_PARITY_OUT}/resume_${id}.html`, html)
    }
  })

  it.each(Object.keys(COVER_LETTER_TEMPLATES))('renders a letter with %s', (id) => {
    const html = renderCoverLetterHtml(id, letter, { pageFormat: 'a4' })
    expect(html).toContain('Dear Hiring Manager,')
    expect(html).toContain('<b>led</b> growth at Foo &amp; Bar.')
    if (process.env.DEMO_PARITY_OUT) {
      mkdirSync(process.env.DEMO_PARITY_OUT, { recursive: true })
      writeFileSync(`${process.env.DEMO_PARITY_OUT}/letter_${id}.html`, html)
      writeFileSync(`${process.env.DEMO_PARITY_OUT}/letter.json`, JSON.stringify(letter))
    }
  })

  it('drops script-capable project links and private keys', () => {
    const html = renderResumeHtml('inter', { ...resume, _score: 'SECRETKEY', projects: [{ name: 'P', url: 'java\tscript:alert(1)' }] }, {})
    expect(html).not.toContain('alert(1)')
    expect(html).not.toContain('SECRETKEY')
  })
})

describe('printHtml', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })

  const stubWindow = (win) => vi.spyOn(HTMLIFrameElement.prototype, 'contentWindow', 'get').mockReturnValue(win)
  const doc = () => ({ open() {}, write() {}, close() {}, fonts: { ready: Promise.resolve() } })

  it('removes its iframe when print throws', async () => {
    stubWindow({ document: doc(), addEventListener() {}, focus() {}, print() { throw new Error('blocked') } })
    expect(await printHtml('<p>x</p>')).toBe(false)
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('removes the iframe after afterprint (also a cancelled dialog)', async () => {
    let after
    stubWindow({ document: doc(), addEventListener: (n, f) => { if (n === 'afterprint') after = f }, focus() {}, print() {} })
    expect(await printHtml('<p>x</p>')).toBe(true)
    expect(document.querySelector('iframe')).not.toBeNull()
    after()
    expect(document.querySelector('iframe')).toBeNull()
  })
})

describe('document routes', () => {
  it('serves the rendered résumé and 404s an unknown id', async () => {
    loadStore(fixture, 'test'); clearRoutes(); register()
    const ok = await handle('GET', `/api/resumes/${fixture.resumes[0].id}/pdf?template=helvetica&format=a4`)
    expect(ok.status).toBe(200)
    expect(ok.data.type).toBe('text/html')
    expect((await handle('GET', '/api/resumes/nope/pdf')).status).toBe(404)
  })
})
