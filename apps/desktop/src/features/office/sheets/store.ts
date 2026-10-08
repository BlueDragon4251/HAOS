import { createSession } from '../session.ts'
import { sheetsAdapter } from './adapter.ts'

/** Herald Sheets' open workbooks in this window. */
export const sheetsSession = createSession(sheetsAdapter)
