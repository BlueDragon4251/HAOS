// Verify the image-bundled polkit rule grants only local haos-ui observers.
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const src = fs.readFileSync(path.join(__dirname, '../networkmanager-observer.rules'), 'utf8')
let registered
vm.runInNewContext(src, {
  polkit: {
    Result: { YES: 'yes' },
    addRule(fn) { registered = fn }
  }
}, { timeout: 1000 })
assert.equal(typeof registered, 'function')
const localUser = (name, group, local) => ({
  user: name,
  local,
  active: false, // greetd autologin may not mark the observer active
  isInGroup(g) { return group && g === 'haos-ui' }
})
const expected = [
  'org.freedesktop.NetworkManager.network-control',
  'org.freedesktop.NetworkManager.settings.modify.own',
  'org.freedesktop.NetworkManager.settings.modify.system',
  'org.freedesktop.NetworkManager.enable-disable-wifi',
  'org.freedesktop.NetworkManager.wifi.scan'
]
for (const action of expected) {
  assert.equal(registered({ id: action }, localUser('hermes', true, true)), 'yes', action)
  assert.equal(registered({ id: action }, localUser('haos-agent', true, true)), undefined)
  assert.equal(registered({ id: action }, localUser('haos-control', true, true)), undefined)
  assert.equal(registered({ id: action }, localUser('hermes', false, true)), undefined)
  assert.equal(registered({ id: action }, localUser('hermes', true, false)), undefined)
}
for (const action of [
  'org.freedesktop.NetworkManager.settings.modify.hostname',
  'org.freedesktop.NetworkManager.reload',
  'org.freedesktop.NetworkManager.settings.modify.global-dns',
  'org.freedesktop.login1.power-off',
  'org.freedesktop.policykit.exec'
]) {
  assert.equal(registered({ id: action }, localUser('hermes', true, true)), undefined)
}
assert.match(src, /subject\.local/)
assert.doesNotMatch(src, /subject\.active/)
console.log('HAOS local observer NetworkManager Polkit policy: passed')
