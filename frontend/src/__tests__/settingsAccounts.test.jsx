// MT-13 · Settings › Accounts / Your account building blocks: the counts line, the
// MT-11 error codes in words, the PIN dialog's steps, the Add account dialog (owner
// PIN first, then the body it posts) and the typed-name Remove confirm.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, fireEvent, act, cleanup, screen } from '@testing-library/react'

vi.mock('../api', () => {
  const api = { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }
  return { default: api, authFailure: (e) => {
    const r = e?.response
    if (!r) return null
    if (r.status === 401 && r.data?.detail === 'wrong_pin') return { kind: 'wrong_pin', triesLeft: r.data.tries_left ?? null }
    if (r.status === 401 && r.data?.detail === 'pin_required') return { kind: 'pin_required' }
    return null
  } }
})

import api from '../api'
import {
  countsLine, errorText, PinDialog, AddAccountModal, RemoveAccountModal, ColorPicker, COPY_ITEMS,
} from '../screens/SettingsAccounts'

const typePin = (pin, label) => {
  const cells = screen.getAllByLabelText(new RegExp(`${label} digit`))
  pin.split('').forEach((d, i) => fireEvent.change(cells[i], { target: { value: d } }))
}
const flush = () => act(() => Promise.resolve())

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => cleanup())

describe('countsLine / errorText', () => {
  it('lists non-zero counts with singular/plural', () => {
    expect(countsLine({ jobs: 1204, applications: 1, resumes: 0 })).toBe('1,204 jobs · 1 application')
    expect(countsLine({})).toBe('no data yet')
  })
  it('words the MT-11 codes and PIN answers', () => {
    const e = (status, data) => ({ response: { status, data } })
    expect(errorText(e(409, { detail: 'account_limit', message: 'x' }))).toMatch(/5 accounts/)
    expect(errorText(e(503, { detail: 'backup_failed' }))).toMatch(/backup failed/)
    expect(errorText(e(400, { detail: 'confirm_name_mismatch' }))).toMatch(/exactly/)
    expect(errorText(e(409, { detail: 'account_busy' }))).toMatch(/background work/)
    expect(errorText(e(401, { detail: 'wrong_pin', tries_left: 3 }))).toBe('Wrong PIN · 3 tries left')
    expect(errorText(e(422, { detail: 'name is required' }))).toBe('name is required')
    expect(errorText(new Error('net'), 'fallback')).toBe('fallback')
  })
})

describe('ColorPicker', () => {
  it('offers five swatches and reports the pick', () => {
    const onPick = vi.fn()
    render(<ColorPicker name="Alex" value="#2f6fed" onPick={onPick} taken={['#d9534f']} />)
    const radios = screen.getAllByRole('radio')
    expect(radios).toHaveLength(5)
    expect(radios[0].getAttribute('aria-checked')).toBe('true')
    expect(radios[1].getAttribute('aria-label')).toMatch(/in use/)
    fireEvent.click(radios[2])
    expect(onPick).toHaveBeenCalledWith('#2e9e6b')
  })
})

describe('PinDialog', () => {
  it('asks current → new → confirm and submits both', async () => {
    const onSubmit = vi.fn().mockResolvedValue()
    render(<PinDialog title="Change your PIN" mode="set" needCurrent onSubmit={onSubmit} onClose={() => {}} />)
    typePin('1111', 'Current PIN')
    typePin('2222', 'New PIN')
    typePin('2222', 'Same PIN again')
    await flush()
    expect(onSubmit).toHaveBeenCalledWith({ pin: '2222', current_pin: '1111' })
  })
  it('a mismatched confirm goes back to the new PIN', async () => {
    const onSubmit = vi.fn()
    render(<PinDialog title="Set your PIN" mode="set" onSubmit={onSubmit} onClose={() => {}} />)
    typePin('1234', 'New PIN')
    typePin('9999', 'Same PIN again')
    await flush()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText(/two PINs differ/)).toBeTruthy()
    expect(screen.getAllByLabelText(/New PIN digit/)).toHaveLength(4)
  })
  it('remove mode sends pin null after the current PIN', async () => {
    const onSubmit = vi.fn().mockResolvedValue()
    render(<PinDialog title="Remove your PIN" mode="remove" needCurrent onSubmit={onSubmit} onClose={() => {}} />)
    typePin('1111', 'Current PIN')
    await flush()
    expect(onSubmit).toHaveBeenCalledWith({ pin: null, current_pin: '1111' })
  })
})

