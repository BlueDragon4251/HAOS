import { createChat, sendPrompt } from './chat.ts'
import { showPage } from './windows.ts'
import { refreshDurableMissions } from './durable-missions.ts'

const TITLE_MAX = 60

/** The prompt shape that makes a chat a mission (todo list first, then work, then a summary). */
export function missionPrompt(goal: string): string {
  return `Mission: ${goal}\n\nPlan this as a mission: first create a todo list of the concrete steps with the todo tool, then work through them, updating the todo list as you go, and finish with a short summary of what you produced.`
}

/** Start a mission in a fresh session and show it. Shared by the composer, the palette and voice. */
export async function startMission(goal: string, requestKey: string = crypto.randomUUID()): Promise<{ sessionId?: string; missionId?: string; title: string; queued: boolean }> {
  const trimmed = goal.trim()

  if (!trimmed) {
    throw new Error('A mission needs a goal.')
  }

  const title = trimmed.slice(0, TITLE_MAX)
  if ((await window.heraldOS.missions.serviceInfo()).managed) {
    const mission = await window.heraldOS.missions.request('missions.create', { goal: trimmed, idempotency_key: requestKey })
    void refreshDurableMissions()
    showPage('missions')
    return { missionId: mission.id, title, queued: true }
  }
  const chat = await createChat({ title })
  void sendPrompt(missionPrompt(trimmed), { sessionId: chat.sessionId })
  showPage('hermes')

  return { sessionId: chat.sessionId, title, queued: false }
}
