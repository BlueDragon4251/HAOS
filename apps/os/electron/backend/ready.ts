const READY_RE = /^(?:HERMES_BACKEND_READY|HERMES_DASHBOARD_READY)\s+port=(\d+)\s*$/

/** Parse the machine sentinel `hermes serve` writes to fd 1 once it is listening. */
export function parseReadyLine(line: string): number | null {
  const match = READY_RE.exec(line.trim())

  if (!match) {
    return null
  }

  const port = Number(match[1])

  return Number.isInteger(port) && port > 0 && port < 65536 ? port : null
}

/** Incremental line splitter for a byte stream; returns complete lines, keeps the remainder. */
export class LineBuffer {
  private rest = ''

  push(chunk: string): string[] {
    this.rest += chunk
    const parts = this.rest.split(/\r?\n/)
    this.rest = parts.pop() ?? ''

    return parts
  }

  flush(): string[] {
    const last = this.rest
    this.rest = ''

    return last ? [last] : []
  }
}
