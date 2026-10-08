import net from 'node:net'
import { MISSION_METHODS, type MissionMethods } from '../../shared/missions.ts'

export function managedMissions(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.HAOS_BACKEND_CONFIG)
}

export function missionSocket(env: NodeJS.ProcessEnv = process.env): string {
  if (!managedMissions(env) || env.HAOS_CONTROL_SOCKET !== '/run/haos-control/control.sock') {
    throw new Error('The HAOS mission controller is not configured')
  }
  return env.HAOS_CONTROL_SOCKET
}

export function controllerRequest<M extends keyof MissionMethods>(method: M, params: MissionMethods[M]['params']): Promise<MissionMethods[M]['result']> {
  if (!MISSION_METHODS.has(method)) {
    return Promise.reject(new Error('Unknown mission method'))
  }
  const path = missionSocket()
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ path })
    const chunks: Buffer[] = []
    let length = 0
    let settled = false
    const finish = (error?: Error, value?: MissionMethods[M]['result']) => {
      if (settled) return
      settled = true
      socket.destroy()
      if (error) reject(error)
      else resolve(value as MissionMethods[M]['result'])
    }
    socket.setTimeout(15_000, () => finish(new Error('The HAOS controller did not respond')))
    socket.once('error', error => finish(error))
    socket.once('end', () => finish(new Error('The HAOS controller closed without a complete reply')))
    socket.once('connect', () => socket.write(`${JSON.stringify({ method, params })}\n`))
    socket.on('data', chunk => {
      length += chunk.length
      if (length > 8 * 1024 * 1024) {
        finish(new Error('The HAOS response exceeds the local transport limit'))
        return
      }
      chunks.push(chunk)
      if (!chunk.includes(10)) return
      try {
        const reply = JSON.parse(Buffer.concat(chunks).toString('utf8').split('\n')[0]) as { ok?: boolean; result?: MissionMethods[M]['result']; error?: string }
        finish(reply.ok ? undefined : new Error(reply.error || 'The HAOS request failed'), reply.result)
      } catch {
        finish(new Error('The HAOS controller returned an invalid reply'))
      }
    })
  })
}
