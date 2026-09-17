import { atom } from 'nanostores'
import type { SurfaceId } from '../app/surfaces.ts'

export const $surface = atom<SurfaceId>('home')
export const $commandBarOpen = atom(false)

export function showSurface(id: SurfaceId): void {
  $surface.set(id)
}

export function toggleCommandBar(open?: boolean): void {
  $commandBarOpen.set(open ?? !$commandBarOpen.get())
}
