import { bindAgentEvents } from './agents.ts'
import { bindBackendStores } from './backend.ts'
import { bindChatEvents, resetChats } from './chat.ts'
import { $connectionEpoch, bindGatewayToBackend } from './gateway.ts'
import { bindNotificationEvents } from './notifications.ts'
import { bindServerRequests } from './requests.ts'
import { refreshSessions } from './sessions.ts'

const BOOT_FLAG = '__hermesOSBooted'

/** Wire every store to its source exactly once, before React mounts (guard survives dev HMR re-evaluation). */
export function bootRenderer(): void {
  const global = window as unknown as Record<string, unknown>

  if (global[BOOT_FLAG]) {
    return
  }

  global[BOOT_FLAG] = true
  bindBackendStores()
  bindGatewayToBackend()
  bindChatEvents()
  bindServerRequests()
  bindNotificationEvents()
  bindAgentEvents()

  let lastEpoch = 0
  $connectionEpoch.subscribe(epoch => {
    if (epoch === 0) {
      return
    }

    // A fresh backend process (restart) invalidates every runtime session id we hold.
    if (lastEpoch !== 0) {
      resetChats()
    }

    lastEpoch = epoch
    void refreshSessions()
  })

  if (import.meta.env.DEV) {
    // Dev-only hook so automated runs (CDP) can drive the stores; never present in production.
    void import('./debug.ts').then(m => m.installDebugHook())
  }
}
