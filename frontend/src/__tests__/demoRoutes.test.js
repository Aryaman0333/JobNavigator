import { describe, it, expect, beforeEach } from 'vitest'
import fixture from '../demo/fixture.json'
import { handle } from '../demo/server.js'
import { loadStore } from '../demo/store.js'
import { registerAll } from '../demo/routes/index.js'
import { clearRuns } from '../demo/routes/monitor.js'

beforeEach(() => {
  localStorage.clear()
  clearRuns()
  loadStore(fixture, 'test')
  registerAll()
})

const get = async (url) => {
  const r = await handle('GET', url)
  expect(r.status, url).toBeLessThan(400)
  return r.data
}

// Each list is the load-time request set of one screen (taken from the api.* calls in screens/).
describe('screen loads', () => {
  it('Job feed', async () => {
    const jobs = await get('/api/jobs?status=new,saved&sort_by=score&limit=50')
    expect(jobs.total).toBe(2)
    expect(jobs.jobs[0].id).toBe('job-1')
    expect((await get('/api/jobs/facets')).companies.length).toBeGreaterThan(0)
    expect(await get('/api/jobs/feed-stats')).toHaveProperty('unscored')
    expect(await get('/api/jobs/unscored-ids')).toHaveProperty('ids')
    expect((await get('/api/jobs/job-1')).title).toMatch(/Growth/)
    expect(await get('/api/monitor/in-flight?job_ids=job-1&detail=1')).toEqual({})
    expect(await get('/api/jobs/job-1/frame-check')).toEqual({ embeddable: false })
    expect(typeof (await get('/api/jobs/job-1/cached-page'))).toBe('string')
  })
  it('Searches', async () => {
    expect(await get('/api/searches')).toHaveLength(1)
    await get('/api/searches/countries'); await get('/api/health/entities'); await get('/api/scheduler/jobs')
  })
  it('Companies', async () => {
    expect((await get('/api/companies'))[0].application_count).toBe(1)
    await get('/api/resumes?is_base=true'); await get('/api/persona'); await get('/api/monitor/active')
  })
  it('Applications', async () => {
    const a = await get('/api/applications')
    expect(a.total).toBe(2)
    expect(a.applications[0]).toHaveProperty('interviews')
  })
  it('Resumes', async () => {
    const shelf = await get('/api/resumes/shelf')
    expect(shelf.bases.map((b) => b.name)).toContain('PM – Platform')
    expect(await get('/api/resumes?is_base=true')).toHaveLength(2)
    expect((await get('/api/resumes/res-1')).json_data.header.name).toBe('Daniel Reyes')
    await get('/api/resumes/templates')
  })
  it('Cover letters', async () => {
    expect(await get('/api/cover-letters')).toEqual([])
    await get('/api/cover-letters/templates')
  })
  it('Persona', async () => {
    expect((await get('/api/persona')).contact.name).toBe('Daniel Reyes')
    expect((await handle('PATCH', '/api/persona', { qa_bank: [{ q: 'a' }] })).data.qa_bank).toHaveLength(1)
    expect((await get('/api/persona')).qa_bank).toHaveLength(1)
  })
  it('Stats', async () => {
    expect((await get('/api/stats')).total_jobs).toBe(4)
    expect(Array.isArray(await get('/api/stats/timeline?days=30'))).toBe(true)
    expect((await get('/api/stats/score-distribution?detail=true')).scored_count).toBe(3)
    expect((await get('/api/stats/sankey')).length).toBeGreaterThan(0)
    await get('/api/monitor/history?limit=1&job_type=scrape_all'); await get('/api/activity-log?limit=20')
    await get('/api/stats/llm-costs?days=7'); await get('/api/scheduler/jobs')
  })
  it('Settings and shell', async () => {
    const s = await get('/api/settings')
    expect(s._demo).toBe(true)
    await get('/api/settings/sections'); await get('/api/settings/policies'); await get('/api/llm/efforts')
    await get('/api/llm/models?provider=openrouter'); await get('/health'); await get('/api/gmail/status')
  })
  it('Auth', async () => {
    const me = await get('/api/auth/me')
    expect(me.account.name).toBe('Daniel Reyes')
    expect(me.accounts_count).toBe(2)
    const acc = await get('/api/accounts')
    expect(acc.accounts.map((a) => a.name)).toEqual(['Daniel Reyes', 'Elena Reyes'])
    expect(acc.accounts[1].disabled).toBe(true)
    expect((await handle('POST', '/api/auth/switch', {})).status).toBe(403)
    expect((await handle('POST', '/api/auth/verify-pin', {})).status).toBe(403)
  })
})

describe('edits', () => {
  it('moving an application records a transition shaped like record_transition()', async () => {
    const r = await handle('PATCH', '/api/applications/app-1', { status: 'interview' })
    const t = r.data.status_transitions
    expect(t).toHaveLength(2)
    expect(t[1]).toMatchObject({ from: 'applied', to: 'interview', source: 'ui' })
    expect(typeof t[1].at).toBe('string')
    const again = (await handle('GET', '/api/applications/app-1')).data
    expect(again.status).toBe('interview')
    expect(again.status_transitions).toHaveLength(2)
  })
  it('undo drops the move without a trace', async () => {
    await handle('PATCH', '/api/applications/app-1', { status: 'interview' })
    const r = await handle('PATCH', '/api/applications/app-1', { status: 'applied', undo: true })
    expect(r.data.status).toBe('applied')
    expect(r.data.status_transitions).toHaveLength(1)
  })
  it('settings writes are refused', async () => {
    expect(await handle('PATCH', '/api/settings', { x: 1 })).toEqual({ status: 403, data: { detail: 'Disabled in the demo' } })
  })
  it('saving a job sticks', async () => {
    await handle('PATCH', '/api/jobs/job-2', { saved: true, status: 'saved' })
    expect((await get('/api/jobs/job-2')).status).toBe('saved')
  })
})
