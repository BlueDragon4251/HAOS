# Make it yours

## Themes

A theme recolours everything at once: the shell, the in-shell terminal, the wallpaper's colours,
Hermes's own command-line skin and, on Herald OS Linux, the window borders, GTK apps, the lock
screen and the rescue terminal. Settings > Appearance shows every theme as a card; click one. Or say
"switch to the Paper theme".

Herald OS ships twelve: Ocean (the default), Graphite, Ice, Violet, Ember, Forest, Dusk, Onyx (true
black), Rose, Lagoon, and two light ones, Paper and Cloud.

- **From an image.** "Make a theme from an image" in Settings, or "make a theme from my
  wallpaper", takes the colours of a photo or artwork, builds a complete theme from them and uses
  the image as the wallpaper. On Herald OS Linux, `herald-os theme new <image> [name]` does the same.
- **From a description.** Ask Hermes: "make me a theme that feels like a foggy forest morning". It
  writes the theme file and switches to it.
- **From someone else.** Paste the https address of a theme repository into "Install themes from
  git" (or `herald-os theme install <url>`). Only colours and images are kept, so a theme can never
  run code on your machine.
- **Follow Hermes.** With "Follow Hermes skins" on, changing Hermes's skin with `/skin` in a chat
  restyles Herald OS too.

### Writing a theme by hand

Your themes live in `~/.config/herald-os/themes/<name>/theme.json` on every platform. The name is
the folder name: lowercase letters, digits and dashes.

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

Every colour is `#rrggbb`. Keep text (`fg`) at 7:1 contrast or more against `bg` and the accent at
3:1 or more. A light theme sets `"scheme": "light"` and `"gtk": {"color_scheme": "default",
"theme": "Adwaita"}`. `"wallpaper"` is `"default"` (the drawn wallpaper, tinted to the theme) or an
image file in the theme's folder. An optional `"terminal"` block sets the terminal's 16 colours.

To share a theme, put its folder (or several, one per theme) in a git repository.

## Fonts

Settings > Appearance > Fonts sets the interface font and the code font (the terminal and code
views); leave a field empty for the default. "Use the font Inter" works too. On Herald OS Linux,
`herald-os font list` shows what is installed and `herald-os font set <family> [--mono]` sets it.

## Keyboard shortcuts

On Herald OS Linux, your own binds go in `~/.config/niri/local.kdl`, which Herald OS never
overwrites. niri reloads it as soon as you save:

```kdl
binds {
    Mod+Shift+O hotkey-overlay-title="Obsidian" { spawn "flatpak" "run" "md.obsidian.Obsidian"; }
    Mod+Ctrl+D { spawn "herald-os" "theme" "set" "herald-dusk"; }
}
```

Check a bind is free in the hotkey overlay (`Super+K`) first.

## When something happens

Herald OS notices these moments: you log in, the computer wakes, you unlock the screen, you come
back after a break, the battery runs low, the network changes, a program crashes, the theme
changes, and Herald OS finishes an update (plus locking the screen and going to sleep, for scripts).

### Automations

On the Automations page, a new automation can run "On a schedule" or "When something happens".
For a crash you can name the program, for a network change the Wi-Fi network. Hermes runs it each
time, with the same history and delivery as scheduled automations. Or just ask: "every time I log
in, tell me what is on my calendar".

### Hooks

For chores that need no Hermes (a script, a sound, syncing a folder), drop an executable script into
`~/.config/herald-os/hooks/<event>.d/`, where `<event>` is `login`, `wake`, `unlock`, `returned`,
`battery-low`, `network-change`, `crash`, `theme-set`, `after-update`, `lock` or `sleep`. It runs
with the event name as its first argument and in `HERALD_EVENT`, each detail in its own variable
(`HERALD_EVENT_APP` for a crash, `HERALD_EVENT_PERCENT` for low battery, `HERALD_EVENT_WIFI` for a
network change) and everything as JSON in `HERALD_EVENT_JSON`. Files ending in `.sample` are
skipped, and a hook gets two minutes.

```sh
#!/bin/sh
# ~/.config/herald-os/hooks/battery-low.d/dim
brightnessctl set 30%
```

On Herald OS Linux, `herald-os hook list` shows your hooks, `herald-os hook install <event>
<script>` copies one in, and `herald-os event <name>` sets one off to test it.
