import type { CronJob } from '../lib/rest.ts'
import { type CronJobDraft, cronApi, errorText, isPaused } from '../features/automations/api.ts'
import { notify } from './notifications.ts'

/*
 * Automation (cron job) mutations shared by the Automations page, the command registry and the
 * agent. The backend emits `cron.changed` after every write, which the page already listens to, so
 * callers do not need to refresh anything here.
 */

const toast = (title: string, body: string, level: 'success' | 'error' | 'info' = 'success') => notify({ title, body, level, surface: 'automations' })

const nameOf = (job: CronJob) => job.name || 'Automation'

export function listAutomations(): Promise<CronJob[]> {
  return cronApi.list()
}

/** Case-insensitive lookup by name (exact first, then contains); null when nothing or too many match. */
export async function findAutomation(query: string): Promise<{ job: CronJob | null; candidates: CronJob[] }> {
  const needle = query.trim().toLowerCase()
  const jobs = await listAutomations()

  if (!needle) {
    return { job: null, candidates: jobs }
  }

  const exact = jobs.filter(job => (job.name ?? '').toLowerCase() === needle)

  if (exact.length === 1) {
    return { job: exact[0], candidates: exact }
  }

  const partial = jobs.filter(job => (job.name ?? '').toLowerCase().includes(needle) || (job.prompt ?? '').toLowerCase().includes(needle))

  return { job: partial.length === 1 ? partial[0] : null, candidates: partial }
}

export async function setAutomationEnabled(job: CronJob, enabled: boolean): Promise<void> {
  try {
    await (enabled ? cronApi.resume(job) : cronApi.pause(job))
    toast(nameOf(job), enabled ? 'Resumed' : 'Paused')
  } catch (error) {
    toast(enabled ? 'Could not resume' : 'Could not pause', errorText(error), 'error')
    throw error
  }
}

export async function triggerAutomation(job: CronJob): Promise<void> {
  try {
    await cronApi.trigger(job)
    toast(nameOf(job), 'Run started')
  } catch (error) {
    toast('Run failed', errorText(error), 'error')
    throw error
  }
}

export async function duplicateAutomation(job: CronJob): Promise<CronJob | null> {
  try {
    const created = await cronApi.duplicate(job)
    toast(nameOf(job), 'Duplicated')

    return created ?? null
  } catch (error) {
    toast('Duplicate failed', errorText(error), 'error')
    throw error
  }
}

export async function deleteAutomation(job: CronJob): Promise<void> {
  try {
    await cronApi.remove(job)
    toast(nameOf(job), 'Deleted', 'info')
  } catch (error) {
    toast('Delete failed', errorText(error), 'error')
    throw error
  }
}

export async function createAutomation(draft: CronJobDraft, profile?: string | null): Promise<CronJob> {
  try {
    const created = await cronApi.create(draft, profile)
    toast(draft.name || 'Automation', 'Created')

    return created
  } catch (error) {
    toast('Could not create automation', errorText(error), 'error')
    throw error
  }
}

export { isPaused }
