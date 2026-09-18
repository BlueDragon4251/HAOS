import { describe, expect, it } from 'vitest'
import { fileUri, filterLinuxMounts, mapDesktopCategory, parseBattery, parseDesktopEntry, parseMeminfo, parseNmcliDevStatus, parseNmcliWifi, parseOsRelease, parseProcStat, parseRecentlyUsed, stripExecFieldCodes } from './linux.ts'

describe('linux parsers', () => {
  it('reads PRETTY_NAME and VERSION_ID from os-release, unquoting and ignoring comments', () => {
    const text = ['# comment', 'NAME="Ubuntu"', 'VERSION_ID="24.04"', "PRETTY_NAME='Ubuntu 24.04.1 LTS'", 'ID=ubuntu', 'HOME_URL="https://www.ubuntu.com/"', 'broken line without equals', ''].join('\n')
    expect(parseOsRelease(text)).toEqual({ prettyName: 'Ubuntu 24.04.1 LTS', name: 'Ubuntu', versionId: '24.04', id: 'ubuntu' })
    expect(parseOsRelease('')).toEqual({ prettyName: undefined, name: undefined, versionId: undefined, id: undefined })
  })

  it('unescapes backslash-quoted characters in os-release values', () => {
    expect(parseOsRelease('PRETTY_NAME="Arch \\"Rolling\\""').prettyName).toBe('Arch "Rolling"')
  })

  it('sums the aggregate cpu line of /proc/stat and counts iowait as idle', () => {
    const text = 'cpu  100 5 50 800 20 3 2 0 0 0\ncpu0 50 2 25 400 10 1 1 0 0 0\nintr 12345\n'
    expect(parseProcStat(text)).toEqual({ idle: 820, total: 980 })
    expect(parseProcStat('intr 1\nctxt 2')).toBeNull()
    expect(parseProcStat('cpu  abc def')).toBeNull()
  })

  it('reads MemTotal and MemAvailable from /proc/meminfo in bytes', () => {
    const text = 'MemTotal:       16000000 kB\nMemFree:         1000000 kB\nMemAvailable:    9000000 kB\nBuffers:          500000 kB\nCached:          3000000 kB\n'
    expect(parseMeminfo(text)).toEqual({ total: 16000000 * 1024, available: 9000000 * 1024 })
  })

  it('falls back to free + buffers + cached when MemAvailable is missing', () => {
    const text = 'MemTotal:       16000000 kB\nMemFree:         1000000 kB\nBuffers:          500000 kB\nCached:          3000000 kB\n'
    expect(parseMeminfo(text)).toEqual({ total: 16000000 * 1024, available: 4500000 * 1024 })
    expect(parseMeminfo('SwapTotal: 0 kB')).toBeNull()
  })

  it('maps sysfs battery capacity and status', () => {
    expect(parseBattery('85\n', 'Charging\n')).toEqual({ present: true, percent: 85, charging: true })
    expect(parseBattery('100', 'Full')).toEqual({ present: true, percent: 100, charging: true })
    expect(parseBattery('42', 'Discharging')).toEqual({ present: true, percent: 42, charging: false })
    expect(parseBattery('42', null)).toEqual({ present: true, percent: 42, charging: false })
    expect(parseBattery(null, 'Charging')).toEqual({ present: false })
    expect(parseBattery('n/a', 'Charging')).toEqual({ present: false })
  })

  it('keeps root, /home and removable media mounts; drops pseudo filesystems and the EFI partition', () => {
    const mk = (mount: string) => ({ mount, total: 1, used: 0, free: 1 })
    const disks = ['/', '/run', '/boot/efi', '/home', '/media/sam/USB', '/run/media/sam/SD Card', '/mnt/data', '/mnt', '/media', '/snap/core/1', '/'].map(mk)
    expect(filterLinuxMounts(disks).map(d => d.mount)).toEqual(['/', '/home', '/media/sam/USB', '/run/media/sam/SD Card', '/mnt/data'])
  })

  it('strips freedesktop field codes from Exec lines and keeps literal percents', () => {
    expect(stripExecFieldCodes('firefox %u')).toBe('firefox')
    expect(stripExecFieldCodes('code --new-window %F')).toBe('code --new-window')
    expect(stripExecFieldCodes('gimp-2.10 %U %i %c %k')).toBe('gimp-2.10')
    expect(stripExecFieldCodes('env FOO=100%% app %f')).toBe('env FOO=100% app')
  })

  it('parses a desktop entry: name, stripped exec, icon, categories and flags', () => {
    const text = ['[Desktop Entry]', 'Version=1.0', 'Type=Application', 'Name=Firefox Web Browser', 'Name[pt_BR]=Navegador Firefox', 'Exec=firefox %u', 'Icon=firefox', 'Terminal=false', 'Categories=Network;WebBrowser;', 'NoDisplay=false', '', '[Desktop Action new-window]', 'Name=New Window', 'Exec=firefox --new-window'].join('\n')
    expect(parseDesktopEntry(text, '/usr/share/applications/firefox.desktop')).toEqual({
      name: 'Firefox Web Browser',
      exec: 'firefox',
      icon: 'firefox',
      categories: ['Network', 'WebBrowser'],
      noDisplay: false,
      hidden: false,
      terminal: false
    })
  })

  it('reports NoDisplay / Hidden / Terminal flags and rejects non-application entries', () => {
    const hidden = parseDesktopEntry('[Desktop Entry]\nType=Application\nName=Helper\nExec=helper\nNoDisplay=true\nHidden=true\nTerminal=true\n', '/x/helper.desktop')
    expect(hidden).toMatchObject({ noDisplay: true, hidden: true, terminal: true, categories: [] })
    expect(parseDesktopEntry('[Desktop Entry]\nType=Link\nName=Docs\nURL=https://example.com\n', '/x/docs.desktop')).toBeNull()
    expect(parseDesktopEntry('[Other Group]\nName=Nope\n', '/x/nope.desktop')).toBeNull()
  })

  it('falls back to the desktop id when Name is missing', () => {
    expect(parseDesktopEntry('[Desktop Entry]\nExec=thing\n', '/usr/share/applications/org.example.Thing.desktop')?.name).toBe('org.example.Thing')
  })

  it('maps freedesktop categories onto the LSApplicationCategoryType vocabulary', () => {
    expect(mapDesktopCategory(['Development', 'IDE'])).toBe('public.app-category.developer-tools')
    expect(mapDesktopCategory(['Network', 'WebBrowser'])).toBe('public.app-category.productivity')
    expect(mapDesktopCategory(['Network', 'Chat'])).toBe('public.app-category.social-networking')
    expect(mapDesktopCategory(['Graphics', '2DGraphics', 'RasterGraphics'])).toBe('public.app-category.graphics-design')
    expect(mapDesktopCategory(['AudioVideo', 'Audio', 'Music'])).toBe('public.app-category.music')
    expect(mapDesktopCategory(['AudioVideo', 'Video', 'Player'])).toBe('public.app-category.video')
    expect(mapDesktopCategory(['Office', 'Finance'])).toBe('public.app-category.finance')
    expect(mapDesktopCategory(['Game', 'ArcadeGame'])).toBe('public.app-category.games')
    expect(mapDesktopCategory(['System', 'Settings'])).toBe('public.app-category.utilities')
    expect(mapDesktopCategory(['GTK', 'GNOME'])).toBeUndefined()
    expect(mapDesktopCategory([])).toBeUndefined()
  })

  it('parses nmcli terse device status, including escaped colons', () => {
    const text = 'wifi:connected:Home Wi\\:Fi:wlan0\nethernet:unavailable:--:eth0\nloopback:connected (externally):lo:lo\n\n'
    expect(parseNmcliDevStatus(text)).toEqual([
      { type: 'wifi', state: 'connected', connection: 'Home Wi:Fi', device: 'wlan0' },
      { type: 'ethernet', state: 'unavailable', connection: '', device: 'eth0' },
      { type: 'loopback', state: 'connected (externally)', connection: 'lo', device: 'lo' }
    ])
  })

  it('parses nmcli terse wifi list rows and marks the active network', () => {
    const rows = parseNmcliWifi('yes:Home Wi\\:Fi:78\nno:Neighbour:45\nno::12\n')
    expect(rows).toEqual([
      { active: true, ssid: 'Home Wi:Fi', signal: 78 },
      { active: false, ssid: 'Neighbour', signal: 45 },
      { active: false, ssid: '', signal: 12 }
    ])
    expect(parseNmcliWifi('')).toEqual([])
  })

  it('parses recently-used.xbel bookmarks newest first, decoding percent-escapes and entities', () => {
    const xml = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<xbel version="1.0">',
      '  <bookmark href="file:///home/sam/Documents/Report%20Q3.pdf" added="2026-09-10T10:00:00Z" modified="2026-09-15T09:30:00Z" visited="2026-09-16T08:00:00Z">',
      '    <info><metadata owner="http://freedesktop.org"><mime:mime-type type="application/pdf"/></metadata></info>',
      '  </bookmark>',
      '  <bookmark href="file:///home/sam/Pictures/caf%C3%A9%20&amp;%20bar.png" added="2026-09-01T00:00:00Z" modified="2026-09-17T12:00:00Z" visited="2026-09-17T12:00:00Z"/>',
      '  <bookmark href="https://example.com/not-a-file" added="2026-09-01T00:00:00Z" modified="2026-09-18T12:00:00Z"/>',
      '  <bookmark href="file:///home/sam/old.txt" added="2026-01-01T00:00:00Z" modified="2026-01-02T00:00:00Z"/>',
      '</xbel>'
    ].join('\n')
    const rows = parseRecentlyUsed(xml, 10)
    expect(rows.map(r => r.path)).toEqual(['/home/sam/Pictures/café & bar.png', '/home/sam/Documents/Report Q3.pdf', '/home/sam/old.txt'])
    expect(rows[1]).toEqual({ path: '/home/sam/Documents/Report Q3.pdf', modifiedAt: Date.parse('2026-09-15T09:30:00Z'), visitedAt: Date.parse('2026-09-16T08:00:00Z') })
    expect(rows[2].visitedAt).toBe(rows[2].modifiedAt)
    expect(parseRecentlyUsed(xml, 1)).toHaveLength(1)
    expect(parseRecentlyUsed('<xbel/>', 5)).toEqual([])
  })

  it('builds file URIs the way GLib does (spaces and non-ASCII escaped, path punctuation kept)', () => {
    expect(fileUri('/home/sam/My Photo.jpg')).toBe('file:///home/sam/My%20Photo.jpg')
    expect(fileUri('/home/sam/café.png')).toBe('file:///home/sam/caf%C3%A9.png')
    expect(fileUri("/tmp/a(b)'c,d:e@f&g=h+i$j!k~l*m-n_o.p")).toBe("file:///tmp/a(b)'c,d:e@f&g=h+i$j!k~l*m-n_o.p")
    expect(fileUri('/tmp/50% off #1?.txt')).toBe('file:///tmp/50%25%20off%20%231%3F.txt')
  })
})
