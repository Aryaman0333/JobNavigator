// Demo UI touches: the rail marker with Reset, Elena's disabled entry, read-only Settings.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import fixture from '../demo/fixture.json'

vi.mock('../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  authFailure: () => null,
  bindPageAccount: () => {}, beginOwnSwitch: () => {}, getPageAccount: () => null, markAccountChanged: () => {}, waitForWrites: async () => {},
}))
globalThis.__APP_VERSION__ = 'test'
const api = (await import('../api')).default
const { default: Settings } = await import('../screens/Settings')
const { default: Shell } = await import('../Shell')
const { default: DemoMarker } = await import('../demo/DemoMarker')
const { loadStore, getStore } = await import('../demo/store')

const DANIEL = { id: 'a1', name: 'Daniel Reyes', color: '#2f6fed', role: 'owner', has_pin: false }
const ELENA = { id: 'a2', name: 'Elena Reyes', color: '#2e9e6b', role: 'member', has_pin: false, disabled: true }

const mockApi = (settings) => {
  api.get.mockImplementation((path) => {
    const data = {
      '/auth/me': { account: DANIEL, accounts_count: 2, owner_has_pin: false },
      '/auth/accounts': [DANIEL, ELENA],
      '/accounts': { accounts: [{ ...DANIEL, is_self: true }, ELENA], max_accounts: 5, self_id: 'a1' },
      '/settings/sections': [],
      '/settings/policies': {},
      '/resumes': [],
      '/settings': settings,
    }[path]
    return Promise.resolve({ data: data ?? {} })
  })
  api.post.mockResolvedValue({ data: {} })
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('demo marker', () => {
  it('shows the badge and Reset; Reset clears edits only after the confirm', () => {
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    loadStore(fixture, 'ui-test')
    const first = getStore().get('resumes')[0]
    getStore().put('resumes', first.id, { ...first, name: 'Edited' })
    render(<DemoMarker open />)
    expect(screen.getByText('DEMO · sample data')).toBeTruthy()
    fireEvent.click(screen.getByText('Reset demo'))
    expect(getStore().find('resumes', first.id).name).toBe('Edited')   // not yet
    fireEvent.click(screen.getByText('Reset'))
    expect(getStore().find('resumes', first.id).name).toBe(first.name)
    expect(reload).toHaveBeenCalled()
  })

  it('renders nothing in a collapsed rail', () => {
    const { container } = render(<DemoMarker open={false} />)
    expect(container.innerHTML).toBe('')
  })
})

describe('Shell account switcher', () => {
  it('lists Elena disabled with the demo note', async () => {
    mockApi({})
    render(<MemoryRouter initialEntries={['/feed']}><Shell /></MemoryRouter>)
    fireEvent.click(await screen.findByLabelText(/Daniel Reyes, .* switch account/))
    const item = await screen.findByText(/Elena Reyes — Demo shows one account/)
    const btn = item.closest('[role="menuitem"]') || item.closest('[aria-disabled]')
    expect(btn.getAttribute('aria-disabled')).toBe('true')
  })

  it('has no demo badge when __DEMO__ is false', async () => {
    mockApi({})
    render(<MemoryRouter initialEntries={['/feed']}><Shell /></MemoryRouter>)
    await screen.findByLabelText(/Daniel Reyes, .* switch account/)
    expect(screen.queryByText('DEMO · sample data')).toBeNull()
  })
})

describe('Settings in the demo', () => {
  const renderSettings = async (settings) => {
    mockApi(settings)
    render(<MemoryRouter initialEntries={['/settings']}><Settings /></MemoryRouter>)
    await waitFor(() => expect(document.querySelector('[data-sec]')).toBeTruthy())
  }
  const controls = () => [...document.querySelectorAll('[data-sec] ~ * input, [data-sec] ~ * select, [data-sec] ~ * textarea, [data-sec] ~ * button')]

  it('disables every control in the rows when settings carry _demo', async () => {
    await renderSettings({ ...fixture.settings, _demo: true })
    const locked = document.querySelectorAll('[data-locked="true"]')
    expect(locked.length).toBeGreaterThan(5)
    const inputs = [...locked].flatMap((w) => [...w.querySelectorAll('input, select, textarea, button')])
    expect(inputs.length).toBeGreaterThan(0)
    expect(inputs.every((c) => c.disabled)).toBe(true)
    expect(controls().length).toBeGreaterThan(0)
  })

  it('leaves them enabled otherwise', async () => {
    await renderSettings({ ...fixture.settings })
    expect(document.querySelectorAll('[data-locked="true"]').length).toBe(0)
  })
})
