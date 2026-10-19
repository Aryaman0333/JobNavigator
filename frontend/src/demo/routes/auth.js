// Auth, accounts and health. One real account (Daniel); a second one is shown disabled.
import { route } from '../server.js'

const OFF = { status: 403, data: { detail: 'Disabled in the demo' } }

const publicAccount = (a) => ({ id: String(a.id), name: a.name, color: a.color, role: a.role, has_pin: !!a.has_pin, ...(a.disabled ? { disabled: true } : {}) })

export function register() {
  route('GET', '/health', () => ({
    data: {
      status: 'ok', service: 'JobNavigator',
      version: typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '3.0',
      image_outdated: false, image_message: '', image_details: [],
    },
  }))

  route('GET', '/auth/me', ({ store }) => {
    const accounts = store.get('accounts')
    const me = accounts.find((a) => a.role === 'owner') || accounts[0]
    return { data: { account: publicAccount(me), accounts_count: accounts.length, owner_has_pin: false, owner_unlocked_until: null } }
  })

  route('GET', '/auth/accounts', ({ store }) => ({ data: store.get('accounts').map(publicAccount) }))

  route('GET', '/accounts', ({ store }) => {
    const accounts = store.get('accounts')
    const me = accounts.find((a) => a.role === 'owner') || accounts[0]
    const counts = (a) => (a === me
      ? { jobs: store.get('jobs').length, applications: store.get('applications').length,
          resumes: store.get('resumes').length, cover_letters: store.get('cover_letters').length,
          searches: store.get('searches').length, companies: store.get('companies').length }
      : { jobs: 0, applications: 0, resumes: 0, cover_letters: 0, searches: 0, companies: 0 })
    return {
      data: {
        accounts: accounts.map((a) => ({ ...publicAccount(a), created_at: a.created_at || null, last_active_at: a.last_active_at || null, counts: counts(a), is_self: a === me })),
        max_accounts: accounts.length, self_id: String(me.id),
      },
    }
  })

  route('POST', '/auth/switch', () => OFF)
  route('POST', '/auth/verify-pin', () => OFF)
  route('POST', '/auth/verify-owner-pin', () => OFF)
  route('POST', '/auth/owner-lock', () => ({ data: { ok: true, locked: false } }))
  route('POST', '/auth/set-session', () => ({ data: { ok: true } }))

  route('GET', '/llm/efforts', () => ({ data: { efforts: {} } }))
  route('GET', '/gmail/status', () => ({ data: { connected: false } }))
  route('GET', '/scheduler/jobs', ({ store }) => ({ data: store.get('scheduler_jobs') }))
}
