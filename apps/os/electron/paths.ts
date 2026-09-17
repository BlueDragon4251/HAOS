import os from 'node:os'
import path from 'node:path'

/** Profile-aware Hermes home; mirrors upstream `get_hermes_home()` for the default profile. */
export function hermesHome(): string {
  const override = process.env.HERMES_HOME?.trim()

  if (override) {
    return override
  }

  if (process.platform === 'win32') {
    return path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'), 'hermes')
  }

  return path.join(os.homedir(), '.hermes')
}

export function hermesOsDataDir(): string {
  return path.join(hermesHome(), 'hermes-os')
}

export const isDev = process.env.HERMES_OS_BUILD_MODE === 'development' || Boolean(process.env.HERMES_OS_DEV_SERVER)

export function devServerUrl(): string | undefined {
  return process.env.HERMES_OS_DEV_SERVER
}
