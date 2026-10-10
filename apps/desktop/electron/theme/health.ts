import type { BrowserWindow } from 'electron'
import fs from 'node:fs'
import type { HeraldOSPrefs } from '../../shared/ipc.ts'
import { schemeOf } from '../../shared/theme.ts'

/** Only the caller's verified shell windows, never mission documents or owner dialogs. */
export async function verifyThemeShell(windows: BrowserWindow[], next: HeraldOSPrefs): Promise<boolean> {
  if (!windows.length) return false
  const expression = `(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const root = document.documentElement, body = document.body;
    const style = body && getComputedStyle(body), bounds = body && body.getBoundingClientRect();
    return {theme: root.dataset.theme, accent: root.dataset.accent, scheme: root.dataset.scheme,
      noNode: typeof process === 'undefined' && typeof require === 'undefined',
      rendered: !!body && !!bounds && bounds.width > 0 && bounds.height > 0 && style.display !== 'none' && style.visibility === 'visible' && Number(style.opacity) > 0};
  })()`
  let timeout: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      Promise.all(windows.map(async win => {
        if (win.isDestroyed() || !win.isVisible()) return false
        const state = await win.webContents.executeJavaScript(expression) as {theme?: string; accent?: string; scheme?: string; rendered?: boolean; noNode?: boolean}
        const status = process.platform === 'linux' ? fs.readFileSync(`/proc/${win.webContents.getOSProcessId()}/status`, 'utf8') : ''
        const restricted = process.platform !== 'linux' || (/^NoNewPrivs:\s*1$/m.test(status) && /^Seccomp:\s*2$/m.test(status) && /^CapEff:\s*0+$/m.test(status))
        if (!restricted || !state.noNode || !state.rendered || state.theme !== next.theme || state.accent !== next.accent
            || state.scheme !== (next.themeColors ? schemeOf(next.themeColors, next.themeScheme) : 'dark')) return false
        const image = await win.webContents.capturePage()
        const size = image.getSize()
        return !image.isEmpty() && size.width > 0 && size.height > 0
      })).then(results => results.every(Boolean)),
      new Promise<boolean>(resolve => { timeout = setTimeout(() => resolve(false), 3_000) })
    ])
  } catch { return false }
  finally { if (timeout) clearTimeout(timeout) }
}
