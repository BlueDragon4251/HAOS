/** Render only theme data in a disposable renderer with no preload or network. */
import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { app, BrowserWindow, session } from 'electron'
import { contrast, paletteVars, schemeOf, toHex, validateTheme, type ThemePreview } from '../../shared/theme.ts'
import { rendererIndex } from '../paths.ts'
import { readThemeFile, type ThemeBundle } from './revisions.ts'

const escape = (value: string) => value.replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character] as string))

function shellCss(): Buffer {
  const dir = path.join(path.dirname(rendererIndex()), 'assets')
  const files = fs.readdirSync(dir).filter(name => /^index-[\w-]+\.css$/.test(name))
  if (files.length !== 1) throw new Error('Build the native renderer before previewing themes')
  const css = readThemeFile(path.join(dir, files[0]), 2 * 1024 * 1024)
  if (/<\/style/i.test(css.toString('utf8'))) throw new Error('Invalid native renderer stylesheet')
  return css
}

interface Rendered {
  width: number
  height: number
  background: [number, number, number, number]
  foreground: [number, number, number, number]
  foregroundBackground: [number, number, number, number]
  heading: [number, number, number, number]
  secondary: [number, number, number, number]
  accent: [number, number, number, number]
  accentText: [number, number, number, number]
  controlsVisible: boolean
  noNode: boolean
  rasterDecoded: boolean
}

let rendering = false

export async function previewTheme(bundle: Omit<ThemeBundle, 'revision'> & { revision?: string }, panels = false): Promise<ThemePreview> {
  if (rendering) throw new Error('A theme preview is already running')
  rendering = true
  try { return await renderTheme(bundle, panels) }
  finally { rendering = false }
}

