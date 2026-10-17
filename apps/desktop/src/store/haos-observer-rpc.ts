/** Methods the HAOS observer may send across Hermes's WebSocket.
 *
 * This list deliberately matches linux/haos/haos/web_access.py READ_RPC.
 * Untrusted UI code must not trigger the server's fail-closed 4403 by sending
 * legacy Herald requests that require the controller/owner credential.
 * The server remains the authority: this is only an early UI compatibility gate.
 */
const HAOS_OBSERVER_RPC = new Set([
  'gateway.ping',
  'session.list',
  'session.active_list',
  'session.events.since',
  'session.events.stats'
])

export function observerRpcAllowed(managedMissions: boolean, method: string): boolean {
  return !managedMissions || HAOS_OBSERVER_RPC.has(method)
}
