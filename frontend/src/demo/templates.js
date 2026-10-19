// The tracked résumé and cover-letter templates, bundled as raw text (the demo layer is copied into a
// JobNavigator checkout, so ../../../backend is the checkout's backend). Garamond is local-only and excluded.
const resume = import.meta.glob(['../../../backend/resume_templates/*/template.html.j2', '!../../../backend/resume_templates/garamond/**'],
  { query: '?raw', import: 'default', eager: true })
const letter = import.meta.glob(['../../../backend/cover_letter_templates/*/template.html.j2', '!../../../backend/cover_letter_templates/garamond/**'],
  { query: '?raw', import: 'default', eager: true })

const byId = (mods) => Object.fromEntries(Object.entries(mods).map(([p, src]) => [p.split('/').slice(-2)[0], src]))

export const RESUME_TEMPLATES = byId(resume)
export const COVER_LETTER_TEMPLATES = byId(letter)
