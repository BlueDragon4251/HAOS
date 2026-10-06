import { describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ ipcMain: { handle: () => undefined }, shell: {} }))

const { parseBluetoothDevices, parseBluetoothInfo, parseBluetoothShow, parseBrightness, parseKnownWifi, parseNiriOutputs, parsePactl, parsePowerProfiles, parseUpowerTime, parseWifiList, renderOutputs, splitTerse } = await import('./linux-controls.ts')
const { parsePmsetTime, parseSpBluetooth, parseSpDisplays } = await import('./darwin-controls.ts')
const { controlActionProblem } = await import('../ipc/controls.ts')

describe('nmcli', () => {
  it('splits terse output on unescaped colons', () => {
    expect(splitTerse('*:Cafe\\: Free:72:WPA2')).toEqual(['*', 'Cafe: Free', '72', 'WPA2'])
    expect(splitTerse('a\\\\b:c')).toEqual(['a\\b', 'c'])
  })

  it('lists each network once, connected and saved ones first', () => {
    const known = parseKnownWifi('Home:802-11-wireless\nWired connection 1:802-3-ethernet\n')
    const list = parseWifiList([':Neighbour:90:WPA2', '*:Home:60:WPA2 WPA3', ':Home:75:WPA2', ':Open Cafe:40:--', '::30:WPA2', ''].join('\n'), known)

    expect(list).toEqual([
      { ssid: 'Home', signal: 75, secure: true, active: true, known: true },
      { ssid: 'Neighbour', signal: 90, secure: true, active: false, known: false },
      { ssid: 'Open Cafe', signal: 40, secure: false, active: false, known: false }
    ])
  })
})

describe('bluetoothctl', () => {
  it('reads the adapter, the devices and their details', () => {
    expect(parseBluetoothShow('Controller 00:1A:7D:DA:71:13 (public)\n\tPowered: yes\n\tDiscovering: no\n')).toEqual({ present: true, powered: true })
    expect(parseBluetoothShow('No default controller available\n')).toEqual({ present: false, powered: false })
    expect(parseBluetoothDevices('Device AC:80:0A:12:34:56 WH-1000XM5\nDevice 11:22:33:44:55:66 \nnoise\n')).toEqual([
      { address: 'AC:80:0A:12:34:56', name: 'WH-1000XM5' },
      { address: '11:22:33:44:55:66', name: '11:22:33:44:55:66' }
    ])
    expect(parseBluetoothInfo('\tPaired: yes\n\tConnected: no\n\tIcon: audio-headphones\n\tBattery Percentage: 0x50 (80)\n')).toEqual({ paired: true, connected: false, icon: 'audio-headphones', battery: 80 })
  })
})

describe('pactl', () => {
  it('reads devices and volumes, without monitor sources', () => {
    const json = JSON.stringify([
      { name: 'alsa_output.pci.analog-stereo', description: 'Built-in Audio', mute: false, volume: { 'front-left': { value_percent: '40%' }, 'front-right': { value_percent: '44%' } } },
      { name: 'alsa_output.pci.analog-stereo.monitor', description: 'Monitor of Built-in Audio', mute: false, volume: {} },
      { name: 'bluez_output.AC_80', description: 'WH-1000XM5', mute: true, volume: { mono: { value_percent: '70%' } } }
    ])

    expect(parsePactl(json, 'bluez_output.AC_80\n')).toEqual([
      { id: 'alsa_output.pci.analog-stereo', name: 'Built-in Audio', isDefault: false, volume: 42, muted: false },
      { id: 'bluez_output.AC_80', name: 'WH-1000XM5', isDefault: true, volume: 70, muted: true }
    ])
    expect(parsePactl('not json', '')).toEqual([])
  })
})

