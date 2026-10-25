// Whether a job reaches the employer's own site (backend scraper/_shared/link_kinds.py):
// the feed's Link menu, the tag on jobs without a direct link, and the link Open uses.

export const LINK_KINDS = [
  { key: 'direct', label: 'Direct' },
  { key: 'board', label: 'Board link', title: "No link to the employer's own site yet" },
  { key: 'easy_apply', label: 'Easy Apply', title: 'Apply on LinkedIn only; the employer has no site for it' },
]

// { text, title } for a job without a direct link, else null.
export const linkTag = (job) => {
  const k = LINK_KINDS.find((x) => x.key === job?.link_kind)
  return k && k.title ? { text: k.label, title: k.title } : null
}

// The employer's link when the job has one (`link`), else its own link.
export const openLink = (job) => (job && (job.link || job.url)) || ''
