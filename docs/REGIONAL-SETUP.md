# HAOS regional setup (locale + keyboard)

**New installations**: on the first HAOS session, the wizard asks for two
independent options before Wi-Fi and account setup:

- Session language: German (Austria/Germany), English (US/UK), French.
- Keyboard layout: Austrian QWERTZ, German QWERTZ, US, UK, French, Swiss.

The keyboard selection is saved in the user-owned
`~/.config/herald-os/region.json` and rendered into the managed
`~/.config/niri/herald-os.kdl` by `herald-os keymap apply`. Niri reloads
the configuration on change. The selected layout persists through restart
and bootc image updates because the user profile is on /var/home.

The user's session locale is stored in
`~/.config/herald-os/locale` and
`~/.config/environment.d/90-haos-locale.conf`.
The session launcher exports LANG and LANGUAGE from a fixed allowlist.
The selected session locale applies to new applications after a new login;
it does **not** translate the hard-coded English strings of the Herald/HAOS
desktop, which require dedicated UI localization work.

A person can change these preferences later under
**Settings > General > Language & keyboard** without a root password.
"Herald/Omarchy keymap" elsewhere in General changes keyboard shortcuts,
not the physical QWERTZ/QWERTY layout.

**System-wide locale and console keyboard** are independent and more privileged.
The observer setup intentionally cannot replace root/recovery keymaps. To align
the system-wide console and service defaults, log in as the separately enrolled
owner and execute on a trusted terminal:

```sh
su - YOUR_OWNER
sudo haos-owner region apply --language de_AT.UTF-8 --keyboard at
sudo haos-owner region status
```

This uses `localectl` with fixed allowlists. Log out and start a new session
to apply new process locale. The first-boot UI does not invoke this command
or claim system-wide authority. The CLI is present only in images containing
the new code, not an already-booted older image.

**Existing older HAOS system (before these changes):** if you know the root
password, from a genuinely privileged root console run:
```sh
localectl set-keymap de-latin1
localectl set-x11-keymap at
localectl set-locale LANG=de_AT.UTF-8
```
Niri with an empty XKB section reads `org.freedesktop.locale1`, so X11
keyboard changes are effective there. Do not use the locked observer account
to bypass this system boundary.

The new layout chooser and locale pack additions still require real image
build and on-device acceptance. Existing media/installations are unchanged.