describe('displays', () => {
  const outputs = JSON.stringify({
    'eDP-1': { name: 'eDP-1', make: 'BOE', model: 'NE135A1M', modes: [{ width: 2880, height: 1920, refresh_rate: 120000 }, { width: 1920, height: 1280, refresh_rate: 60001 }], current_mode: 0, logical: { scale: 2 } },
    'HDMI-A-1': { name: 'HDMI-A-1', make: 'Unknown', model: 'Unknown', modes: [{ width: 3840, height: 2160, refresh_rate: 60000 }], current_mode: null, logical: null }
  })

  it('reads niri outputs', () => {
    expect(parseNiriOutputs(outputs)).toEqual([
      {
        name: 'eDP-1',
        label: 'BOE NE135A1M',
        enabled: true,
        width: 2880,
        height: 1920,
        refresh: 120,
        scale: 2,
        modes: [
          { width: 2880, height: 1920, refresh: 120 },
          { width: 1920, height: 1280, refresh: 60 }
        ]
      },
      { name: 'HDMI-A-1', label: 'HDMI-A-1', enabled: false, width: 0, height: 0, refresh: 0, scale: 1, modes: [{ width: 3840, height: 2160, refresh: 60 }] }
    ])
  })

  it('writes outputs.kdl that niri reads back', () => {
    const kdl = renderOutputs(parseNiriOutputs(outputs))

    expect(kdl).toContain('output "eDP-1" {\n    mode "2880x1920@120.000"\n    scale 2\n}')
    expect(kdl).toContain('output "HDMI-A-1" {\n    off\n}')
  })

  it('reads the backlight', () => {
    expect(parseBrightness('intel_backlight,backlight,48000,50%,96000\n')).toBe(50)
    expect(parseBrightness('')).toBeUndefined()
  })
})

describe('power', () => {
  it('reads power profiles and the time left', () => {
    expect(parsePowerProfiles('  performance:\n    CpuDriver:\tamd_pstate\n\n* balanced:\n    CpuDriver:\tamd_pstate\n\n  power-saver:\n    CpuDriver:\tamd_pstate\n')).toEqual({ profiles: ['performance', 'balanced', 'power-saver'], active: 'balanced' })
    expect(parseUpowerTime('  state:               discharging\n  time to empty:       3.2 hours\n')).toBe('about 3.2 hours left')
    expect(parseUpowerTime('  time to full:        40.5 minutes\n')).toBe('full in about 40.5 minutes')
  })
})

describe('macOS read-only panels', () => {
  it('reads Bluetooth, displays and the battery time', () => {
    const bt = JSON.stringify({ SPBluetoothDataType: [{ controller_properties: { controller_state: 'attrib_on' }, device_connected: [{ AirPods: { device_address: 'AA:BB:CC:DD:EE:FF', device_minorType: 'Headphones', device_batteryLevelMain: '80%' } }], device_not_connected: [{ 'Magic Mouse': { device_address: '11:22:33:44:55:66' } }] }] })

    expect(parseSpBluetooth(bt)).toEqual({
      powered: true,
      devices: [
        { address: 'AA:BB:CC:DD:EE:FF', name: 'AirPods', paired: true, connected: true, icon: 'Headphones', battery: 80 },
        { address: '11:22:33:44:55:66', name: 'Magic Mouse', paired: true, connected: false, icon: undefined, battery: undefined }
      ]
    })
    expect(parseSpDisplays(JSON.stringify({ SPDisplaysDataType: [{ spdisplays_ndrvs: [{ _name: 'Color LCD', _spdisplays_resolution: '3456 x 2234 @ 120.00Hz' }] }] }))[0]).toMatchObject({ name: 'Color LCD', width: 3456, height: 2234, refresh: 120 })
    expect(parsePmsetTime("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t76%; discharging; 3:12 remaining present: true")).toBe('about 3.2 hours left')
  })
})

describe('controlActionProblem', () => {
  it('refuses names that could be read as options and bad addresses', () => {
    expect(controlActionProblem({ panel: 'wifi', action: 'connect', ssid: 'Home' })).toBeNull()
    expect(controlActionProblem({ panel: 'wifi', action: 'connect', ssid: '--help' })).toBe('invalid name')
    expect(controlActionProblem({ panel: 'bluetooth', action: 'connect', address: 'not-a-mac' })).toBe('not a Bluetooth address')
    expect(controlActionProblem({ panel: 'power', action: 'profile', profile: 'turbo; reboot' })).toBe('unknown power profile')
    expect(controlActionProblem({ panel: 'audio', action: 'volume', kind: 'output', percent: 30 })).toBeNull()
  })
})
