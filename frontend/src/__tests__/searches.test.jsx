// Searches screen: JobSpy source blocks, Test-run errors and the country field.
// Restores the v2 halves of the deleted sourceBlocks / testRunErrors specs and
// re-targets the classic-only country spec at screens/Searches.jsx.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Searches from '../screens/Searches'
import { BLOCKED_BADGE, SOURCE_BLOCKS } from '../sourceBlocks'

vi.mock('../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const api = (await import('../api')).default

const ZIP_TEXT = 'the server refuses the requests that this scraper sends: HTTP 403'
const SEARCH = {
  id: 's1', name: 'TPM', search_mode: 'keyword', search_term: 'tpm', location: '',
  country: 'usa', active: true, sources: ['indeed', 'zip_recruiter'],
}
const TEST_RESULT = {
  search_name: 'TPM', duration: 1, raw_count: 1, after_filter: 1,
  source_breakdown: { indeed: 1 }, source_errors: { zip_recruiter: ZIP_TEXT },
  company_breakdown: {}, jobs: [], config: { sources: ['indeed', 'zip_recruiter'] },
}
const COUNTRIES = [{ value: 'usa', label: 'United States' }, { value: 'canada', label: 'Canada' }]

const mockApi = (searches) => {
  api.get.mockImplementation((path) => {
    if (path === '/searches') return Promise.resolve({ data: searches })
    if (path === '/searches/countries') return Promise.resolve({ data: COUNTRIES })
    return Promise.resolve({ data: path === '/health/entities' ? {} : [] })
  })
  api.post.mockImplementation((path) => Promise.resolve(
    path.endsWith('/test') ? { status: 200, data: TEST_RESULT } : { status: 200, data: {} }))
  api.patch.mockResolvedValue({ data: {} })
}

const renderScreen = () => render(<MemoryRouter><Searches /></MemoryRouter>)

describe('Source blocks · v2 Searches', () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear() })

  const chip = (name) => screen.getAllByRole('button').find((b) => b.textContent.includes(name))

  it('flags only ZipRecruiter and Google Jobs, and a flagged board still submits', async () => {
    mockApi([])
    renderScreen()
    fireEvent.click((await screen.findAllByText('+ New search'))[0])
    await waitFor(() => expect(chip('ZipRecruiter')).toBeTruthy())

    expect(within(chip('ZipRecruiter')).queryByText(BLOCKED_BADGE)).not.toBeNull()
    expect(within(chip('Google Jobs')).queryByText(BLOCKED_BADGE)).not.toBeNull()
    expect(within(chip('Indeed')).queryByText(BLOCKED_BADGE)).toBeNull()
    expect(within(chip('LinkedIn')).queryByText(BLOCKED_BADGE)).toBeNull()
    for (const reason of Object.values(SOURCE_BLOCKS)) {
      expect(screen.getByText(reason, { exact: false })).toBeTruthy()
    }

    // Off with the chip, back on with a click on the badge itself.
    fireEvent.click(chip('ZipRecruiter'))
    expect(chip('ZipRecruiter').getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(within(chip('ZipRecruiter')).getByText(BLOCKED_BADGE))
    expect(chip('ZipRecruiter').getAttribute('aria-pressed')).toBe('true')

    fireEvent.change(screen.getByPlaceholderText('e.g. TPM roles — Tier 1'), { target: { value: 'TPM' } })
    fireEvent.click(screen.getByText('Create search'))
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post.mock.calls[0][0]).toBe('/searches')
    expect(api.post.mock.calls[0][1].sources).toContain('zip_recruiter')
    expect(api.post.mock.calls[0][1].sources).toContain('google')
  })
})

describe('Test run · v2 Searches', () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear() })

  it('shows a failed board and its text in the Test run result', async () => {
    mockApi([SEARCH])
    renderScreen()
    fireEvent.click(await screen.findByTitle(/^Preview run/))
    expect(await screen.findByText(`failed: ${ZIP_TEXT}`, { exact: false })).toBeTruthy()
    expect(screen.getByText('indeed 1')).toBeTruthy()
  })
})

describe('Country · v2 Searches', () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear() })

  it('new keyword search shows the Country select, defaults to usa and sends it', async () => {
    mockApi([])
    renderScreen()
    fireEvent.click((await screen.findAllByText('+ New search'))[0])
    expect(await screen.findByLabelText('Country')).toBeTruthy()

    fireEvent.change(screen.getByPlaceholderText('e.g. TPM roles — Tier 1'), { target: { value: 'TPM' } })
    fireEvent.click(screen.getByText('Create search'))
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post.mock.calls[0][1].country).toBe('usa')
  })

  it('editing a keyword search lets the country change and sends the new value', async () => {
    mockApi([SEARCH])
    renderScreen()
    fireEvent.click(await screen.findByText('TPM'))
    const trigger = await screen.findByLabelText('Country')
    await waitFor(() => expect(within(trigger).queryByText('United States')).not.toBeNull())
    fireEvent.click(trigger)
    fireEvent.click(await screen.findByRole('option', { name: /Canada/ }))
    fireEvent.click(screen.getByText('Save changes'))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][0]).toBe('/searches/s1')
    expect(api.patch.mock.calls[0][1].country).toBe('canada')
  })

  it('a non-keyword search has no Country field and sends no country', async () => {
    mockApi([{ ...SEARCH, id: 's2', name: 'Levels', search_mode: 'levels_fyi', direct_url: 'https://www.levels.fyi/jobs' }])
    renderScreen()
    fireEvent.click(await screen.findByText('Levels'))
    await screen.findByText('Save changes')
    expect(screen.queryByLabelText('Country')).toBeNull()
    fireEvent.click(screen.getByText('Save changes'))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1]).not.toHaveProperty('country')
  })
})
