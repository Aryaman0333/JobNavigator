import { describe, it, expect } from 'vitest'
import { shiftDates } from '../demo/dates.js'

const today = new Date('2026-12-01T00:00:00Z')

describe('shiftDates', () => {
  it('moves a datetime relative to the reference', () => {
    expect(shiftDates('2026-10-10T12:00:00Z', '2026-10-15', today)).toBe('2026-11-26T12:00:00.000Z')
  })
  it('moves a date-only string', () => {
    expect(shiftDates('2026-10-15', '2026-10-15', today)).toBe('2026-12-01')
  })
  it('shifts nested arrays and objects, leaving other values alone', () => {
    const out = shiftDates({ a: [{ at: '2026-10-10T12:00:00Z' }], n: 3, t: 'Senior PM', z: null }, '2026-10-15', today)
    expect(out).toEqual({ a: [{ at: '2026-11-26T12:00:00.000Z' }], n: 3, t: 'Senior PM', z: null })
  })
  it('does not mutate its input', () => {
    const src = { at: '2026-10-10T12:00:00Z' }
    shiftDates(src, '2026-10-15', today)
    expect(src.at).toBe('2026-10-10T12:00:00Z')
  })
})
