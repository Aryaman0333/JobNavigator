// Registers every demo route module on the server's route table.
import { clearRoutes } from '../server.js'
import * as auth from './auth.js'
import * as monitor from './monitor.js'
import * as jobs from './jobs.js'
import * as applications from './applications.js'
import * as searches from './searches.js'
import * as companies from './companies.js'
import * as resumes from './resumes.js'
import * as coverLetters from './coverLetters.js'
import * as persona from './persona.js'
import * as settings from './settings.js'
import * as stats from './stats.js'
import * as ai from './ai.js'
import * as documents from './documents.js'

const MODULES = [auth, monitor, jobs, applications, searches, companies, resumes, coverLetters, persona, settings, stats, ai, documents]

export function registerAll() {
  clearRoutes()
  MODULES.forEach((m) => m.register())
}
