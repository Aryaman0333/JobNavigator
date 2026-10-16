// The résumé toolbar's Download button opens a menu offering PDF and Word (the Word export
// is based on work by @mrAlishah). Both go through axios; a failure is an error toast.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const get = vi.fn()
vi.mock('../api', () => ({
  default: { get: (...a) => get(...a), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), defaults: {} },
  bindPageAccount: () => {}, getPageAccount: () => null, markAccountChanged: () => {},
  beginOwnSwitch: () => {}, waitForWrites: () => Promise.resolve(),
}))

import { DownloadMenu, downloadName } from '../screens/ResumeEditor'

const props = { id: 'r1', template: 'inter', format: 'a4' }

describe('DownloadMenu', () => {
  let saved
  beforeEach(() => {
    get.mockReset()
    saved = []
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:x')
    globalThis.URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () { saved.push(this.download) })
  })
  afterEach(() => vi.restoreAllMocks())

  it('starts closed, with a menu-popup button', () => {
    render(<DownloadMenu {...props} />)
    const btn = screen.getByRole('button', { name: /Download/ })
    expect(btn.getAttribute('aria-haspopup')).toBe('menu')
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('offers PDF and Word, and Escape closes it', () => {
    render(<DownloadMenu {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /Download/ }))
    expect(screen.getByRole('button', { name: /Download/ }).getAttribute('aria-expanded')).toBe('true')
    const items = screen.getAllByRole('menuitem').map((el) => el.textContent)
    expect(items).toEqual(['PDF.pdf', 'Word.docx'])
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('Word downloads the .docx with the current template and paper, under the server filename', async () => {
    get.mockResolvedValue({ data: new Blob(['PK']), headers: { 'content-disposition': 'attachment; filename="Dana_Base_Resume_7.docx"' } })
    render(<DownloadMenu {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /Download/ }))
    fireEvent.click(screen.getByText('Word'))
    expect(screen.queryByRole('menu')).toBeNull()   // closes on a choice
    await waitFor(() => expect(saved).toEqual(['Dana_Base_Resume_7.docx']))
    expect(get).toHaveBeenCalledWith('/resumes/r1/docx', { responseType: 'blob', params: { template: 'inter', format: 'a4' } })
  })

  it('PDF goes through the same path', async () => {
    get.mockResolvedValue({ data: new Blob(['%PDF']), headers: {} })
    render(<DownloadMenu {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /Download/ }))
    fireEvent.click(screen.getByText('PDF'))
    await waitFor(() => expect(saved).toEqual(['Resume.pdf']))
    expect(get.mock.calls[0][0]).toBe('/resumes/r1/pdf')
  })

  it('a non-ASCII name downloads under its UTF-8 filename*, not the ASCII fallback', async () => {
    get.mockResolvedValue({ data: new Blob(['%PDF']), headers: { 'content-disposition':
      "attachment; filename=\"JoseMuller_BaseCV_Resume.pdf\"; filename*=UTF-8''Jos%C3%A9M%C3%BCller_BaseCV_Resume.pdf" } })
    render(<DownloadMenu {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /Download/ }))
    fireEvent.click(screen.getByText('PDF'))
    await waitFor(() => expect(saved).toEqual(['JoséMüller_BaseCV_Resume.pdf']))
  })

  it('a failed export is reported through onError, not saved', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    get.mockRejectedValue(new Error('500'))
    const onError = vi.fn()
    render(<DownloadMenu {...props} onError={onError} />)
    fireEvent.click(screen.getByRole('button', { name: /Download/ }))
    fireEvent.click(screen.getByText('Word'))
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Could not download the Word document.'))
    expect(saved).toEqual([])
  })
})

describe('downloadName', () => {
  it('prefers filename* (RFC 5987) and decodes it', () => {
    expect(downloadName("attachment; filename=\"Resume.pdf\"; filename*=UTF-8''%D0%94%D0%B0%D0%BD%D0%B0_Resume.pdf", 'x'))
      .toBe('Дана_Resume.pdf')
    expect(downloadName("attachment; filename*=utf-8''%E7%8E%8B_CV.docx", 'x')).toBe('王_CV.docx')
  })

  it('falls back to the plain filename, quoted or bare', () => {
    expect(downloadName('attachment; filename="Dana_Base_Resume_7.docx"', 'x')).toBe('Dana_Base_Resume_7.docx')
    expect(downloadName('attachment; filename=Dana.pdf', 'x')).toBe('Dana.pdf')
    expect(downloadName("attachment; filename=\"Jose.pdf\"; filename*=UTF-8''%E0%A4%A", 'x')).toBe('Jose.pdf')   // malformed escape
  })

  it('uses the fallback when there is no name', () => {
    expect(downloadName(undefined, 'Resume.pdf')).toBe('Resume.pdf')
    expect(downloadName('attachment', 'Resume.docx')).toBe('Resume.docx')
  })
})