async function renderTheme(bundle: Omit<ThemeBundle, 'revision'> & { revision?: string }, panels: boolean): Promise<ThemePreview> {
  const problem = validateTheme(bundle.spec)
  if (problem) throw new Error(problem)
  if (['no-sandbox', 'disable-seccomp-filter-sandbox', 'disable-gpu-sandbox'].some(flag => app.commandLine.hasSwitch(flag))) {
    throw new Error('Theme validation requires an enabled Chromium sandbox')
  }
  const css = shellCss()
  const spec = bundle.spec
  const scheme = schemeOf(spec.colors, spec.shell?.scheme)
  const variables = spec.shell?.theme ? '' : Object.entries(paletteVars(spec.colors, { scheme, panels })).map(([key, value]) => `${key}:${value}`).join(';')
  let raster = ''
  if (spec.wallpaper && spec.wallpaper !== 'default') {
    const types: Record<string, string> = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.avif': 'image/avif' }
    const image = readThemeFile(path.join(bundle.dir, spec.wallpaper), 25 * 1024 * 1024)
    raster = `<img id="wallpaper" alt="Theme wallpaper preview" src="data:${types[path.extname(spec.wallpaper).toLowerCase()]};base64,${image.toString('base64')}" style="width:100%;height:120px;object-fit:cover;border-radius:12px">`
  }
  const html = `<!doctype html><html data-theme="${spec.shell?.theme || 'ocean'}" data-accent="${spec.shell?.accent || 'blue'}" data-scheme="${scheme}">
<head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none';style-src 'unsafe-inline';img-src data:;connect-src 'none';script-src 'none';font-src 'none';form-action 'none';base-uri 'none'">
<style>${css.toString('utf8')}</style><style>:root{${variables}}body{margin:0;padding:32px;background:var(--color-bg);color:var(--color-fg);font:16px system-ui}h1{font-size:26px}p{margin:16px 0}.card{padding:24px;margin-top:20px}button{background:var(--color-accent);color:var(--color-accent-fg);padding:12px 24px;border:0;border-radius:8px;font:inherit}.secondary{color:var(--color-fg-3)}.swatches{display:flex;gap:12px;margin:20px 0}.swatches span{height:32px;width:80px;border-radius:8px}</style></head>
<body><h1 id="heading">${escape(spec.label || spec.name)}</h1><p class="secondary" id="secondary">Isolated theme preview · no mission is running in this window.</p>
<section class="glass-card card"><p id="foreground">Readable conversation and mission text</p><div class="swatches"><span style="background:var(--color-accent)"></span><span style="background:var(--color-ok)"></span><span style="background:var(--color-warn)"></span></div><button id="button" type="button">Example control</button></section>${raster}</body></html>`
  const url = `data:text/html;base64,${Buffer.from(html).toString('base64')}`
  const isolated = session.fromPartition(`haos-theme-preview-${randomUUID()}`, { cache: false })
  isolated.setPermissionRequestHandler((_contents, _permission, respond) => respond(false))
  isolated.setPermissionCheckHandler(() => false)
  isolated.webRequest.onBeforeRequest((details, respond) => respond({ cancel: details.url !== url && !details.url.startsWith('data:image/') }))
  isolated.on('will-download', event => event.preventDefault())
  const win = new BrowserWindow({ width: 960, height: 640, useContentSize: true, show: false, frame: false, resizable: false,
    backgroundColor: spec.colors.bg,
    webPreferences: { session: isolated, sandbox: true, contextIsolation: true, nodeIntegration: false,
      webSecurity: true, offscreen: true, backgroundThrottling: false } })
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', event => event.preventDefault())
  let deadline: ReturnType<typeof setTimeout> | undefined
  let phase = 'load'
  try {
    return await Promise.race([
      (async () => {
        await win.loadURL(url)
        phase = 'layout'
        const rendered = await win.webContents.executeJavaScript(`(async()=>{
          const image=document.getElementById('wallpaper');let rasterDecoded=true;
          if(image){try{await image.decode();rasterDecoded=image.naturalWidth>0&&image.naturalHeight>0&&image.naturalWidth<=8192&&image.naturalHeight<=8192&&image.naturalWidth*image.naturalHeight<=16777216}catch{rasterDecoded=false}}
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
          const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');
          const body=getComputedStyle(document.body),button=getComputedStyle(document.getElementById('button'));
          const sample=(color,bg=body.backgroundColor)=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=bg;ctx.fillRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data]};
          const backgroundOf=el=>{const ancestors=[];for(let node=el;node;node=node.parentElement)ancestors.unshift(node);ctx.clearRect(0,0,1,1);for(const node of ancestors){ctx.fillStyle=getComputedStyle(node).backgroundColor;ctx.fillRect(0,0,1,1)}return [...ctx.getImageData(0,0,1,1).data]};
          const foreground=document.getElementById('foreground'),foregroundBackground=backgroundOf(foreground);
          const foregroundColor=sample(getComputedStyle(foreground).color,'rgba('+foregroundBackground.slice(0,3).join(',')+','+(foregroundBackground[3]/255)+')');
          const visible=['heading','foreground','secondary','button'].every(id=>{const el=document.getElementById(id),r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&s.visibility!=='hidden'&&s.display!=='none'&&Number(s.opacity)>0});
          return {width:innerWidth,height:innerHeight,background:sample(body.backgroundColor),foreground:foregroundColor,foregroundBackground,heading:sample(getComputedStyle(document.getElementById('heading')).color),secondary:sample(getComputedStyle(document.getElementById('secondary')).color),accent:sample(button.backgroundColor),accentText:sample(button.color,button.backgroundColor),controlsVisible:visible,noNode:typeof process==='undefined'&&typeof require==='undefined',rasterDecoded};
        })()`) as Rendered
        phase = 'capture'
        const screenshot = await win.webContents.capturePage({ x: 0, y: 0, width: 960, height: 640 })
        const size = screenshot.getSize()
        const bitmap = screenshot.toBitmap()
        const png = screenshot.toPNG()
        phase = 'sandbox'
        const hex = (color: number[]) => toHex({ r: color[0], g: color[1], b: color[2] })
        const status = process.platform === 'linux' ? fs.readFileSync(`/proc/${win.webContents.getOSProcessId()}/status`, 'utf8') : ''
        const restricted = process.platform !== 'linux' || (/^NoNewPrivs:\s*1$/m.test(status) && /^Seccomp:\s*2$/m.test(status) && /^CapEff:\s*0+$/m.test(status))
        const checks = {
          sandbox: restricted && rendered.noNode,
          rendered: rendered.width === 960 && rendered.height === 640 && size.width === 960 && size.height === 640 && png.length > 1000
            && bitmap[2] === rendered.background[0] && bitmap[1] === rendered.background[1] && bitmap[0] === rendered.background[2],
          controlsVisible: rendered.controlsVisible,
          textContrast: contrast(hex(rendered.foreground), hex(rendered.foregroundBackground)) >= 4.5
            && contrast(hex(rendered.heading), hex(rendered.background)) >= 4.5,
          secondaryContrast: contrast(hex(rendered.secondary), hex(rendered.background)) >= 3,
          controlContrast: contrast(hex(rendered.accentText), hex(rendered.accent)) >= 3,
          rasterDecoded: rendered.rasterDecoded
        }
        return { revision: bundle.revision || undefined, passed: Object.values(checks).every(Boolean), checks,
          width: size.width, height: size.height, png: screenshot.toDataURL(),
          screenshotSha256: createHash('sha256').update(png).digest('hex'),
          stylesheetSha256: createHash('sha256').update(css).digest('hex') }
      })(),
      new Promise<never>((_resolve, reject) => { deadline = setTimeout(() => reject(new Error('Isolated theme preview timed out')), 15000) })
    ])
  } catch (error) {
    if (process.env.HAOS_DISPOSABLE_SCREEN_TEST === '1') fs.writeSync(2, `HAOS_THEME_PREVIEW_FAILURE ${phase} ${error instanceof Error ? error.name : 'UnknownError'}\n`)
    // load/capture errors can contain the complete private data URL.
    throw new Error('Isolated theme preview failed; the current theme was not changed')
  } finally {
    if (deadline) clearTimeout(deadline)
    if (!win.isDestroyed()) win.destroy()
    await isolated.clearStorageData()
  }
}
