import { pauseAllAgents } from '../store/agents-control.ts'
import { $activeChat, createChat, interruptChat, openStoredSession, sendPrompt } from '../store/chat.ts'
import { $activeMissions, $completedMissions, $missions, $reviewMissions, focusMissions, markReviewed, type Mission } from '../store/missions.ts'
import { startMission } from '../store/missions-actions.ts'
import { $durableMissions, $missionServiceError, answerMissionRequest, cancelDurableMission, refreshDurableMissions } from '../store/durable-missions.ts'
import { fail, ok, type OsCommand } from '../store/os-commands.ts'
import { $sessions, refreshSessions } from '../store/sessions.ts'
import { readToolSearch, setToolSearch } from '../store/tool-search.ts'
import { openApp, showPage } from '../store/windows.ts'

/* Chat sessions and missions, and how Hermes reaches its tools. */

function findMission(query: string): { mission: Mission | null; candidates: Mission[] } {
  const needle = query.trim().toLowerCase()
  const missions = $missions.get()

  if (!needle) {
    return { mission: null, candidates: missions }
  }

  const exact = missions.filter(m => m.title.toLowerCase() === needle)

  if (exact.length === 1) {
    return { mission: exact[0], candidates: exact }
  }

  const partial = missions.filter(m => m.title.toLowerCase().includes(needle) || m.goal.toLowerCase().includes(needle))

  return { mission: partial.length === 1 ? partial[0] : null, candidates: partial }
}

const ambiguous = (what: string, names: string[]) => fail(`Which ${what}? ${names.slice(0, 5).join(', ')}${names.length > 5 ? ', …' : ''}`, { items: names })

