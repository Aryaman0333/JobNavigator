import { describe, it, expect, beforeEach, vi } from 'vitest'
import { handle, route, clearRoutes } from '../demo/server.js'
import { loadStore, STORAGE_KEY } from '../demo/store.js'

beforeEach(() => { clearRoutes(); localStorage.clear() })

describe('demo server', () => {
  it('answers an unmatched collection GET with []', async () => {
    loadStore({}, 'v1')
    expect(await handle('GET', '/api/jobs')).toEqual({ status: 200, data: [] })
  })
  it('answers an unmatched singular GET with {}', async () => {
    loadStore({}, 'v1')
    expect(await handle('GET', '/api/stats/overview')).toEqual({ status: 200, data: {} })
  })
  it('refuses unmatched writes', async () => {
    loadStore({}, 'v1')
    expect(await handle('POST', '/api/jobs', {})).toEqual({ status: 403, data: { detail: 'Disabled in the demo' } })
  })
  it('passes params, query and body to a route', async () => {
    const store = loadStore({}, 'v1')
    route('PATCH', '/jobs/:id', ({ params, query, body, store: s }) => ({ data: { params, query, body, same: s === store } }))
    const r = await handle('PATCH', '/api/jobs/7?x=1', { a: 2 })
    expect(r.data).toEqual({ params: { id: '7' }, query: { x: '1' }, body: { a: 2 }, same: true })
  })
})

describe('demo store', () => {
  it('keeps a put across a reload with the same version', () => {
    loadStore({ jobs: [{ id: 1, t: 'a' }] }, 'v1').put('jobs', 1, { id: 1, t: 'b' })
    expect(loadStore({ jobs: [{ id: 1, t: 'a' }] }, 'v1').get('jobs')).toEqual([{ id: 1, t: 'b' }])
  })
  it('discards stored state when the version changes', () => {
    loadStore({ jobs: [{ id: 1, t: 'a' }] }, 'v1').put('jobs', 1, { id: 1, t: 'b' })
    expect(loadStore({ jobs: [{ id: 1, t: 'a' }] }, 'v2').get('jobs')).toEqual([{ id: 1, t: 'a' }])
  })
  it('works in memory when storage throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const s = loadStore({ jobs: [] }, 'v1')
    s.put('jobs', 5, { id: 5 })
    expect(s.get('jobs')).toEqual([{ id: 5 }])
    s.remove('jobs', 5)
    expect(s.get('jobs')).toEqual([])
    spy.mockRestore()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
})
