import { createSession } from '../session.ts'
import { docsAdapter } from './adapter.ts'

/** Herald Docs' open documents in this window. */
export const docsSession = createSession(docsAdapter)
