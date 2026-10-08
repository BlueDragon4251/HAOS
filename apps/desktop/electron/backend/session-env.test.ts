import { describe, expect, it } from 'vitest'
import { serveEnvironment } from './manager.ts'
import { forgetInheritedSession, isInheritedSessionVariable, withoutInheritedSession } from './session-env.ts'

// What a Herald OS started by a command in a Herald OS session would inherit: the session Hermes
// passed on, the backend's own markers, and the person's environment.
const LAUNCHED_FROM_A_SESSION: NodeJS.ProcessEnv = {
  HERMES_SESSION_SOURCE: 'herald_os',
  HERMES_SESSION_SOURCE_EXPLICIT: '1',
  HERMES_SESSION_PLATFORM: 'telegram',
  HERMES_SESSION_ID: '20261008_101112_abcdef',
  HERMES_SESSION_KEY: 'agent:main:telegram:dm:42',
  HERMES_UI_SESSION_ID: 'tab-1',
  HERMES_CRON_SESSION: '1',
  HERMES_CRON_AUTO_DELIVER_CHAT_ID: '42',
  HERMES_BROWSER_CONTROL_PRINCIPAL: 'digest',
  HERMES_SINGLE_QUERY_SESSION: '1',
  HERMES_KANBAN_TASK: 't_1',
  HERALD_OS: '1',
  HERALD_OS_CONTROL_SOCKET: '/run/user/1000/herald-os/os.sock',
  HERALD_OS_CONTROL_TOKEN: 'secret',
  HERMES_HOME: '/home/me/.hermes',
  HERMES_DESKTOP: '1',
  HERMES_PARENT_PID: '1234',
  HERALD_OS_BACKEND_URL: 'http://127.0.0.1:9119',
  HERALD_OS_WINDOWED: '1',
  PATH: '/usr/bin:/bin',
  HOME: '/home/me'
}

const KEPT = ['HERMES_HOME', 'HERMES_DESKTOP', 'HERMES_PARENT_PID', 'HERALD_OS_BACKEND_URL', 'HERALD_OS_WINDOWED', 'PATH', 'HOME']

describe('a session inherited from the environment', () => {
  it('is not passed on, while the rest of the environment is', () => {
    const env = withoutInheritedSession(LAUNCHED_FROM_A_SESSION)

    expect(Object.keys(env).sort()).toEqual([...KEPT].sort())
    expect(env.HERMES_HOME).toBe('/home/me/.hermes')
  })

  it('covers every HERMES_SESSION_ variable, current and future', () => {
    expect(isInheritedSessionVariable('HERMES_SESSION_SOURCE')).toBe(true)
    expect(isInheritedSessionVariable('HERMES_SESSION_SOMETHING_NEW')).toBe(true)
    expect(isInheritedSessionVariable('HERMES_SESSION')).toBe(false)
    expect(isInheritedSessionVariable('HERALD_OS_SCALE')).toBe(false)
    expect(isInheritedSessionVariable('XHERMES_SESSION_SOURCE')).toBe(false)
  })

  it('does not reach the backend, which gets its own Herald OS markers instead', () => {
    const env = serveEnvironment({ ...LAUNCHED_FROM_A_SESSION, ELECTRON_RUN_AS_NODE: '1' }, { HERALD_OS: '1', HERMES_PARENT_PID: '99', HERMES_SPAWN: undefined })

    expect(Object.keys(env).filter(name => name.startsWith('HERMES_SESSION_'))).toEqual([])
    expect(env.HERMES_UI_SESSION_ID).toBeUndefined()
    expect(env.HERALD_OS_CONTROL_SOCKET).toBeUndefined()
    expect(env.ELECTRON_RUN_AS_NODE).toBeUndefined()
    expect(env.HERALD_OS).toBe('1')
    expect(env.HERMES_PARENT_PID).toBe('99')
    expect(env.HERMES_HOME).toBe('/home/me/.hermes')
  })

  it('is dropped from the app’s own environment, so nothing it starts inherits it', () => {
    const env = { ...LAUNCHED_FROM_A_SESSION }
    const dropped = forgetInheritedSession(env)

    expect(dropped).toContain('HERMES_SESSION_SOURCE')
    expect(dropped).toContain('HERALD_OS')
    expect(Object.keys(env).sort()).toEqual([...KEPT].sort())
    expect(forgetInheritedSession(env)).toEqual([])
  })
})
