import { defineCommands } from '../../store/os-commands.ts'
import { automationCommands } from './automations.ts'
import { connectionCommands } from './connections.ts'
import { editCommands } from './edit.ts'
import { filesCommands } from './files.ts'
import { hermesCommands } from './hermes.ts'
import { memoryCommands } from './memory.ts'
import { navigationCommands } from './navigation.ts'
import { openCommands } from './open.ts'
import { studioCommands } from './studio.ts'
import { systemCommands } from './system.ts'

let registered = false

/** Register every OS command once at boot. New user-visible actions belong in one of these files. */
export function registerOsCommands(): void {
  if (registered) {
    return
  }

  registered = true

  // A bad definition must not take the whole shell down with it; report and keep booting.
  for (const group of [navigationCommands, editCommands, hermesCommands, memoryCommands, filesCommands, automationCommands, connectionCommands, systemCommands, studioCommands, openCommands]) {
    try {
      defineCommands(group)
    } catch (error) {
      console.error('[os-commands] registration failed:', error)
    }
  }
}