describe('AddAccountModal', () => {
  const owner = { id: 'o1', name: 'Viktor', color: '#2f6fed', role: 'owner', has_pin: true }
  it('an owner without a PIN sets one first (twice), then sees the form', async () => {
    api.patch.mockResolvedValue({ data: {} })
    render(<AddAccountModal accounts={[{ ...owner, has_pin: false }]} me={{ ...owner, has_pin: false }} onClose={() => {}} onCreated={() => {}} />)
    expect(screen.getByText('Set your PIN first')).toBeTruthy()
    typePin('4321', 'New PIN')
    typePin('4321', 'Same PIN again')
    await flush(); await flush()
    expect(api.patch).toHaveBeenCalledWith('/accounts/o1', { pin: '4321' })
    expect(screen.getByLabelText('Account name')).toBeTruthy()
  })
  it('posts name, first free colour, PIN and the copy-from items', async () => {
    api.post.mockResolvedValue({ data: { account: { id: 'm1', name: 'Alex' }, copied: {} } })
    const onCreated = vi.fn()
    const { container } = render(<AddAccountModal accounts={[owner]} me={owner} onClose={() => {}} onCreated={onCreated} />)
    fireEvent.change(screen.getByLabelText('Account name'), { target: { value: ' Alex ' } })
    fireEvent.change(screen.getByLabelText('PIN for the new account'), { target: { value: '12a34' } })
    expect(screen.queryByRole('group', { name: 'Items to copy' })).toBeNull()
    // pick the owner as the copy source through the Select's trigger
    fireEvent.click(screen.getByLabelText('Copy from account'))
    fireEvent.click(screen.getByText('Viktor (owner)'))
    const group = screen.getByRole('group', { name: 'Items to copy' })
    expect(group.querySelectorAll('[role="checkbox"]')).toHaveLength(COPY_ITEMS.length)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Companies' }))      // untick one
    fireEvent.click(screen.getByText('Add account', { selector: '[role="button"], button' }))
    await flush()
    expect(api.post).toHaveBeenCalledWith('/accounts', {
      name: 'Alex', color: '#d9534f', pin: '1234',
      copy_from: { account_id: 'o1', items: ['persona', 'resumes', 'searches', 'settings', 'voices', 'excludes'] },
    })
    expect(onCreated).toHaveBeenCalled()
    expect(container).toBeTruthy()
  })
  it('shows the API message for a refused add', async () => {
    api.post.mockRejectedValue({ response: { status: 409, data: { detail: 'name_taken', message: 'x' } } })
    render(<AddAccountModal accounts={[owner]} me={owner} onClose={() => {}} onCreated={() => {}} />)
    fireEvent.change(screen.getByLabelText('Account name'), { target: { value: 'Viktor' } })
    fireEvent.click(screen.getByText('Add account', { selector: '[role="button"], button' }))
    await flush()
    expect(screen.getByText(/already has that name/)).toBeTruthy()
  })
})

describe('RemoveAccountModal', () => {
  const acc = { id: 'm1', name: 'Alex', counts: { jobs: 3, applications: 1 } }
  it('needs the exact name, then deletes with it', async () => {
    api.delete.mockResolvedValue({ data: { deleted: {}, backup: 'pre_remove_x.sql' } })
    const onRemoved = vi.fn()
    render(<RemoveAccountModal account={acc} onClose={() => {}} onRemoved={onRemoved} />)
    const btn = screen.getByText('Remove Alex', { selector: '[role="button"], button' })
    expect(btn.getAttribute('aria-disabled')).toBe('true')
    fireEvent.change(screen.getByLabelText('Type the account name to confirm'), { target: { value: 'alex' } })
    expect(btn.getAttribute('aria-disabled')).toBe('true')
    fireEvent.change(screen.getByLabelText('Type the account name to confirm'), { target: { value: 'Alex' } })
    fireEvent.click(btn)
    await flush()
    expect(api.delete).toHaveBeenCalledWith('/accounts/m1', { data: { confirm_name: 'Alex' } })
    expect(onRemoved).toHaveBeenCalled()
  })
  it('itemises the counts and words a failed backup', async () => {
    api.delete.mockRejectedValue({ response: { status: 503, data: { detail: 'backup_failed' } } })
    render(<RemoveAccountModal account={acc} onClose={() => {}} onRemoved={() => {}} />)
    expect(screen.getByText('jobs')).toBeTruthy()
    expect(screen.getByText('application')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Type the account name to confirm'), { target: { value: 'Alex' } })
    fireEvent.click(screen.getByText('Remove Alex', { selector: '[role="button"], button' }))
    await flush()
    expect(screen.getByText(/nothing was removed/)).toBeTruthy()
  })
})
