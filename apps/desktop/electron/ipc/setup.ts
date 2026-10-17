import { ipcMain } from 'electron'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { type HaosRegion, DEFAULT_HAOS_REGION, validHaosRegion } from '../../shared/region.ts'
import { IPC, type SetupResult, type SetupState } from '../../shared/ipc.ts'
import { log } from '../log.ts'
import { loadPty } from './terminal.ts'

/*
 * First-boot setup on the Herald OS image: the image's first boot made the account (no password)
 * and installed Hermes; the person names it, sets a password, joins Wi-Fi and signs in to Hermes.
 * Nothing here needs root: `passwd` changes the person's own password (the current one is empty on
 * a new account), and the name Herald greets with lives in ~/.config/herald-os/name.
 */

const HAOS_ENABLED = '/etc/haos/enabled'
const FIRSTBOOT_DONE = '/var/lib/herald-os/firstboot-done'
const configDir = () => path.join(os.homedir(), '.config', 'herald-os')
const doneFile = () => path.join(configDir(), 'setup-done')
export const nameFile = (): string => path.join(configDir(), 'name')

const REGION_FILE = () => path.join(configDir(), 'region.json')
const LOCALE_FILE = () => path.join(configDir(), 'locale')

// Unlike application preferences, the keyboard compositor renderer depends on
// this exact protected shape. There are no caller-selected paths or commands.
export function readRegion(): HaosRegion {
  try {
    const parsed: unknown = JSON.parse(fs.readFileSync(REGION_FILE(), 'utf8'))
    return validHaosRegion(parsed) ? parsed : DEFAULT_HAOS_REGION
  } catch {
    return DEFAULT_HAOS_REGION
  }
}

function writeRegionFile(file: string, data: string): void {
  const dir = path.dirname(file)
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
  if (fs.existsSync(file) && fs.lstatSync(file).isSymbolicLink()) throw new Error('Refusing a symbolic-link region setting')
  const temporary = path.join(dir, `.haos-region-${randomBytes(8).toString('hex')}`)
  try {
    fs.writeFileSync(temporary, data, { mode: 0o600, flag: 'wx' })
    fs.renameSync(temporary, file)
  } finally {
    try { fs.unlinkSync(temporary) } catch { /* already renamed */ }
  }
}

export function saveRegion(value: unknown): SetupResult {
  if (process.platform !== 'linux') return { ok: false, error: 'Regional configuration is supported only on Linux.' }
  if (!validHaosRegion(value)) return { ok: false, error: 'Unsupported language or keyboard layout.' }
  const region = value
  try {
    writeRegionFile(REGION_FILE(), JSON.stringify(region) + '\n')
    // The session launcher reads this allowlisted locale, so applications and
    // desktop services use it on the next session. Never modify root/owner files.
    writeRegionFile(LOCALE_FILE(), region.language + '\n')
    // User systemd services use the same locale on their next activation.
    writeRegionFile(path.join(os.homedir(), '.config', 'environment.d', '90-haos-locale.conf'),
                    `LANG=${region.language}\nLANGUAGE=${region.language.split('_')[0]}\n`)
    // The real niri renderer consumes region.json; it atomically reloads when
    // this config changes, applying the keyboard immediately without root.
    execFileSync('herald-os', ['keymap', 'apply'], { timeout: 8000, stdio: 'pipe' })
    return { ok: true }
  } catch (error) {
    log('setup', `regional configuration could not be applied: ${error instanceof Error ? error.message : String(error)}`)
    return { ok: false, error: 'Cannot activate keyboard layout. Please try again or use the terminal.' }
  }
}

/** In a managed image the one-shot root service must have validated a separate
 * administrator plus recovery before the observer may dismiss first-run.
 * This is status-only: no renderer IPC ever receives root/owner privileges.
 */
