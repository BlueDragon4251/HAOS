# Hermes OS shell: design and engineering brief

Read this before adding or changing a page. It is the contract between pages, the shell, the
stores and the Electron bridge. The target look is
"deep-blue glass on a living wallpaper": one main Hermes window with a persistent left sidebar
and swappable pages, floating glass windows for secondary apps, a dock, a menu bar.

## Layout model

- `src/app/shell/Desktop.tsx` composes Wallpaper, MenuBar, the window layer, Dock and overlays.
- `src/store/windows.ts` is the window manager. `showPage(pageId)` switches the main window's page;
  `openApp(appId)` opens floating apps (`terminal`, `system`, `chat-popout`). Never navigate any
  other way. `$page` is the current page id.
- `src/app/apps.ts` is the registry: `PAGES` (sidebar), `FLOATING_APPS`, `HERMES_APPS`,
  `FEATURED_NATIVE` (macOS apps by name). Icons are ids rendered by `AppGlyph` / `AppTile`
  (`src/components/app-icon.tsx`); `HermesAvatar` is the brand mark.
- A page is a component exported from `src/app/<page>/<Name>Page.tsx` and registered in
  `src/app/shell/MainWindow.tsx`. It fills its container (`h-full`), owns its scrolling, and is kept
  mounted when hidden (visibility is not lifecycle).

## Visual vocabulary (tokens only, never literals)

Tailwind v4 tokens in `src/styles.css`:

| Use | Token / class |
| --- | --- |
| Page/panel fill | `.glass` (blur + stroke + shadow), `.glass-card`, `.glass-card-hover`, `.glass-card-selected` |
| Inputs | `.glass-input` |
| Text | `text-fg`, `text-fg-2` (secondary), `text-fg-3` (tertiary), `text-fg-4` (quiet) |
| Strokes | `border-line`, `border-line-strong`, `bg-line` for 1px dividers, `.hairline` |
| Accent | `bg-accent`, `text-accent-strong`, `bg-accent-soft`; semantic `ok` (mint), `progress` (cyan), `warn`, `danger`, `info` |
| Radii | `rounded-lg` (12) for controls, `rounded-xl` (16) for cards, `rounded-2xl` (22) for windows |
| Icon tiles | `AppTile` / `.icon-tile` (blue glass square with a glyph) |
| Motion | `.page-enter`, `.stagger` on lists, `.animate-rise` / `.animate-pop` for popovers, `.shimmer` for loading; `src/lib/motion.ts` for durations |

Primitives in `src/components/ui/glass.tsx`: `PageHeader`, `GlassCard`, `Pill`, `StatusDot`,
`Tabs`, `Chips`, `SearchField`, `Toggle`, `Section`, `LinkAction`, `KeyValue`, `GlassButton`,
`MoreButton`, `Dropdown`, `EmptyGlass`, `ProgressBar`. Older primitives in `ui/primitives.tsx`
(`Badge`, `Spinner`, `Switch`, `Row`, `Meter`) still work but prefer the glass set for new pages.
Icons: `@tabler/icons-react`.

Composition rules: header row (tile + title + subtitle, actions right) at the top of every page;
master/detail pages use a 3:2 split with the detail as a `GlassCard`; lists are rows or cards
with 12px gaps; selected item uses `glass-card-selected`; secondary text 12-12.5px; headings
20px semibold in headers, 14px semibold in sections. No dark borders, no card-in-card beyond
one level, no literal colours. Every interactive element has an `aria-label` or visible text.

## Data and actions

Gateway (Hermes runtime) via `src/store/gateway.ts`:
`gatewayRequest(method, params)` typed by the upstream contract (`RpcMethods`), `onGatewayEvent`.
REST via `src/lib/rest.ts` (`rest.get/post/put/del`, paths under `/api/`). Loaders:
`useBackendData(loader, deps)` (refetches on reconnect) and `useLocalData(loader, deps)` in
`src/lib/use-async.ts`.

Stores (nanostores; subscribe with `useStore`):

- `store/chat.ts`: `$chats`, `$activeChat`, `createChat`, `openStoredSession`, `sendPrompt`, `runSlash`, `interruptChat`.
- `store/sessions.ts`: `$sessions` (rows), `$runtimeIds` (stored -> runtime id), `refreshSessions`, `deleteSession`.
- `store/missions.ts`: `$missions`, `$activeMissions`, `$reviewMissions`, `$completedMissions`, `$todos`, `$artifacts`, `$allArtifacts`, `$activity`, `markReviewed`. A Mission is a derived view of a session (goal, todo steps, progress %, agents, artifacts, status active|review|queued|completed).
- `store/agents.ts`: `$agents` (live subagents).
- `store/requests.ts`: `$pendingRequests`, `resolveRequest` (approval / clarify / sudo / secret).
- `store/notifications.ts`: `notify()`, `$notifications`.
- `store/spaces.ts`: `$spaces`, `$activeSpace`, `setActiveSpace`, `addSpace`.
- `store/backend.ts`: `$backend`, `$prefs`, `updatePrefs`, `$env`.
- `store/system.ts`: `useSystemStats()`, `useSystemInfo()`, `useNetworkStatus()`.
- `store/native-apps.ts`: `useNativeApps()` -> `{ apps, iconFor(path) }`, `findNativeApp(names)`.

Electron bridge `window.hermesOS` (typed in `preload/index.ts`):
`backend.{getState,onState,restart,rest,logTail}`, `system.{info,stats,processes,network,subscribeStats}`,
`apps.{list,launch,icon}`, `fs.{home,readDir,readFile,reveal,openPath,openIn,recent,thumbnail,imageInfo,writeText,mkdir,rename,trash,exportPdf,pickFiles,dirSize}`,
`calendar.today()`, `terminal.*`, `notifications.native`, `window.*`, `shell.openExternal`,
`prefs.{get,set}`, `bridge.{readPolicy,writePolicy,readAudit}`, `env()`.

Hermes data on disk (read through `fs.readFile`, write through `fs.writeText`):
memories in `$HERMES_HOME/memories/MEMORY.md` and `USER.md`, entries separated by a line `§`.
`$HERMES_HOME` comes from `$env.get().hermesHome`.

## Rules

- Backend truth is cached, not owned: merge refreshes, be optimistic then honest, guard stale responses.
- No background event may steal focus or navigate. Offer; don't hijack.
- Every user-facing mutation of the machine goes through either a user-initiated `fs.*` call
  (inside the home folder) or Hermes's audited bridge tools; never spawn shell commands from the renderer.
- Reduced motion (`prefers-reduced-motion` or the pref) must collapse all animation.
- Keep pages self-contained under their directory; shared changes (stores, IPC, primitives) are
  proposed in the page's report, not made ad hoc.
