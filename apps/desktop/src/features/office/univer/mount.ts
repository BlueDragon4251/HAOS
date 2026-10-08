/*
 * A Univer instance in its own element inside a document's view. Each instance renders its own
 * React root, so a new one (a reload, or React mounting a view twice in development) never shares
 * an element with one that is still going away. An instance is disposed outside React's commit,
 * since disposing unmounts that root.
 */

export interface Mounted<Engine extends { dispose: () => void }> {
  engine: Engine
  element: HTMLElement
}

export function mountIn<Engine extends { dispose: () => void }>(host: HTMLElement, create: (element: HTMLElement) => Engine): Mounted<Engine> {
  const element = document.createElement('div')
  element.className = 'absolute inset-0'
  host.append(element)

  return { engine: create(element), element }
}

export function unmount<Engine extends { dispose: () => void }>(mounted: Mounted<Engine> | null, later: boolean): void {
  if (!mounted) {
    return
  }

  const finish = () => {
    mounted.engine.dispose()
    mounted.element.remove()
  }

  if (later) {
    setTimeout(finish, 0)
  } else {
    finish()
  }
}
