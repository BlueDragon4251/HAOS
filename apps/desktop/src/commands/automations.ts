import type { CronJob } from '../lib/rest.ts'
import { createAutomation, deleteAutomation, findAutomation, isPaused, listAutomations, setAutomationEnabled, triggerAutomation } from '../store/automations.ts'
import { fail, ok, type OsCommand } from '../store/os-commands.ts'
import { showPage } from '../store/windows.ts'
import { humanizeSchedule } from '../features/automations/cron-humanize.ts'

/* Automations (Hermes cron jobs). */

const summarise = (job: CronJob) => ({ id: job.id, name: job.name, schedule: humanizeSchedule(job), paused: isPaused(job), nextRun: job.next_run_at ?? null, lastStatus: job.last_status ?? null })

async function pick(name: string) {
  const { job, candidates } = await findAutomation(name)

  if (!job) {
    return { job: null, result: candidates.length ? fail(`Which automation? ${candidates.map(j => j.name || j.id).slice(0, 5).join(', ')}`, { items: candidates.map(summarise) }) : fail(`No automation matches "${name}".`) }
  }

  return { job, result: null }
}

export const automationCommands: readonly OsCommand[] = [
  {
    id: 'automation.list',
    title: 'List automations',
    description: 'Open Automations and list the scheduled jobs.',
    tier: 'read',
    args: [],
    phrases: ['show my automations', 'list automations', 'what automations do i have', 'show scheduled tasks', 'what is scheduled'],
    run: async () => {
      showPage('automations')
      const jobs = await listAutomations()
      const active = jobs.filter(job => !isPaused(job))

      return ok(`${jobs.length} automation${jobs.length === 1 ? '' : 's'}, ${active.length} active`, {
        page: 'automations',
        spoken: jobs.length ? `You have ${jobs.length} automations, ${active.length} active: ${jobs.slice(0, 4).map(j => j.name || 'unnamed').join(', ')}.` : 'You have no automations yet.',
        items: jobs.map(summarise)
      })
    }
  },
  {
    id: 'automation.show',
    title: 'Show an automation',
    description: 'Open Automations focused on one job.',
    tier: 'read',
    args: [{ name: 'name', type: 'string', description: 'Part of the automation name', required: true }],
    phrases: ['show the {name} automation', 'open the {name} automation'],
    run: async ({ name }) => {
      const { job, result } = await pick(String(name))

      if (!job) {
        return result!
      }

      showPage('automations')

      return ok(`${job.name}: ${humanizeSchedule(job)}${isPaused(job) ? ' (paused)' : ''}`, { page: 'automations', highlight: { kind: 'automation', id: job.id }, data: summarise(job) })
    }
  },
  {
    id: 'automation.run',
    title: 'Run an automation now',
    description: 'Trigger a scheduled job immediately.',
    tier: 'act',
    args: [{ name: 'name', type: 'string', description: 'Part of the automation name', required: true }],
    phrases: ['run the {name} automation now', 'run {name} now', 'trigger {name}'],
    run: async ({ name }) => {
      const { job, result } = await pick(String(name))

      if (!job) {
        return result!
      }

      await triggerAutomation(job)
      showPage('automations')

      return ok(`Started "${job.name}"`, { spoken: `Running ${job.name} now.`, page: 'automations', highlight: { kind: 'automation', id: job.id } })
    }
  },
  {
    id: 'automation.pause',
    title: 'Pause an automation',
    description: 'Pause a scheduled job.',
    tier: 'mutate',
    args: [{ name: 'name', type: 'string', description: 'Part of the automation name', required: true }],
    phrases: ['pause the {name} automation', 'pause {name}', 'disable the {name} automation'],
    run: async ({ name }) => {
      const { job, result } = await pick(String(name))

      if (!job) {
        return result!
      }

      await setAutomationEnabled(job, false)
      showPage('automations')

      return ok(`Paused "${job.name}"`, { page: 'automations', highlight: { kind: 'automation', id: job.id } })
    }
  },
  {
    id: 'automation.resume',
    title: 'Resume an automation',
    description: 'Resume a paused job.',
    tier: 'mutate',
    args: [{ name: 'name', type: 'string', description: 'Part of the automation name', required: true }],
    phrases: ['resume the {name} automation', 'resume {name}', 'enable the {name} automation', 'unpause {name}'],
    run: async ({ name }) => {
      const { job, result } = await pick(String(name))

      if (!job) {
        return result!
      }

      await setAutomationEnabled(job, true)
      showPage('automations')

      return ok(`Resumed "${job.name}"`, { page: 'automations', highlight: { kind: 'automation', id: job.id } })
    }
  },
  {
    id: 'automation.create',
    title: 'Create an automation',
    description: 'Schedule a prompt: `schedule` is natural ("every day at 9am", "every 30 minutes", "weekdays at 8:00") or cron.',
    tier: 'mutate',
    args: [
      { name: 'name', type: 'string', description: 'Short name', required: true },
      { name: 'schedule', type: 'string', description: 'When it runs', required: true },
      { name: 'prompt', type: 'string', description: 'What Hermes should do each run', required: true }
    ],
    run: async ({ name, schedule, prompt }) => {
      const created = await createAutomation({ name: String(name), schedule: String(schedule), prompt: String(prompt), deliver: 'local' })
      showPage('automations')

      return ok(`Created "${created.name ?? String(name)}" (${humanizeSchedule(created)})`, { page: 'automations', highlight: { kind: 'automation', id: created.id }, data: summarise(created) })
    }
  },
  {
    id: 'automation.delete',
    title: 'Delete an automation',
    description: 'Delete a scheduled job permanently.',
    tier: 'destructive',
    args: [{ name: 'name', type: 'string', description: 'Part of the automation name', required: true }],
    phrases: ['delete the {name} automation', 'remove the {name} automation'],
    run: async ({ name }) => {
      const { job, result } = await pick(String(name))

      if (!job) {
        return result!
      }

      await deleteAutomation(job)
      showPage('automations')

      return ok(`Deleted "${job.name}"`, { page: 'automations' })
    }
  }
]
