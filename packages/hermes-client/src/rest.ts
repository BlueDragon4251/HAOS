// Thin REST helpers over the FastAPI routers `hermes serve` mounts next to the JSON-RPC socket.
// The renderer never holds the token: Electron main performs these requests (see apps/desktop), so the
// client is built around an injected `fetch`-like function.

export interface RestClientOptions {
  baseUrl: string
  token: string
  fetchImpl?: typeof fetch
}

export class HermesRestError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string
  ) {
    super(message)
    this.name = 'HermesRestError'
  }
}

export interface HermesRest {
  get<T>(path: string, query?: Record<string, string | number | boolean | undefined>): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  put<T>(path: string, body?: unknown): Promise<T>
  del<T>(path: string): Promise<T>
}

export function createHermesRest(options: RestClientOptions): HermesRest {
  const fetchImpl = options.fetchImpl ?? fetch
  const base = options.baseUrl.replace(/\/+$/, '')

  const run = async <T>(method: string, path: string, body?: unknown, query?: Record<string, unknown>): Promise<T> => {
    const url = new URL(base + path)

    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value))
      }
    }

    const response = await fetchImpl(url.toString(), {
      method,
      headers: {
        'X-Hermes-Session-Token': options.token,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' })
      },
      body: body === undefined ? undefined : JSON.stringify(body)
    })

    if (!response.ok) {
      let detail = response.statusText

      try {
        const parsed = (await response.json()) as { detail?: unknown; error?: unknown }
        detail = String(parsed.detail ?? parsed.error ?? detail)
      } catch {
        // Non-JSON error body: keep the status text.
      }

      throw new HermesRestError(response.status, path, `${method} ${path} failed (${response.status}): ${detail}`)
    }

    const text = await response.text()

    return (text ? JSON.parse(text) : null) as T
  }

  return {
    get: (path, query) => run('GET', path, undefined, query),
    post: (path, body) => run('POST', path, body),
    put: (path, body) => run('PUT', path, body),
    del: path => run('DELETE', path)
  }
}

/** `GET /api/status` (public route used for readiness probing). */
export interface HermesStatus {
  status?: string
  version?: string
  [key: string]: unknown
}
