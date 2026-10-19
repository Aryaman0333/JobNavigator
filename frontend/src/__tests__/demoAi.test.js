import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fixture from '../demo/fixture.json'
import { handle } from '../demo/server.js'
import { loadStore } from '../demo/store.js'
import { registerAll } from '../demo/routes/index.js'
import { clearRuns } from '../demo/routes/monitor.js'

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  clearRuns()
  loadStore(fixture, 'test')
  registerAll()
})
afterEach(() => vi.useRealTimers())

const active = async () => (await handle('GET', '/api/monitor/active')).data

describe('prepared AI actions', () => {
  it('scores a featured job: 202, shows on the monitor, writes the prepared scores after 3 s', async () => {
    const r = await handle('POST', '/api/analyze/job-2?depth=full', null)
    expect(r.status).toBe(202)
    expect(r.data.run_id).toBeTruthy()
    const runs = await active()
    expect(runs).toHaveLength(1)
    expect(runs[0]).toMatchObject({ job_type: 'analyze_job', scope_key: 'job-2', target_job_id: 'job-2' })
    expect((await handle('GET', '/api/jobs/job-2')).data.in_flight).toEqual(['analyze_job'])

    await vi.advanceTimersByTimeAsync(3000)
    expect(await active()).toEqual([])
    const job = (await handle('GET', '/api/jobs/job-2')).data
    expect(job.cv_scores).toEqual({ 'PM – Platform': 82 })
    expect(job.best_score).toBe(82)
    expect(job.scoring_report['PM – Platform'].summary).toMatch(/platform/i)
    const done = (await handle('GET', '/api/monitor/run/' + r.data.run_id)).data
    expect(done.status).toBe('completed')
  })

  it('refuses a duplicate while the same scope is running', async () => {
    await handle('POST', '/api/analyze/job-2', null)
    expect((await handle('POST', '/api/analyze/job-2', null)).status).toBe(409)
  })

  it('tailors a featured job into a résumé linked to it', async () => {
    const r = await handle('POST', '/api/resumes/tailor', { base_resume_id: 'res-2', job_id: 'job-2' })
    expect(r.status).toBe(202)
    expect((await active())[0]).toMatchObject({ job_type: 'tailor_resume', scope_key: 'res-2:job-2' })
    await vi.advanceTimersByTimeAsync(3000)
    expect(await active()).toEqual([])
    const copies = (await handle('GET', '/api/resumes')).data.filter((x) => !x.is_base)
    expect(copies).toHaveLength(1)
    expect(copies[0]).toMatchObject({ job_id: 'job-2', parent_id: 'res-2' })
    expect((await handle('GET', '/api/jobs/job-2')).data.tailored_resume_id).toBe(copies[0].id)
  })

  it('writes a cover letter for a featured job', async () => {
    await handle('POST', '/api/cover-letters/generate', { resume_id: 'res-2', job_id: 'job-2' })
    await vi.advanceTimersByTimeAsync(3000)
    const list = (await handle('GET', '/api/cover-letters')).data
    expect(list).toHaveLength(1)
    expect(list[0]).toMatchObject({ job_id: 'job-2', company: 'Northwind Labs', source_name: 'PM – Platform' })
  })

  it('answers a non-featured job with the friendly message and no monitor entry', async () => {
    for (const [url, body] of [['/api/analyze/job-3', null], ['/api/resumes/tailor', { base_resume_id: 'res-1', job_id: 'job-3' }],
      ['/api/cover-letters/generate', { resume_id: 'res-1', job_id: 'job-3' }], ['/api/resumes/tailor', { base_resume_id: 'res-1', job_description: 'pasted' }]]) {
      const r = await handle('POST', url, body)
      expect(r).toEqual({ status: 200, data: { detail: 'Prepared for the featured jobs only' } })
    }
    expect(await active()).toEqual([])
  })
})