export const hermesCommands: readonly OsCommand[] = [
  {
    id: 'chat.new',
    title: 'New chat',
    description: 'Start a new Hermes session and show it.',
    tier: 'act',
    args: [{ name: 'title', type: 'string', description: 'Optional title' }],
    phrases: ['new chat', 'start a new chat', 'new conversation', 'new session'],
    run: async ({ title }) => {
      const chat = await createChat({ title: title ? String(title) : undefined })
      showPage('hermes')

      return ok('Started a new chat', { page: 'hermes', data: { sessionId: chat.sessionId } })
    }
  },
  {
    id: 'chat.open',
    title: 'Open a session',
    description: 'Open a past Hermes session by title.',
    tier: 'read',
    args: [{ name: 'title', type: 'string', description: 'Part of the session title', required: true }],
    phrases: ['open the chat about {title}', 'open my {title} session', 'open the conversation about {title}'],
    run: async ({ title }) => {
      const needle = String(title).toLowerCase()
      let rows = $sessions.get()

      if (rows.length === 0) {
        await refreshSessions()
        rows = $sessions.get()
      }

      const matches = rows.filter(row => `${row.title ?? ''} ${row.preview ?? ''}`.toLowerCase().includes(needle))

      if (matches.length === 0) {
        return fail(`No session mentions "${String(title)}".`)
      }

      if (matches.length > 1 && !matches.some(row => (row.title ?? '').toLowerCase() === needle)) {
        return ambiguous(
          'session',
          matches.map(row => row.title || row.preview || row.id)
        )
      }

      const row = matches.find(r => (r.title ?? '').toLowerCase() === needle) ?? matches[0]
      showPage('hermes')
      await openStoredSession(row.id)

      return ok(`Opened "${row.title || row.preview || 'session'}"`, { page: 'hermes' })
    }
  },
  {
    id: 'chat.stop',
    title: 'Stop Hermes',
    description: 'Interrupt the running turn in the active session.',
    tier: 'act',
    args: [],
    phrases: ['stop hermes', 'stop the current task', 'interrupt', 'cancel that'],
    run: async () => {
      const chat = $activeChat.get()

      if (!chat?.streaming) {
        return ok('Nothing is running', { spoken: 'Nothing is running right now.' })
      }

      await interruptChat(chat.sessionId)

      return ok('Stopped the current turn')
    }
  },
  {
    id: 'chat.popout',
    title: 'Pop out the chat',
    description: 'Open the active session in its own window.',
    tier: 'read',
    args: [],
    phrases: ['pop out the chat', 'open the chat in a window', 'chat popout'],
    run: () => {
      const chat = $activeChat.get()

      if (!chat) {
        return fail('No active session to pop out.')
      }

      openApp('chat-popout', { payload: { sessionId: chat.sessionId }, title: chat.title || 'Hermes' })

      return ok('Popped out the chat')
    }
  },
  {
    id: 'chat.send',
    title: 'Ask Hermes',
    description: 'Send a message to Hermes in the active session.',
    tier: 'act',
    args: [{ name: 'text', type: 'string', description: 'The message', required: true }],
    hidden: true,
    run: async ({ text }) => {
      showPage('hermes')
      const sid = await sendPrompt(String(text))

      return ok('Sent to Hermes', { page: 'hermes', data: { sessionId: sid } })
    }
  },
  {
    id: 'mission.start',
    title: 'Start a mission',
    description: 'Start a mission: Hermes plans the steps and works through them.',
    tier: 'mutate',
    args: [{ name: 'goal', type: 'string', description: 'What the mission should achieve', required: true }],
    phrases: ['start a mission to {goal}', 'new mission {goal}', 'create a mission to {goal}', 'start a mission: {goal}'],
    run: async ({ goal }) => {
      const { sessionId, missionId, title, queued } = await startMission(String(goal))

      return ok(`${queued ? 'Queued' : 'Started'} mission "${title}"`, { spoken: queued ? 'Mission queued.' : 'Mission started.', page: queued ? 'missions' : 'hermes', data: { sessionId, missionId } })
    }
  },
  {
    id: 'mission.compose',
    title: 'New mission form',
    description: 'Open the Missions page with the new-mission form.',
    tier: 'read',
    args: [],
    phrases: ['new mission', 'start a mission', 'create a mission'],
    hidden: true,
    run: () => {
      showPage('missions')
      focusMissions({ compose: true })

      return ok('Opened the new-mission form', { page: 'missions' })
    }
  },
  {
    id: 'mission.open',
    title: 'Open a mission',
    description: 'Show a mission by name on the Missions page.',
    tier: 'read',
    args: [{ name: 'name', type: 'string', description: 'Part of the mission title', required: true }],
    phrases: ['open the {name} mission', 'show the mission {name}', 'open mission {name}'],
    run: async ({ name }) => {
      if ((await window.heraldOS.missions.serviceInfo()).managed) {
        await refreshDurableMissions()
        if ($missionServiceError.get()) return fail($missionServiceError.get()!)
        const needle = String(name).toLowerCase()
        const matches = $durableMissions.get().filter(row => row.id === String(name) || row.goal.toLowerCase().includes(needle))
        if (matches.length !== 1) return fail(matches.length ? 'Several stored missions match; use a mission ID.' : 'No stored mission matches.')
        showPage('missions'); focusMissions({ missionId: matches[0].id })
        return ok('Showing stored mission', { page: 'missions', data: { missionId: matches[0].id, state: matches[0].state } })
      }
      const { mission, candidates } = findMission(String(name))

      if (!mission) {
        return candidates.length ? ambiguous('mission', candidates.map(m => m.title)) : fail(`No mission matches "${String(name)}".`)
      }

      showPage('missions')
      focusMissions({ tab: mission.status, missionId: mission.id })

      return ok(`Showing mission "${mission.title}"`, { page: 'missions', highlight: { kind: 'mission', id: mission.id }, data: { status: mission.status, progress: mission.progress } })
    }
  },
  {
    id: 'mission.list',
    title: 'List missions',
    description: 'Summarise active missions and those waiting for review.',
    tier: 'read',
    args: [],
    phrases: ['what missions are running', 'list my missions', 'show my missions', 'how are my missions going'],
    run: async () => {
      if ((await window.heraldOS.missions.serviceInfo()).managed) {
        await refreshDurableMissions()
        if ($missionServiceError.get()) return fail($missionServiceError.get()!)
        showPage('missions')
        const rows = $durableMissions.get()
        return ok(`${rows.length} stored missions`, { page: 'missions', items: rows.map(row => ({ id: row.id, goal: row.goal, state: row.state })) })
      }
      const active = $activeMissions.get()
      const review = $reviewMissions.get()
      const completed = $completedMissions.get()
      showPage('missions')
      const summary = `${active.length} active, ${review.length} to review, ${completed.length} completed`

      return ok(summary, {
        page: 'missions',
        spoken: active.length ? `${summary}. Active: ${active.map(m => m.title).slice(0, 3).join(', ')}.` : `${summary}.`,
        items: [...active, ...review].map(m => ({ id: m.id, title: m.title, status: m.status, progress: m.progress, currentStep: m.currentStep }))
      })
    }
  },
  {
    id: 'mission.openDurable', title: 'Open a stored mission', description: 'Show a controller mission by its stable ID.', tier: 'read',
    args: [{ name: 'id', type: 'string', description: 'Mission ID', required: true }], hidden: true,
    run: ({ id }) => { showPage('missions'); focusMissions({ missionId: String(id) }); return ok('Opened stored mission', { page: 'missions' }) }
  },
  {
    id: 'mission.cancel', title: 'Stop a stored mission', description: 'Request interruption and retain uncertain work for owner recovery.', tier: 'act',
    args: [{ name: 'id', type: 'string', description: 'Stable mission ID', required: true }],
    run: async ({ id }) => { await cancelDurableMission(String(id)); return ok('Stop requested', { page: 'missions' }) }
  },
  {
    id: 'mission.answer', title: 'Answer a mission request', description: 'Give a clarification or one-time tool approval; grants no owner authority.', tier: 'mutate', hidden: true,
    args: [{ name: 'requestId', type: 'string', description: 'Pending request ID', required: true }, { name: 'choice', type: 'string', description: 'Explicit once or deny' }, { name: 'answer', type: 'string', description: 'Clarification answer' }],
    run: async ({ requestId, choice, answer }) => {
      if (choice !== undefined && choice !== 'once' && choice !== 'deny') return fail('Choose once or deny.')
      await answerMissionRequest(String(requestId), choice, typeof answer === 'string' ? answer : undefined)
      return ok('Answer sent', { page: 'missions' })
    }
  },
  {
    id: 'mission.pause',
    title: 'Pause a mission',
    description: 'Interrupt a running mission.',
    tier: 'act',
    args: [{ name: 'name', type: 'string', description: 'Part of the mission title', required: true }],
    phrases: ['pause the {name} mission', 'stop the {name} mission'],
    run: async ({ name }) => {
      if ((await window.heraldOS.missions.serviceInfo()).managed) {
        await refreshDurableMissions()
        if ($missionServiceError.get()) return fail($missionServiceError.get()!)
        const matches = $durableMissions.get().filter(row => row.id === String(name) || row.goal.toLowerCase().includes(String(name).toLowerCase()))
        if (matches.length !== 1) return fail('Choose one stored mission by its stable ID.')
        await cancelDurableMission(matches[0].id)
        showPage('missions'); focusMissions({ missionId: matches[0].id })
        return ok('Stop requested; interruption is confirmed by the controller.', { page: 'missions' })
      }
      const { mission, candidates } = findMission(String(name))

      if (!mission) {
        return candidates.length ? ambiguous('mission', candidates.map(m => m.title)) : fail(`No mission matches "${String(name)}".`)
      }

      if (!mission.runtimeId) {
        return fail(`"${mission.title}" is not running.`)
      }

      await interruptChat(mission.runtimeId)
      showPage('missions')
      focusMissions({ missionId: mission.id })

      return ok(`Paused "${mission.title}"`, { page: 'missions', highlight: { kind: 'mission', id: mission.id } })
    }
  },
  {
    id: 'mission.markReviewed',
    title: 'Mark a mission reviewed',
    description: 'Move a mission from Needs review to Completed.',
    tier: 'act',
    args: [{ name: 'name', type: 'string', description: 'Part of the mission title', required: true }],
    phrases: ['mark the {name} mission as reviewed', 'mark {name} reviewed', 'i reviewed the {name} mission'],
    run: ({ name }) => {
      const { mission, candidates } = findMission(String(name))

      if (!mission) {
        return candidates.length ? ambiguous('mission', candidates.map(m => m.title)) : fail(`No mission matches "${String(name)}".`)
      }

      markReviewed(mission.id)
      showPage('missions')
      focusMissions({ tab: 'completed', missionId: mission.id })

      return ok(`Marked "${mission.title}" as reviewed`, { page: 'missions', highlight: { kind: 'mission', id: mission.id } })
    }
  },
  {
    id: 'agents.pauseAll',
    title: 'Pause all agents',
    description: 'Interrupt every running session and pause every automation.',
    tier: 'destructive',
    args: [],
    phrases: ['pause all agents', 'pause everything', 'stop everything'],
    run: async () => {
      const result = await pauseAllAgents()

      return ok(`Paused all agents: ${result.interrupted} sessions, ${result.paused} automations`, { data: { ...result } })
    }
  },
  {
    id: 'agents.toolSearch.set',
    title: 'Tool search',
    description: "Hermes's Tool Search for every session: on looks plugin and MCP tools up when needed (fewer prompt tokens), off keeps Herald OS's system tools directly callable. New conversations use it.",
    tier: 'mutate',
    args: [{ name: 'enabled', type: 'boolean', description: 'true to turn Tool Search on, false to turn it off; leave it out to flip it' }],
    phrases: [
      { phrase: 'turn on tool search', args: { enabled: true } },
      { phrase: 'turn off tool search', args: { enabled: false } }
    ],
    run: async ({ enabled }) => {
      const on = enabled === undefined ? !(await readToolSearch()) : Boolean(enabled)
      await setToolSearch(on)

      return ok(`Tool search ${on ? 'on' : 'off'} for new conversations`, { highlight: { kind: 'setting', id: 'agents' }, data: { enabled: on } })
    }
  }
]
