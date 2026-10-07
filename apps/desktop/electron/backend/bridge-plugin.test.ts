import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { bridgeLinkPlan, ensureBridgePlugin, failureReason } from './bridge-plugin.ts'

const bundled = '/Applications/Herald OS.app/Contents/Resources/herald-os-bridge'

describe('bridgeLinkPlan', () => {
  it('links a missing plugin and keeps what the person set up', () => {
    expect(bridgeLinkPlan({ kind: 'missing' }, bundled)).toBe('create')
    expect(bridgeLinkPlan({ kind: 'folder' }, bundled)).toBe('keep')
    expect(bridgeLinkPlan({ kind: 'link', target: bundled, exists: true }, bundled)).toBe('keep')
    // A checkout's link, from npm run bootstrap.
    expect(bridgeLinkPlan({ kind: 'link', target: '/Users/sam/Herald-OS/plugins/herald-os-bridge', exists: true }, bundled)).toBe('keep')
  })

  it('moves a link that leads nowhere or into another copy of the app', () => {
    expect(bridgeLinkPlan({ kind: 'link', target: '/Users/sam/old/plugins/herald-os-bridge', exists: false }, bundled)).toBe('replace')
    const translocated = '/private/var/folders/x/AppTranslocation/1/d/Herald OS.app/Contents/Resources/herald-os-bridge'
    expect(bridgeLinkPlan({ kind: 'link', target: translocated, exists: true }, bundled)).toBe('replace')
  })
})

describe('failureReason', () => {
  it("keeps Hermes's ✗ lines and drops its warnings", () => {
    const warning = '⚠ install out of sync (ffmpeg: not installed or outdated) — run `hermes pm install`'
    expect(failureReason(`${warning}\n✗ Unknown toolset 'herald_os'`)).toBe("✗ Unknown toolset 'herald_os'")
    // A wrapped message without a ✗ line reads as one sentence.
    expect(failureReason(`${warning}\nNo plugin named 'herald-os-bridge'. Run \`hermes plugins list\`\nto see the exact names.`)).toBe("No plugin named 'herald-os-bridge'. Run `hermes plugins list` to see the exact names.")
  })
})

describe('ensureBridgePlugin', () => {
  const saved = process.env.HERMES_HOME
  let root = ''

  afterEach(() => {
    process.env.HERMES_HOME = saved
    fs.rmSync(root, { recursive: true, force: true })
  })

  /** An app bundle, a Hermes home, and a `hermes` that logs its arguments and answers `config get` with `toolSearch`. */
  function setUp(script = '', toolSearch = 'auto') {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-'))
    const resources = path.join(root, 'Herald OS.app', 'Contents', 'Resources')
    fs.mkdirSync(path.join(resources, 'herald-os-bridge'), { recursive: true })
    fs.writeFileSync(path.join(resources, 'herald-os-bridge', 'plugin.yaml'), 'name: herald-os-bridge\n')
    process.env.HERMES_HOME = path.join(root, 'hermes')
    const calls = path.join(root, 'calls.txt')
    const body = `echo "$*" >> '${calls}'; ${script} [ "$1 $2" = "config get" ] && echo '${toolSearch}'; exit 0`
    const runtime = { kind: 'path' as const, label: 'test', command: ['/bin/sh', '-c', body, 'hermes'] }
    const herald = (name: string) => path.join(root, 'hermes', 'herald-os', name)

    return { resources, runtime, calls: () => fs.readFileSync(calls, 'utf8').trim().split('\n'), herald }
  }

  it("links the app's copy into the Hermes home, enables it once and keeps Tool Search's value", async () => {
    const { resources, runtime, calls, herald } = setUp()

    expect(await ensureBridgePlugin(runtime, resources)).toBeNull()
    const link = path.join(root, 'hermes', 'plugins', 'herald-os-bridge')
    expect(fs.readlinkSync(link)).toBe(path.join(resources, 'herald-os-bridge'))
    expect(calls()).toEqual(['plugins enable herald-os-bridge', 'tools enable herald_os', 'config get tools.tool_search.enabled', 'config set tools.tool_search.enabled off'])
    expect(fs.readFileSync(herald('tool-search-before'), 'utf8')).toBe('auto\n')

    // Already linked: nothing to do, and Hermes is not asked again.
    await ensureBridgePlugin(runtime, resources)
    expect(calls()).toHaveLength(4)
  })

  it('leaves Tool Search alone when it is off already and keeps the first value it found', async () => {
    const { resources, runtime, calls, herald } = setUp('', 'off')
    fs.mkdirSync(path.dirname(herald('tool-search-before')), { recursive: true })
    fs.writeFileSync(herald('tool-search-before'), 'on\n')

    expect(await ensureBridgePlugin(runtime, resources)).toBeNull()
    expect(calls()).not.toContain('config set tools.tool_search.enabled off')
    expect(fs.readFileSync(herald('tool-search-before'), 'utf8')).toBe('on\n')
  })

  it('stops at a failed step, says why, and tries again on the next start', async () => {
    const { resources, runtime, calls, herald } = setUp('exit 1;')

    expect(await ensureBridgePlugin(runtime, resources)).toMatch(/^hermes plugins enable herald-os-bridge failed/)
    await ensureBridgePlugin(runtime, resources)
    expect(calls()).toEqual(['plugins enable herald-os-bridge', 'plugins enable herald-os-bridge'])
    expect(fs.existsSync(herald('bridge-enabled'))).toBe(false)
  })

  it('counts a ✗ line as a failure even when hermes exits 0', async () => {
    const { resources, runtime, calls, herald } = setUp(`[ "$1" = tools ] && echo "✗ Unknown toolset 'herald_os'";`)

    expect(await ensureBridgePlugin(runtime, resources)).toContain("Unknown toolset 'herald_os'")
    expect(calls()).toEqual(['plugins enable herald-os-bridge', 'tools enable herald_os'])
    expect(fs.existsSync(herald('tool-search-before'))).toBe(false)
    expect(fs.existsSync(herald('bridge-enabled'))).toBe(false)
  })

  it('leaves a link the person removed after setup removed', async () => {
    const { resources, runtime, calls, herald } = setUp()
    await ensureBridgePlugin(runtime, resources)
    const link = path.join(root, 'hermes', 'plugins', 'herald-os-bridge')
    fs.rmSync(link)

    expect(await ensureBridgePlugin(runtime, resources)).toBeNull()
    expect(fs.existsSync(link)).toBe(false)
    expect(calls()).toHaveLength(4)
    expect(fs.existsSync(herald('bridge-enabled'))).toBe(true)
  })

  it('does nothing without a bundled copy (development)', async () => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-'))
    process.env.HERMES_HOME = path.join(root, 'hermes')
    expect(await ensureBridgePlugin({ kind: 'path', label: 'test', command: ['false'] }, path.join(root, 'none'))).toBeNull()
    expect(fs.existsSync(path.join(root, 'hermes', 'plugins'))).toBe(false)
  })
})
