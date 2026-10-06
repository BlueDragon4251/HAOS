---
name: herald-os-tailor
description: Change Herald OS itself - make and switch themes, fonts and the wallpaper, keybindings, settings, routines and hooks
metadata:
  hermes:
    tags: [herald-os, customise, themes, settings, linux, macos]
---

# Tailor Herald OS

Herald OS is meant to be shaped by the person using it, and by you on their behalf. Use this when
they ask to change how Herald OS looks or behaves: "make me a calm green theme", "use a bigger
font", "add a shortcut for Obsidian", "do this every time I log in".

Ground rules:

- Change settings through `os_ui` commands, never by editing `~/.hermes/herald-os/prefs.json`
  while the shell runs (it rewrites that file).
- Say what you changed and how to undo it in one sentence ("Switched to Dusk; say 'use the
  ocean theme' to go back").
- Ask before anything large or hard to undo, and keep a copy of any file you replace.

## Themes

A theme recolours everything at once: the shell, your own CLI skin and, on Herald OS Linux, the
compositor, GTK apps, the lock screen and the terminal.

- `os_ui action=run command=theme.list`, then `theme.set args={"theme": "<name>"}`.
- From an image: `theme.generate args={"image": "<path>", "name": "<label>"}` (optional
  `"scheme": "dark" | "light"`). It saves the theme, makes the image the wallpaper and applies it.
- From a description ("a sunset theme", "something like old paper"): write the theme yourself.
  Create `~/.config/herald-os/themes/<name>/theme.json` with `write_file`, then run `theme.set`.
  `<name>` is the folder name: lowercase letters, digits and dashes. The file:

```json
{
  "name": "sunset",
  "label": "Sunset",
  "description": "Warm dusk orange on deep plum.",
  "shell": { "scheme": "dark" },
  "wallpaper": "default",
  "colors": {
    "bg": "#170d14", "bg2": "#26131f", "surface": "#2e1726",
    "fg": "#fbefe9", "fg_dim": "#c4a0a4",
    "accent": "#ff8a4c", "accent_strong": "#ffa36e",
    "border_active": "#ff8a4c", "border_inactive": "#3e1f30",
    "urgent": "#ff6b6b", "ok": "#5fd39a", "warn": "#f2c25e"
  },
  "gtk": { "color_scheme": "prefer-dark", "theme": "Adwaita-dark" }
}
```

  Every colour is `#rrggbb`. Text (`fg`) needs at least 7:1 contrast against `bg`, the accent at
  least 3:1. Dark themes keep `bg` very dark; light themes set `"scheme": "light"`, a very light
  `bg`, dark `fg`, and `"gtk": {"color_scheme": "default", "theme": "Adwaita"}`. `bg2` and
  `surface` are a few steps from `bg` toward the accent (dark) or toward white (light). A
  `"terminal"` block (`background`, `foreground`, `cursor`, a 16-colour `palette`) is optional;
  the shell derives one when it is missing. `"wallpaper"` is `"default"` (the drawn Herald
  wallpaper, tinted to the theme) or an image file inside the theme's folder.
- Someone shared a theme repository: `theme.install args={"url": "https://…"}`. Only colours and
  images are kept.
- Undo: `theme.set args={"theme": "herald-ocean"}`, the default.

## Fonts and wallpaper

- `font.list` (optional `filter`), then `font.set args={"family": "Inter"}` for the interface or
  `{"family": "JetBrains Mono", "kind": "mono"}` for code and the terminal. `"default"` resets.
- `wallpaper.set args={"image": "<path>"}`, or `"default"` for the drawn wallpaper.

## Settings

The shell's settings are commands: `accent.set`, `dock.autoHide`, `motion.reduce`,
`voice.engine.set`, `voice.wake.set`, `crash.help`, `theme.followHermes` and more. Run
`os_ui action=list` for the full list with arguments, and `settings.open section=<id>` to show the
person the result.

## Keybindings (Herald OS Linux)

The compositor is niri. Its managed config (`~/.config/niri/config.kdl`) is rewritten on update;
the person's own settings go in `~/.config/niri/local.kdl`, which is included last and never
touched by Herald OS. Add binds there:

```kdl
binds {
    Mod+Shift+O hotkey-overlay-title="Obsidian" { spawn "flatpak" "run" "md.obsidian.Obsidian"; }
    Mod+Ctrl+T { spawn "herald-os" "open" "terminal"; }
}
```

niri reloads the file as soon as it is saved. Check it with
`niri validate -c ~/.config/niri/config.kdl` in the terminal, and read the hotkey overlay
(`Mod+K`) before reusing a key: Herald OS already binds many `Mod+…` combinations. Any
`herald-os` command can be a bind (`spawn "herald-os" "theme" "set" "herald-dusk"`).

## Routines

- Something on a schedule: `automation.create args={"name": …, "schedule": "every weekday at 9am", "prompt": …}`.
- Something each time an event happens ("every time I log in", "when the battery is low",
  "when Safari crashes"): `automation.create` with `"event"` (and `"match"`) instead of a schedule,
  or a hook script for chores that need no Hermes. The `herald-os` skill lists the events and how
  hooks run.
