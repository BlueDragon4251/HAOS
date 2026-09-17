import { $activeChat, $activeChatId, $chats, createChat, interruptChat, openStoredSession, runSlash, sendPrompt } from './chat.ts'
import { $connection, gatewayRequest } from './gateway.ts'
import { $notifications } from './notifications.ts'
import { $pendingRequests, resolveRequest } from './requests.ts'
import { $sessions } from './sessions.ts'
import { showSurface } from './surface.ts'
import { $page, $windows, openApp, showPage } from './windows.ts'

/** Installed only in development builds (see boot.ts). */
export function installDebugHook(): void {
  Object.assign(window as unknown as Record<string, unknown>, {
    __hermesOS: {
      sendPrompt,
      runSlash,
      createChat,
      openStoredSession,
      interruptChat,
      gatewayRequest,
      showSurface,
      showPage,
      openApp,
      resolveRequest,
      state: () => ({
        connection: $connection.get(),
        page: $page.get(),
        windows: Object.values($windows.get()).map(w => ({ id: w.id, appId: w.appId, phase: w.phase, bounds: w.bounds, maximized: w.maximized })),
        activeChatId: $activeChatId.get(),
        activeChat: $activeChat.get(),
        chats: $chats.get(),
        sessions: $sessions.get(),
        pending: $pendingRequests.get().map(p => ({ kind: p.kind, id: p.request.id, params: p.request.params })),
        notifications: $notifications.get()
      })
    }
  })
}
