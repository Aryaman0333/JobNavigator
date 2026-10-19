// Settings are read-only in the demo: GET returns the seed values plus `_demo: true`, every write is refused.
import { route } from '../server.js'

const OFF = { status: 403, data: { detail: 'Disabled in the demo' } }

export function register() {
  route('GET', '/settings', ({ store }) => ({ data: { ...(store.get('settings') || {}), _demo: true } }))
  route('PATCH', '/settings', () => OFF)
  route('PATCH', '/settings/policies', () => OFF)
  route('GET', '/settings/sections', () => ({ data: [] }))
  route('GET', '/settings/policies', () => ({ data: {} }))
  route('GET', '/settings/defaults', ({ store }) => ({ data: store.get('settings_defaults') || {} }))
}
