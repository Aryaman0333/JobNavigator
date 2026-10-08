import React, { useState, useEffect, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import LoginModal from './LoginModal'
import AccountPicker from './AccountPicker'
import AccountChanged from './AccountChanged'
import { listenForSwitches } from './accounts'
import WelcomeModal from './WelcomeModal'
import NewUiModal from './NewUiModal'
import Shell from './Shell'
import JobFeed from './screens/JobFeed'
import Resumes from './screens/Resumes'
import ResumeEditor from './screens/ResumeEditor'
import Companies from './screens/Companies'
import Searches from './screens/Searches'
import Applications from './screens/Applications'
import CoverLetters from './screens/CoverLetters'
import CoverLetterEditor from './screens/CoverLetterEditor'
import Settings from './screens/Settings'
import Persona from './screens/Persona'
import Stats from './screens/Stats'
import axios from 'axios'
import { TitleSync } from './useTitle'

// design-base/ (lab pages) is git-ignored and may not exist on a clone.
// import.meta.glob yields an empty map when it matches nothing, so an absent folder costs the two routes rather than breaking the build.
const LAB_PAGES = import.meta.glob('./design-base/*.jsx')
const labRoute = (name, path) => {
  const load = LAB_PAGES[`./design-base/${name}.jsx`]
  if (!load) return null   // folder (or file) absent — no route, no error
  const Page = lazy(load)
  return <Route path={path} element={<Suspense fallback={null}><Page /></Suspense>} />
}

// Set once the onboarding overlay has been dismissed; its absence is what makes
// a browser profile a "first visit" (R4-T0-02).
const WELCOMED_KEY = 'jobnavigator_welcomed'
// Two keys an older build wrote for the same fact (and the ones the Playwright
// harness seeds). Either one means the tour has already been seen, so neither an
// upgrade nor a test run replays it.
const LEGACY_WELCOMED = ['jobnavigator_v2_welcome_seen', 'jobnavigator_welcome_seen']
const alreadyWelcomed = () => {
  try {
    if (localStorage.getItem(WELCOMED_KEY) === '1') return true
    return LEGACY_WELCOMED.some((k) => localStorage.getItem(k) === 'true')
  } catch { return true }   // storage blocked: never strand someone behind a modal that can't record its own dismissal
}

// The upgrade overlay (NewUiModal). Versioned rather than boolean, so the
// next release can raise its own by bumping the value; anything else — an older
// mark, no mark — means this release has not been announced to this profile yet.
const NEWUI_KEY = 'jobnavigator_newui_seen'
const NEWUI_VERSION = '2.0.0'
// Keys only an EXISTING install can have written. A profile carrying any of them
// (or the welcome mark itself) used JobNavigator before the redesign, which is
// exactly the audience for "here is what moved" — a genuinely fresh profile has
// none of them and gets the first-run tour instead.
const RETURNING_KEYS = ['jobnavigator_api_key', 'jobnavigator_dark_mode', 'jobnavigator_v2_rail']
const isReturningUser = () => {
  try {
    if (alreadyWelcomed()) return true
    return RETURNING_KEYS.some((k) => localStorage.getItem(k) !== null)
  } catch { return false }
}
// Same guard as the tour: storage blocked → no overlay, since the dismissal
// could not be recorded and it would come back on every load.
const newUiPending = () => {
  try { return isReturningUser() && localStorage.getItem(NEWUI_KEY) !== NEWUI_VERSION } catch { return false }
}

// `/v2/feed?job=7#x` → `/feed?job=7#x`; bare `/v2` → `/`. Search and hash ride
// along because the query is what the old links actually carried. `/classic/…`
// (the v1 dashboard, removed in 3.0) lands the same way: every v1 path has a twin
// at the root, so `/classic/applications` becomes `/applications`.
function DropPrefix({ prefix }) {
  const { pathname, search, hash } = useLocation()
  const rest = pathname.replace(new RegExp(`^/${prefix}(?=/|$)`), '')
  return <Navigate to={(rest || '/') + search + hash} replace />
}

function App() {
  const [showLogin, setShowLogin] = useState(false)
  // Two ways in, one modal. LoginModal writes the session flag on a successful
  // sign-in (the key-set install), but a keyless first run never sees that
  // modal — so a *first visit* with no `jobnavigator_welcomed` mark shows the
  // onboarding too, which is the install it was written for (R4-T0-02).
  const [showWelcome, setShowWelcome] = useState(() => {
    try { if (sessionStorage.getItem('jn:welcome') === '1') return true } catch { /* ignore */ }
    return !alreadyWelcomed()
  })
  // At most one of the two overlays ever shows. The first-run tour wins: a
  // profile that is BOTH new and carrying a legacy key (the harness seeds an API
  // key into an otherwise empty context) is being onboarded, not upgraded — so
  // this stays mounted-but-unrendered and, crucially, unmarked, which is what
  // makes it appear on the visit after the tour was dismissed.
  const [showNewUi, setShowNewUi] = useState(newUiPending)

  // Handle ?cv= query param tracer links — redirect to /cv/{token} on backend
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const cvToken = params.get('cv')
    if (cvToken) {
      window.location.href = '/cv/' + encodeURIComponent(cvToken)
    }
  }, [])

  // On startup, sync localStorage API key to backend session cookie.
  useEffect(() => {
    const key = localStorage.getItem('jobnavigator_api_key') || ''
    axios.post('/api/auth/set-session', { api_key: key }, { withCredentials: true }).catch((err) => {
      if (err.response?.status === 401) setShowLogin(true)
    })
  }, [])

  // Global 401 handler — show login modal when any API call is rejected
  useEffect(() => {
    const handler = () => setShowLogin(true)
    window.addEventListener('jn:unauthorized', handler)
    return () => window.removeEventListener('jn:unauthorized', handler)
  }, [])

  // The account picker (MT-12). `required`: the API answered 401 account_required
  // (several accounts, none chosen in this browser) — it cannot be dismissed.
  // Otherwise the rail's switcher opened it on one account's PIN pad.
  const [picker, setPicker] = useState(null)   // null | { required: true } | { account }
  useEffect(() => {
    const onRequired = () => setPicker((p) => (p?.required ? p : { required: true }))
    const onPick = (e) => setPicker((p) => (p?.required ? p : { account: e.detail?.account || null }))
    window.addEventListener('jn:account-required', onRequired)
    window.addEventListener('jn:account-pick', onPick)
    return () => {
      window.removeEventListener('jn:account-required', onRequired)
      window.removeEventListener('jn:account-pick', onPick)
    }
  }, [])
  // QA F7 / R6-01: another tab switched this browser (or a write came back 409
  // account_changed) — a blocking reload notice; api.js has already stopped writes.
  const [changed, setChanged] = useState(null)
  useEffect(() => {
    const stop = listenForSwitches()
    const onChanged = (e) => setChanged(e.detail || {})
    window.addEventListener('jn:account-changed', onChanged)
    return () => { stop(); window.removeEventListener('jn:account-changed', onChanged) }
  }, [])
  const showPicker = !!picker && !showLogin && !changed

  const handleLoginSuccess = () => {
    setShowLogin(false)
    window.location.reload()
  }

  return (
    <BrowserRouter>
      <TitleSync />
      <Routes>
        {/* the app */}
        <Route path="/" element={<Shell />}>
          <Route index element={<Navigate to="feed" replace />} />
          <Route path="feed" element={<JobFeed />} />
          <Route path="resumes" element={<Resumes />} />
          <Route path="resumes/:id" element={<ResumeEditor />} />
          <Route path="companies" element={<Companies />} />
          <Route path="searches" element={<Searches />} />
          <Route path="applications" element={<Applications />} />
          <Route path="cover-letters" element={<CoverLetters />} />
          <Route path="cover-letters/:id" element={<CoverLetterEditor />} />
          <Route path="settings" element={<Settings />} />
          <Route path="persona" element={<Persona />} />
          <Route path="stats" element={<Stats />} />
        </Route>
        {/* labRoute returns null when design-base/ is absent; React skips a null child. */}
        {labRoute('ToastLab', '/toasts')}
        {labRoute('UiGallery', '/ui')}

        {/* /v2 was the staging prefix while the redesign was built beside v1;
            every screen it named now lives one level up, so old links (and
            bookmarks, and the harness) land on their twin, query and hash intact. */}
        <Route path="/v2" element={<DropPrefix prefix="v2" />} />
        <Route path="/v2/*" element={<DropPrefix prefix="v2" />} />
        {/* /classic was the v1 dashboard, removed in 3.0; old bookmarks keep working. */}
        <Route path="/classic" element={<DropPrefix prefix="classic" />} />
        <Route path="/classic/*" element={<DropPrefix prefix="classic" />} />
        {/* Every v1 root path (/applications, /resumes, …) is now the v2 screen of
            the same name — same feature, new UI — and v1 had no path without a
            twin, so nothing else needs a redirect. Anything left over is a typo
            or a dead bookmark: send it to the feed, not a blank shell. */}
        <Route path="*" element={<Navigate to="/feed" replace />} />
      </Routes>

      {showLogin && <LoginModal onSuccess={handleLoginSuccess} />}
      {showPicker && (
        // R6-04: keyed on the account, so a second shortcut while a PIN pad is up
        // opens a fresh picker on the NEW account's pad (not the old target's)
        <AccountPicker key={picker.required ? 'required' : (picker.account?.id || 'grid')}
          required={!!picker.required} account={picker.account || null}
          onClose={picker.required ? undefined : () => setPicker(null)} />
      )}
      {changed && !showLogin && <AccountChanged account={changed} />}
      {showWelcome && !showLogin && !showPicker && !changed && (
        <WelcomeModal onClose={() => {
          try { sessionStorage.removeItem('jn:welcome') } catch {}
          // durable, so the tour does not come back on the next visit
          try { localStorage.setItem(WELCOMED_KEY, '1') } catch {}
          setShowWelcome(false)
        }} />
      )}
      {showNewUi && !showWelcome && !showLogin && !showPicker && !changed && (
        <NewUiModal onClose={() => {
          try { localStorage.setItem(NEWUI_KEY, NEWUI_VERSION) } catch {}
          setShowNewUi(false)
        }} />
      )}
    </BrowserRouter>
  )
}

export default App
