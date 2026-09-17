import { execFile } from 'node:child_process'

export interface ExecResult {
  stdout: string
  stderr: string
  code: number
}

/** Small promise wrapper around execFile that never throws on non-zero exit. */
export function run(command: string, args: string[], timeoutMs = 8000): Promise<ExecResult> {
  return new Promise(resolve => {
    execFile(command, args, { timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024, encoding: 'utf8' }, (error, stdout, stderr) => {
      const rawCode: unknown = error ? (error as { code?: unknown }).code : 0
      const code = typeof rawCode === 'number' ? rawCode : error ? 1 : 0
      resolve({ stdout: String(stdout ?? ''), stderr: String(stderr ?? ''), code })
    })
  })
}