function ownerReady(): boolean {
  try {
    execFileSync('/usr/bin/systemctl', ['is-active', '--quiet', 'haos-owner-ready.service'],
      { timeout: 3000, stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

export function setupState(): SetupState {
  const image = fs.existsSync(FIRSTBOOT_DONE) || process.env.HERALD_OS_FORCE_SETUP === '1'
  let name = ''

  try {
    name = fs.readFileSync(nameFile(), 'utf8').trim()
  } catch {
    // Not named yet.
  }

  const managed = fs.existsSync(HAOS_ENABLED)
  const ready = managed ? ownerReady() : true
  return { needed: process.platform === 'linux' && image && (!fs.existsSync(doneFile()) || !ready),
    haosManaged: managed, ownerReady: ready, user: os.userInfo().username, name }
}

/** What `passwd` asks (LANG=C), most specific first: "Retype new password:" also ends in "new password:". */
export function passwdReply(screen: string, password: string, current: string): string | null {
  const tail = screen.slice(-160).toLowerCase()

  if (/retype new password:\s*$/.test(tail)) {
    return `${password}\r`
  }

  if (/new password:\s*$/.test(tail)) {
    return `${password}\r`
  }

  if (/(current|\(current\) unix|old) password:\s*$/.test(tail) || /password:\s*$/.test(tail)) {
    return `${current}\r`
  }

  return null
}

/** `passwd` for this account, answered through a terminal; the reason when it refuses (too short, too simple). */
export function changePassword(password: string, current = ''): Promise<SetupResult> {
  const pty = loadPty()

  if (!pty) {
    return Promise.resolve({ ok: false, error: 'The terminal library is missing, so the password cannot be set here; run `passwd` in a terminal.' })
  }

  return new Promise(resolve => {
    const child = pty.spawn('passwd', [], { name: 'xterm', cols: 100, rows: 24, cwd: os.homedir(), env: { ...process.env, LANG: 'C', LC_ALL: 'C' } })
    let screen = ''
    let refusal = ''
    const timer = setTimeout(() => {
      child.kill()
      resolve({ ok: false, error: 'passwd did not finish' })
    }, 30_000)

    child.onData(data => {
      screen += data
      const bad = /BAD PASSWORD: ([^\r\n]+)/.exec(screen)

      if (bad?.[1]) {
        // pwquality refused it and would ask again; stop and say why.
        refusal = bad[1].trim()
        child.kill()

        return
      }

      const reply = passwdReply(screen, password, current)

      if (reply !== null) {
        screen = ''
        child.write(reply)
      }
    })
    child.onExit(({ exitCode }) => {
      clearTimeout(timer)

      if (exitCode === 0) {
        resolve({ ok: true })
      } else {
        const last = screen.split(/\r?\n/).map(line => line.trim()).filter(Boolean).pop() ?? ''
        log('setup', `passwd exited ${exitCode}: ${refusal || last}`)
        resolve({ ok: false, error: refusal ? `That password was refused: ${refusal}.` : last || 'passwd refused the change' })
      }
    })
  })
}

export function registerSetupIpc(): void {
  ipcMain.handle(IPC.setupState, () => setupState())
  ipcMain.handle(IPC.setupRegionGet, () => readRegion())
  ipcMain.handle(IPC.setupRegionSet, (_event, region: unknown) => saveRegion(region))
  ipcMain.handle(IPC.setupName, (_event, name: string) => {
    const clean = String(name ?? '').replace(/[\r\n:]/g, ' ').trim().slice(0, 64)
    fs.mkdirSync(configDir(), { recursive: true })
    fs.writeFileSync(nameFile(), `${clean}\n`)

    return { ok: true } satisfies SetupResult
  })
  ipcMain.handle(IPC.setupPassword, (_event, password: string) => {
    if (fs.existsSync(HAOS_ENABLED)) {
      return { ok: false, error: 'HAOS owner credentials are created on the trusted tty2 console. The observer account must remain locked.' } satisfies SetupResult
    }
    const value = String(password ?? '')

    if (value.length < 8 || /[\r\n]/.test(value)) {
      return { ok: false, error: 'Use at least 8 characters.' } satisfies SetupResult
    }

    return changePassword(value)
  })
  // `later`: set up for someone else; setup shows again for them at the next start.
  ipcMain.handle(IPC.setupFinish, (_event, options: { later?: boolean } = {}) => {
    if (fs.existsSync(HAOS_ENABLED) && !ownerReady()) {
      return { ok: false, error: 'Administrator und Wiederherstellungscodes sind noch nicht geprüft. HAOS bleibt im Einrichtungsmodus.' } satisfies SetupResult
    }
    if (!options.later) {
      fs.mkdirSync(configDir(), { recursive: true })
      fs.writeFileSync(doneFile(), `${new Date().toISOString()}\n`)
    }

    return { ok: true } satisfies SetupResult
  })
}
