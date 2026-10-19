import { describe, it, expect, vi, afterEach } from 'vitest'

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })

describe('demo mode config', () => {
  it('has no router basename when __DEMO__ is false', async () => {
    vi.stubGlobal('__DEMO__', false)
    vi.resetModules()
    const { ROUTER_BASENAME } = await import('../demo/config.js')
    expect(ROUTER_BASENAME).toBeUndefined()
  })
  it('uses /JobNavigator when __DEMO__ is true', async () => {
    vi.stubGlobal('__DEMO__', true)
    vi.resetModules()
    const { ROUTER_BASENAME } = await import('../demo/config.js')
    expect(ROUTER_BASENAME).toBe('/JobNavigator')
  })
})
