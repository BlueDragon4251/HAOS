import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { COMMAND_ID, defineCommands, listCommands, resetCommands } from '../store/os-commands.ts'
import { commandGroups, registerOsCommands } from './index.ts'

// The stores read the preload bridge and the viewport when they load; tests run without a DOM.
vi.hoisted(() => {
  Object.assign(globalThis, { window: { innerWidth: 1440, innerHeight: 900 } })
})

const everyCommand = Object.values(commandGroups).flat()
const registeredIds = () => listCommands({ includeHidden: true }).map(command => command.id)

describe('the OS command groups', () => {
  beforeEach(() => {
    resetCommands()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it.each(Object.entries(commandGroups))('%s registers every command', (_group, commands) => {
    defineCommands(commands)

    expect(registeredIds().sort()).toEqual(commands.map(command => command.id).sort())
  })

  it('use ids the registry accepts, each once', () => {
    const ids = everyCommand.map(command => command.id)

    expect(ids.filter(id => !COMMAND_ID.test(id))).toEqual([])
    expect(ids.filter((id, index) => ids.indexOf(id) !== index)).toEqual([])
  })

  it('all register at boot without a reported failure', () => {
    const report = vi.spyOn(console, 'error')
    registerOsCommands()

    expect(report).not.toHaveBeenCalled()
    expect(registeredIds()).toHaveLength(everyCommand.length)
  })
})
