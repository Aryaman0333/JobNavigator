// Shifts every ISO date/datetime string in a value so the prepared data reads
// as recent: d -> today + (d - reference).
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/

export function shiftDates(value, reference, today) {
  const ref = Date.parse(reference.length === 10 ? `${reference}T00:00:00Z` : reference)
  const offset = (today instanceof Date ? today.getTime() : Date.parse(today)) - ref

  const walk = (v) => {
    if (typeof v === 'string') {
      if (DATE_ONLY.test(v)) {
        const t = Date.parse(`${v}T00:00:00Z`)
        return Number.isNaN(t) ? v : new Date(t + offset).toISOString().slice(0, 10)
      }
      if (DATE_TIME.test(v)) {
        const t = Date.parse(/(Z|[+-]\d{2}:?\d{2})$/.test(v) ? v : `${v}Z`)
        return Number.isNaN(t) ? v : new Date(t + offset).toISOString()
      }
      return v
    }
    if (Array.isArray(v)) return v.map(walk)
    if (v && typeof v === 'object') {
      const out = {}
      for (const k of Object.keys(v)) out[k] = walk(v[k])
      return out
    }
    return v
  }
  return walk(value)
}
