import type { ApprovalRequestParams, ClarifyRequestParams, SecretRequestParams, ServerRequest, SudoRequestParams } from '@hermes-os/client'
import { atom } from 'nanostores'
import { onGatewayEvent, onServerRequest } from './gateway.ts'
import { notify } from './notifications.ts'

// The generated contract types are closed shapes; the channel's params type carries an index
// signature. Intersect so cards get the typed fields without losing assignability.
type Open<T> = T & Record<string, unknown>

export type PendingRequest =
  | { kind: 'approval'; request: ServerRequest<'approval', Open<ApprovalRequestParams>>; receivedAt: number }
  | { kind: 'clarify'; request: ServerRequest<'clarify', Open<ClarifyRequestParams>>; receivedAt: number }
  | { kind: 'sudo'; request: ServerRequest<'sudo', Open<SudoRequestParams>>; receivedAt: number }
  | { kind: 'secret'; request: ServerRequest<'secret', Open<SecretRequestParams>>; receivedAt: number }

const HANDLED = new Set(['approval', 'clarify', 'sudo', 'secret'])

/** Open server->client questions, oldest first. One host renders them; answering removes them. */
export const $pendingRequests = atom<PendingRequest[]>([])

export function bindServerRequests(): () => void {
  const offRequests = onServerRequest(request => {
    if (!HANDLED.has(request.method)) {
      // Declining lets the channel answer -32601 so the backend treats it as unanswered.
      return false
    }

    const kind = request.method as PendingRequest['kind']
    const pending = $pendingRequests.get()

    if (pending.some(entry => entry.request.id === request.id)) {
      return true
    }

    $pendingRequests.set([...pending, { kind, request, receivedAt: Date.now() } as PendingRequest])

    if (kind === 'approval') {
      const params = request.params as ApprovalRequestParams
      notify({ title: 'Approval needed', body: params.description || params.command || params.tool_name || 'Hermes is asking for permission', level: 'warn', surface: 'chat', native: true })
    } else if (kind === 'clarify') {
      notify({ title: 'Hermes has a question', body: (request.params as ClarifyRequestParams).question ?? 'Hermes needs clarification', level: 'info', surface: 'chat', native: true })
    }

    return true
  })

  const offCancel = onGatewayEvent('request.cancel', event => {
    const id = (event.payload as { request_id?: string; id?: string } | undefined)?.request_id ?? (event.payload as { id?: string } | undefined)?.id

    if (id) {
      $pendingRequests.set($pendingRequests.get().filter(entry => entry.request.id !== id))
    }
  })

  return () => {
    offRequests()
    offCancel()
  }
}

export function resolveRequest(id: string, result: Record<string, unknown>): void {
  const entry = $pendingRequests.get().find(item => item.request.id === id)

  if (!entry) {
    return
  }

  entry.request.respond(result)
  $pendingRequests.set($pendingRequests.get().filter(item => item.request.id !== id))
}
