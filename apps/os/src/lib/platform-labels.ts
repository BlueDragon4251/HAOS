import { $env } from '../store/backend.ts'

/** Host platform of the shell; `darwin` until main reports (the boot value on macOS builds). */
export function hostPlatform(): NodeJS.Platform | 'darwin' {
  return ($env.get()?.platform as NodeJS.Platform | undefined) ?? 'darwin'
}

/** Name of the host file manager, for "Reveal in …" affordances. */
export function fileManagerName(): string {
  switch (hostPlatform()) {
    case 'darwin':
      return 'Finder'
    case 'win32':
      return 'Explorer'
    default:
      return 'Files'
  }
}

export function revealLabel(): string {
  return hostPlatform() === 'darwin' ? 'Reveal in Finder' : `Show in ${fileManagerName()}`
}
