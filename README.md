# Everything
List, search, and browse to every app, tab, window, agent... everything. An Omarchy plugin.

Everything 0.0.1 is a native Omarchy Quattro switcher for windows, tabs,
panes, and other actionable things. Its chevron button
(`nf-fa-chevron_down`, U+F078) opens a keyboard-first search panel for native
tabs, terminal panes, tmux and Herdr containers, Herdr agents, Neovim buffers,
and every managed window.

It targets the current Omarchy 4 shell/plugin API and the application
interfaces shipped with that release. There are no legacy Hyprland,
shell-plugin, terminal, or Neovim compatibility paths.

## Install

Install and enable the Git checkout with Omarchy's plugin manager:

```bash
omarchy plugin add https://github.com/brianblakely/omarchy-everything.git --enable --yes
```

`b.everything` declares `defaultSection: "left"`; current Quattro placement
puts a newly enabled left-side widget immediately after workspaces. To restore
that placement later:

```bash
omarchy bar move b.everything --after omarchy.workspaces
```

For a local development checkout, place or clone the complete repository at
`~/.config/omarchy/plugins/b.everything`, then run:

```bash
omarchy-shell shell rescanPlugins
omarchy plugin enable b.everything --after omarchy.workspaces
```

The plugin needs Python 3 and the PyGObject Gio/AT-SPI bindings supplied by the
current Omarchy installation. Individual adapters activate only when their
corresponding application or local runtime socket exists.

## Open it

Click the chevron in the bar, or use:

```bash
omarchy-shell shell toggle b.everything
```

Shell routing opens the widget on the currently focused monitor. To make
`SUPER + SLASH` the user-owned shortcut, add this to
`~/.config/hypr/bindings.lua`:

```lua
hl.unbind("SUPER + SLASH")
o.bind("SUPER + SLASH", "Everything", "omarchy-shell shell toggle b.everything")
```

This deliberately replaces Omarchy's current **Monitor scaling up** binding.
Everything never edits Hyprland configuration automatically. After editing a
Lua config, validate it with `hyprctl reload` and `hyprctl configerrors`.

## Keyboard controls

The panel opens in Omarchy's standard keyboard-navigation mode. Press `/` or
click the search field to edit the query; while editing, every printable key,
including H, J, K, and L, belongs to the search field. Every space-separated
query token must fuzzily match a title, breadcrumb/context, provider, type,
badge, or search term. Results are grouped by exact kind in a stable order;
within each group, title matches rank first, followed by context/type, the
current thing, and recency. Opening beneath a stationary pointer does not move
the keyboard highlight; pointer selection begins only after actual movement.

| Focus | Keys | Action |
|---|---|---|
| Navigation | `H`, `K`, `Left`, `Up` | Move to the previous result |
| Navigation | `J`, `L`, `Down`, `Right` | Move to the next result |
| Navigation | `Home`, `End`, `g`, `G` | Move to the first or last result |
| Navigation | `Page Up`, `Page Down`, `Ctrl+U`, `Ctrl+D` | Move one visible page |
| Navigation | `Ctrl+P`, `Ctrl+N` | Move to the previous or next result |
| Navigation | `Enter`, `Space` | Close Everything, then activate the highlighted thing |
| Navigation | `/` | Focus the search field |
| Navigation | `X`, `Backspace`, `Delete` | Hide only the actively highlighted result |
| Navigation | `Tab`, `Shift+Tab` | Use Omarchy's standard adjacent-panel navigation |
| Search | `Down`, `Tab` | Return to navigation at the first result |
| Either | `Escape` | Clear a nonempty query and return to search; a second press closes |

Hidden IDs stay filtered across refreshes and panel reopenings. They are held
only in the shell service's memory and reset when this plugin service or
`omarchy-shell` reloads.

Every result has an internal deterministic UUID derived from its stable
provider, kind, and native identity. Rebuilding an identical ranked sequence
does not touch the list UI. When the sequence changes, a surviving highlighted
thing keeps both its highlight and its visual distance from the top of the
list; short lists simply keep the highlight. If that thing disappeared, the
first result is selected. The query and keyboard focus remain unchanged during
that opening. Closing and reopening clears the query, selects the first result,
and resets the list to the top.

## What appears

- Every mapped Hyprland client, including other workspaces, groups,
  scratchpads, and hidden windows.
- Strict native browser tabs for Chromium, Chrome, Brave variants, Edge,
  Firefox, Zen, Vivaldi, Helium, and LibreWolf, plus strict native GTK/Qt
  application tabs exposed through AT-SPI.
- Kitty OS windows, tabs, and panes; Ghostty 1.3.1 native tabs and surfaces;
  exact Foot and Alacritty windows.
- Same-user tmux sessions, windows, and panes from default and custom sockets.
- Running local Herdr protocol-20 sessions, workspaces, tabs, panes, and agents.
- Listed buffers from current-user Neovim runtime sockets, including modified,
  hidden, loaded, and unloaded buffers.

Processes are routing metadata, never results. A shell, `btop`, or any other
ordinary process appears only through an actionable containing thing.
Applications without a reliable current native-tab adapter remain available
as their exact outer Hyprland windows. Page-authored ARIA tabs, web/editor DOM
tabs, layers, and arbitrary `/proc` entries are never listed.

Browser discovery is AT-SPI-only in 0.0.1. It provides native tab titles but
does not promise URLs or favicons. There is no browser extension or native
messaging host.

When a nested tmux, Herdr, Neovim, or Ghostty host cannot be identified without
guessing, Everything may open a fresh attached terminal client or Neovim
remote UI. For a Neovim buffer this happens only when the buffer is hidden; a
buffer already shown selects its first existing window and reuses its
container. Everything never hijacks a remote tmux client or routes by a merely
similar title. Herdr discovery is local-only.

## Runtime behavior and privacy

The Python helper starts only while at least one monitor's panel is open or an
activation is pending. Hyprland windows arrive first; independent providers
then stream partial snapshots. Nonintrusive adapters refresh about every two
seconds while open. Ghostty's modal palette bridge runs once per opening and
again only to validate an activation; it is excluded from periodic scans.

AT-SPI is enabled at runtime only for that helper lease. Screen-reader mode is
never enabled, and a guard restores the prior AT-SPI state on shutdown,
cancellation, or helper failure.

Everything makes **no network requests** and has no install hooks, privileged
operations, persistent background worker, browser extension, analytics, or
on-disk hidden-item database. See [Security and runtime access](docs/security.md)
for every command, socket, `/proc` read, temporary state change, and synthetic
key used by the plugin. The wire contract is in
[JSON-lines protocol](docs/protocol.md), and provider details are in
[Provider behavior](docs/providers.md).

## Develop and test

```bash
tests/all.sh
```

That runs Python and JavaScript unit tests, Python compilation, QML lint, an
offscreen Quickshell entrypoint/lease fixture, and
`omarchy plugin validate .`. The live application matrix and reproducible
manual checks are documented in [Testing](docs/testing.md).

Licensed under the [MIT License](LICENSE).
