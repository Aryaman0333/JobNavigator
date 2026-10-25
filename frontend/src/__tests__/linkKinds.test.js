// Link kinds (backend scraper/_shared/link_kinds.py): whether a job reaches the employer's own site.
import { describe, it, expect } from 'vitest'
import { LINK_KINDS, linkTag, openLink } from '../linkKinds'

describe('link kinds', () => {
  it('offers Direct, Board link and Easy Apply in the Link menu', () => {
    expect(LINK_KINDS.map((k) => [k.key, k.label])).toEqual([
      ['direct', 'Direct'], ['board', 'Board link'], ['easy_apply', 'Easy Apply']])
  })

  it('tags only jobs without a direct link', () => {
    expect(linkTag({ link_kind: 'direct' })).toBeNull()
    expect(linkTag({ link_kind: null })).toBeNull()
    expect(linkTag({ link_kind: 'board' })).toEqual({ text: 'Board link', title: "No link to the employer's own site yet" })
    expect(linkTag({ link_kind: 'easy_apply' })).toEqual({ text: 'Easy Apply', title: 'Apply on LinkedIn only; the employer has no site for it' })
  })

  it('opens the employer link when there is one', () => {
    expect(openLink({ url: 'https://www.linkedin.com/jobs/view/1', link: 'https://boards.greenhouse.io/a/jobs/2' }))
      .toBe('https://boards.greenhouse.io/a/jobs/2')
    expect(openLink({ url: 'https://www.linkedin.com/jobs/view/1', link: null })).toBe('https://www.linkedin.com/jobs/view/1')
    expect(openLink(null)).toBe('')
  })
})
