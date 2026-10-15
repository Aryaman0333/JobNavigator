// The Apify board list belongs to the backend (GET /searches/apify-boards), so
// a board the frontend has never heard of must still render, default and label.
// (3.0 port: the classic SearchManager half now targets screens/Searches.jsx.)
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Searches from '../screens/Searches'
import { apifySourceLabel, boardLabel } from '../apifyBoards'

vi.mock('../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const api = (await import('../api')).default

const BOARDS = [
  { value: 'glassdoor', label: 'Glassdoor', hint: 'Glassdoor hint', actor: 'x/glassdoor' },
  { value: 'indeed', label: 'Indeed', hint: 'Indeed hint', actor: 'misceres/indeed-scraper' },
]

describe('Apify board helpers', () => {
  it('names a board, and an Apify job source, from the backend list', () => {
    expect(boardLabel(BOARDS, 'glassdoor')).toBe('Glassdoor')
    expect(boardLabel(BOARDS, 'monster')).toBe('monster')
    expect(apifySourceLabel(BOARDS, 'apify_indeed')).toBe('Indeed (Apify)')
    expect(apifySourceLabel(BOARDS, 'apify_indeed', ' via Apify')).toBe('Indeed via Apify')
    expect(apifySourceLabel(BOARDS, 'jobspy_indeed')).toBeNull()
    expect(apifySourceLabel([], 'apify_dice')).toBe('dice (Apify)')
  })
})

describe('Apify boards · Searches', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    api.get.mockImplementation((path) => {
      if (path === '/searches/apify-boards') return Promise.resolve({ data: BOARDS })
      if (path === '/searches/countries') return Promise.resolve({ data: [{ value: 'usa', label: 'United States' }] })
      return Promise.resolve({ data: path === '/health/entities' ? {} : [] })
    })
    api.post.mockResolvedValue({ status: 200, data: {} })
  })

  const chip = (name) => screen.getAllByRole('button').find((b) => b.textContent.endsWith(name))

  it('offers every backend board, picks the first by default and saves the choice', async () => {
    render(<MemoryRouter><Searches /></MemoryRouter>)
    fireEvent.click((await screen.findAllByText('+ New search'))[0])
    fireEvent.click(await screen.findByLabelText('Mode'))
    fireEvent.click(await screen.findByRole('option', { name: /Apify/ }))

    await waitFor(() => expect(chip('Glassdoor')).toBeTruthy())
    expect(chip('Glassdoor').getAttribute('aria-pressed')).toBe('true')
    expect(chip('Indeed').getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByText('Glassdoor: Glassdoor hint')).toBeTruthy()
    expect(screen.queryByText('Indeed: Indeed hint')).toBeNull()   // hints only for ticked boards

    fireEvent.click(chip('Indeed'))
    expect(screen.getByText('Indeed: Indeed hint')).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText('e.g. TPM roles — Tier 1'), { target: { value: 'PM' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. technical program manager'), { target: { value: 'pm' } })
    fireEvent.click(screen.getByText('Create search'))
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const [, payload] = api.post.mock.calls.find(([p]) => p === '/searches')
    expect(payload.search_mode).toBe('apify')
    expect(payload.sources).toEqual(['glassdoor', 'indeed'])
  })
})
