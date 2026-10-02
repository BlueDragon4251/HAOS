import { describe, expect, it } from 'vitest'
import { detectLocalUrl, emptyStudio, noteDiskChange, reduceStudioEvent, resolvePath, setStudioPreview, type StudioEvent, type StudioState } from './studio-model.ts'

const HOME = '/Users/me'
const CWD = '/Users/me/Projects/salon'
const run = (events: StudioEvent[], start: StudioState = emptyStudio('s1', HOME, CWD)) => events.reduce((state, event) => reduceStudioEvent(state, event, 1), start)

describe('resolvePath', () => {
  it('resolves relative, home and dotted paths', () => {
    expect(resolvePath('index.html', CWD, HOME)).toBe('/Users/me/Projects/salon/index.html')
    expect(resolvePath('./src/../css/site.css', CWD, HOME)).toBe('/Users/me/Projects/salon/css/site.css')
    expect(resolvePath('~/notes.md', CWD, HOME)).toBe('/Users/me/notes.md')
    expect(resolvePath('/tmp/x', CWD, HOME)).toBe('/tmp/x')
  })
})

describe('detectLocalUrl', () => {
  it('finds dev server addresses through colour codes', () => {
    expect(detectLocalUrl('  \u001b[32m➜\u001b[39m  \u001b[1mLocal\u001b[22m:   \u001b[36mhttp://localhost:\u001b[1m5173\u001b[22m/\u001b[39m')).toBe('http://localhost:5173/')
    expect(detectLocalUrl('Serving HTTP on 0.0.0.0 port 8000 (http://0.0.0.0:8000/) ...')).toBe('http://localhost:8000/')
    expect(detectLocalUrl('Serving HTTP on :: port 8000 (http://[::]:8000/) ...')).toBe('http://localhost:8000/')
    expect(detectLocalUrl('see https://example.com')).toBeNull()
  })
})

describe('reduceStudioEvent', () => {
  it('shows a file while it is being written, then marks the changed lines', () => {
    const writing = run([{ type: 'tool.start', payload: { tool_id: 't1', name: 'write_file', args: { path: 'index.html', content: '<h1>Salon</h1>' } } }])
    const path = `${CWD}/index.html`
    expect(writing.activeFile).toBe(path)
    expect(writing.files[path]).toMatchObject({ status: 'writing', pending: '<h1>Salon</h1>' })
    expect(writing.status).toBe('Writing index.html')

    const written = run([{ type: 'tool.complete', payload: { tool_id: 't1', name: 'write_file', args: { path: 'index.html' }, result: '{"bytes_written": 14}', inline_diff: '--- /dev/null\n+++ b/index.html\n@@ -0,0 +1 @@\n+<h1>Salon</h1>\n' } }], writing)
    expect(written.files[path]).toMatchObject({ status: 'written', changedLines: [] })
    expect(written.files[path].pending).toBeUndefined()
    expect(written.revision).toBe(1)
  })

  it('tracks edits from a patch and failed writes', () => {
    const edited = run([
      { type: 'tool.start', payload: { tool_id: 't2', name: 'patch', args: { path: 'styles.css', old_string: 'black', new_string: 'hotpink' } } },
      { type: 'tool.complete', payload: { tool_id: 't2', name: 'patch', args: { path: 'styles.css' }, result: { success: true }, inline_diff: '--- a/styles.css\n+++ b/styles.css\n@@ -3 +3 @@\n-  color: black;\n+  color: hotpink;\n' } }
    ])
    expect(edited.files[`${CWD}/styles.css`]).toMatchObject({ status: 'edited', changedLines: [3] })

    const failed = run([{ type: 'tool.complete', payload: { tool_id: 't3', name: 'write_file', args: { path: 'x.txt' }, result: { error: 'denied' } } }])
    expect(failed.files[`${CWD}/x.txt`].status).toBe('failed')
  })

  it('logs commands and follows background processes to their dev server', () => {
    const state = run([
      { type: 'tool.start', payload: { tool_id: 'c1', name: 'terminal', args: { command: 'npm install' } } },
      { type: 'tool.complete', payload: { tool_id: 'c1', name: 'terminal', args: { command: 'npm install' }, result: { output: 'added 12 packages', exit_code: 0 } } },
      { type: 'tool.start', payload: { tool_id: 'c2', name: 'terminal', args: { command: 'npm run dev', background: true } } },
      { type: 'tool.complete', payload: { tool_id: 'c2', name: 'terminal', args: { command: 'npm run dev', background: true }, result: { output: 'Background process started', session_id: 'proc_1', exit_code: 0 } } },
      { type: 'agent.terminal.output', payload: { process_id: 'proc_1', chunk: '  Local:   http://localhost:5173/\n' } }
    ])
    expect(state.commands.map(c => [c.command, c.status])).toEqual([['npm install', 'done'], ['npm run dev', 'background']])
    expect(state.processes.proc_1).toMatchObject({ command: 'npm run dev', running: true })
    expect(state.processes.proc_1.output).toContain('5173')
    expect(state.previewUrl).toBe('http://localhost:5173/')

    const closed = run([{ type: 'terminal.close', payload: { process_id: 'proc_1' } }], state)
    expect(closed.processes.proc_1.running).toBe(false)
  })

  it('never lets a detected address replace a preview chosen on purpose', () => {
    const chosen = setStudioPreview(emptyStudio('s1', HOME, CWD), 'http://localhost:3000/')
    const after = run([{ type: 'agent.terminal.output', payload: { process_id: 'p', chunk: 'http://localhost:9999' } }], chosen)
    expect(after.previewUrl).toBe('http://localhost:3000/')
  })

  it('marks failed commands and tracks the session folder and running state', () => {
    const state = run([
      { type: 'session.info', payload: { cwd: '/tmp/other', running: true } },
      { type: 'tool.complete', payload: { tool_id: 'c9', name: 'terminal', args: { command: 'false' }, result: { output: '', exit_code: 1 } } },
      { type: 'message.complete', payload: {} }
    ])
    expect(state.cwd).toBe('/tmp/other')
    expect(state.commands[0].status).toBe('failed')
    expect(state.running).toBe(false)
  })

  it('shows that Hermes is composing a file until the write starts', () => {
    const composing = run([{ type: 'tool.generating', payload: { name: 'write_file' } }])
    expect(composing).toMatchObject({ status: 'Writing a file…', running: true, generating: { tool: 'write_file' } })
    const started = run([{ type: 'tool.start', payload: { tool_id: 't', name: 'write_file', args: { path: 'a.css', content: 'x' } } }], composing)
    expect(started.generating).toBeNull()
    expect(started.status).toBe('Writing a.css')
  })

  it('lists files changed on disk by other programs', () => {
    const state = noteDiskChange(emptyStudio('s1', HOME, CWD), [`${CWD}/package.json`], 1)
    expect(state.files[`${CWD}/package.json`].status).toBe('changed')
    expect(state.revision).toBe(1)
  })
})
