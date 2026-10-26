// telemetry.js: only fixed values leave the browser, page paths lose their ids, and the script
// loads only at `full` (never in the demo, never with Do Not Track).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('../api', () => ({ default: { get: vi.fn() } }))
const api = (await import('../api')).default
const T = await import('../telemetry')

const FULL = { level: 'full', umami: { host: 'https://a.example', website_id: 'site-1' } }
let calls

beforeEach(() => {
  T.__resetTelemetry()
  calls = []
  window.umami = { track: (fn) => calls.push(fn({ website: 'site-1', hostname: 'my.private.host', url: '/x', referrer: 'https://my.private.host/feed' })) }
  document.head.querySelectorAll('script[data-website-id]').forEach(s => s.remove())
})
afterEach(() => { delete window.umami; vi.unstubAllGlobals() })

describe('normalizePath', () => {
  it('replaces ids and drops query and hash', () => {
    expect(T.normalizePath('/resumes/4f1c2a9e-1b2c-4d5e-8f90-123456789abc')).toBe('/resumes/:id')
    expect(T.normalizePath('/feed?job=abc123def#x')).toBe('/feed')
    expect(T.normalizePath('/cover-letters/12345')).toBe('/cover-letters/:id')
    expect(T.normalizePath('/settings')).toBe('/settings')
  })
})

describe('sanitize', () => {
  it('keeps only listed events, fields and values', () => {
    expect(T.sanitize('nope', { a: 1 })).toBeNull()
    expect(T.sanitize('job_opened', { link_kind: 'direct', title: 'Secret PM' })).toEqual({ link_kind: 'direct' })
    expect(T.sanitize('job_opened', { link_kind: 'https://x' })).toEqual({})
    expect(T.sanitize('search_tested', { mode: 'Keyword', results: 37 })).toEqual({ mode: 'keyword', results: '21_100' })
    expect(T.sanitize('letter_generated', { voice: 'My own voice for Acme' })).toEqual({})
  })
})

describe('track', () => {
  it('sends nothing until enabled', () => {
    T.track('job_saved', { from: 'card' })
    expect(calls).toEqual([])
  })

  it('sends with a fixed hostname, a normalized url and no referrer or title', () => {
    T.__enableForTests()
    window.history.pushState({}, '', '/resumes/4f1c2a9e-1b2c-4d5e-8f90-123456789abc?x=1')
    T.track('resume_exported', { format: 'pdf', template: 'classic' })
    expect(calls[0]).toMatchObject({ hostname: 'jobnavigator', url: '/resumes/:id', referrer: '', title: '',
      name: 'resume_exported', data: { format: 'pdf', template: 'classic' } })
  })

  it('drops the same event within 3 s', () => {
    T.__enableForTests()
    T.track('job_saved', { from: 'card' })
    T.track('job_saved', { from: 'card' })
    T.track('job_saved', { from: 'panel' })
    expect(calls.length).toBe(2)
  })

  it('stops after 300 events in one load', () => {
    T.__enableForTests()
    for (let i = 0; i < 400; i++) T.trackPage(`/p${i}`)
    expect(calls.length).toBe(300)
  })
})

describe('initTelemetry', () => {
  const scripts = () => document.head.querySelectorAll('script[data-website-id]').length

  it('loads the script at full', async () => {
    api.get.mockResolvedValue({ data: FULL })
    await T.initTelemetry()
    const s = document.head.querySelector('script[data-website-id]')
    expect(s.src).toBe('https://a.example/script.js')
    expect(s.getAttribute('data-auto-track')).toBe('false')
  })

  it.each([
    ['essentials', { level: 'essentials', umami: null }],
    ['unset', { level: 'unset', umami: null }],
    ['off', { level: 'off', umami: null }],
  ])('loads nothing at %s', async (_n, data) => {
    api.get.mockResolvedValue({ data })
    await T.initTelemetry()
    expect(scripts()).toBe(0)
  })

  it('loads nothing with Do Not Track', async () => {
    vi.stubGlobal('navigator', { ...navigator, doNotTrack: '1' })
    api.get.mockResolvedValue({ data: FULL })
    await T.initTelemetry()
    expect(scripts()).toBe(0)
  })

  it('survives the API failing', async () => {
    api.get.mockRejectedValue(new Error('offline'))
    expect(await T.initTelemetry()).toBeNull()
    expect(scripts()).toBe(0)
  })
})
