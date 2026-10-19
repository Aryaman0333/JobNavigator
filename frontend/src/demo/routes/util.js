// Small helpers shared by the demo route modules.
export const nowIso = () => new Date().toISOString()

export function newId() {
  const c = globalThis.crypto
  if (c && c.randomUUID) return c.randomUUID()
  return 'demo-' + Math.random().toString(16).slice(2) + Date.now().toString(16)
}

export const notFound = (what) => ({ status: 404, data: { detail: `${what} not found` } })

export const csv = (v) => String(v || '').split(',').map((s) => s.trim()).filter(Boolean)

// The Jinja-free subset of the backend's `limit` / `offset` paging.
export function page(rows, query, dflt = 50) {
  const offset = Math.max(0, parseInt(query.offset, 10) || 0)
  const n = query.limit === undefined ? dflt : Math.max(0, parseInt(query.limit, 10) || 0)
  return rows.slice(offset, offset + n)
}

// Update a stored row with a shallow patch and return the stored copy.
export function patchRow(store, collection, id, patch) {
  const row = store.find(collection, id)
  if (!row) return null
  return store.put(collection, id, { ...row, ...patch })
}
