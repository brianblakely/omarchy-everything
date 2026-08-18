# Testing

## Automated suite

From the repository root:

```bash
tests/all.sh
```

The suite performs:

- Python compilation and 30+ unit/protocol tests;
- fuzzy token ranking over titles and displayed group names only, explicit
  exclusion of context/provider/badges/search terms, stable kind grouping,
  active/recency order, duplicate identity handling, token authentication, and
  hidden-result persistence;
- deterministic kind icons, one-line row density, vital-metadata selection,
  JavaScript/Qt-list badge normalization, exclusion of redundant kind labels,
  Herdr immediate-parent metadata, and absence of visual metadata pills;
- absence of panel scan, count, warning, and empty-result messages while
  automatic discovery continues;
- every documented keyboard alias, focus-sensitive Delete/Backspace ownership,
  safe selection after removal, stationary-pointer filtering, deliberate
  pointer selection, and close-before-activation ordering;
- argv injection rejection, command timeout/kill behavior, JSON-lines request
  correlation, malformed-request recovery, and stale-token rejection;
- partial provider streaming, provider failure isolation, stale-row removal,
  and scan cancellation propagation;
- AT-SPI state restoration without screen-reader writes, browser-family
  matching, and exclusion of document-authored/tool tab strips;
- Hyprland mapped/hidden/group/scratchpad handling and Herdr protocol-20 shape;
- Ghostty effective-binding filtering, 9+ virtualized rows, duplicate
  fingerprint occurrences, fail-closed mutations, and exact-address paired
  key-state construction;
- Neovim's unique/ambiguous Herdr and multi-surface Ghostty routing;
- QML lint and an offscreen Quickshell fixture that synchronously loads both
  entrypoints and exercises two independent monitor leases. The fixture swaps
  only compositor-dependent `KeyboardPanel` for an API-equivalent test double,
  because Qt's offscreen backend cannot instantiate a layer-shell
  `PanelWindow`;
- `omarchy plugin validate .` against the installed current manifest schema.

## Live helper smoke test

To inspect live discovery without activating anything, start the helper,
send one `scan` request, read partials until the full snapshot, then send
`shutdown`. Confirm afterward that `org.a11y.Status.IsEnabled` equals its value
before the run. The automated protocol tests use `--test-mode`; live smoke
testing intentionally does not.

Useful observation commands are:

```bash
hyprctl -j clients
omarchy-shell shell listPlugins
omarchy menu keybindings --print
```

## Manual acceptance matrix

Install the plugin into a disposable user plugin checkout, enable it, and run
these cases on the current Omarchy 4 package set. For each case verify both the
row/breadcrumb and exact activation target, then close the target and verify a
single refresh followed by a visible stale notification.

### Shell and windows

- Multiple monitors: invoke the shell shortcut while each monitor is focused;
  only that monitor's widget opens. Open two panels by pointer to confirm the
  helper remains leased until both close.
- Confirm search owns initial focus and printable input edits it immediately.
  Press Down or Tab to enter navigation, then confirm H/K and J/L move backward
  and forward like the arrow keys, Enter/Space activates, X hides, and Tab
  follows Omarchy's adjacent-panel navigation. Press `/` to return to search
  and confirm H, J, K, and L insert text instead of moving the selection.
- Managed clients across numbered workspaces, a special scratchpad, a group,
  hidden state, and duplicate titles. Confirm layers do not appear.
- Confirm Foot and Alacritty expose their exact separate Hyprland windows but
  no fabricated native tabs/panes.
- Start `btop`, ordinary shells, and background processes. Confirm none becomes
  a row except through a window, pane, or supported container.

### Browsers and native application tabs

- Chromium/Chrome, Brave variants, Edge, Firefox, Zen, Vivaldi, Helium, and
  LibreWolf where installed: multiple windows, private windows, PWAs, duplicate
  titles, hidden tabs, and horizontal/vertical/custom native strips.
- A test page containing ARIA `tablist`/`tab` elements plus browser developer
  tools. Confirm neither page-authored nor tool tabs appear.
- A GTK/Qt application with genuine native tabs and an editor/web app with DOM
  tabs. Confirm only the former expands and both retain outer-window rows.
- Confirm browser rows are title-only and never claim a URL or favicon.

### Kitty and Ghostty

- Kitty: multiple OS windows, tabs, panes, duplicate titles, a removed pane,
  and a stale runtime socket. Confirm numeric IDs select the intended object
  before its exact outer window is focused.
- Ghostty 1.3.1: multiple processes/windows, 9+ tabs, horizontal and vertical
  splits, unselected tabs, identical title/cwd rows, and enough rows to force
  palette virtualization.
- Mutate Ghostty surfaces mid-scan and mid-activation. Confirm fingerprint
  validation fails rather than selecting a neighbor.
- Run a PTY key logger while exercising Ghostty discovery. Confirm no
  `HOME`/`DOWN`/`RETURN`/`ESCAPE` reaches the PTY and no `Focus:` text is typed.
- Change Ghostty tab bindings and confirm Everything uses only the effective
  local binding plus AT-SPI selection verification.

### tmux, Herdr, and Neovim

- tmux: default and custom sockets, attached and detached sessions, multiple
  clients, a remote-only client, immutable duplicate titles, and closed
  targets. Confirm only one unique local client is switched; otherwise a fresh
  local attach opens.
- Herdr: multiple running local protocol-20 sessions, detached sessions,
  workspaces/tabs/panes, and agents in idle/working/blocked/done states. Confirm
  exact socket focus methods and fresh attach behavior for ambiguous hosts.
- Neovim: displayed, hidden, loaded, unloaded, and modified listed buffers;
  existing windows on another tab; standalone, tmux-nested, and Herdr-nested
  servers. Confirm a displayed buffer selects its first existing window and
  never starts a new terminal attach or remote UI; confirm `:hide buffer`
  preserves modified buffers.
- Put nested Neovim instances in duplicate-cwd Herdr panes and multi-split
  Ghostty surfaces. Confirm inherited Herdr pane IDs disambiguate duplicate
  cwd values, and only hidden buffers with ambiguous hosts open a fresh
  `--remote-ui` rather than guessing.

### Lifecycle and recovery

- Open the panel and confirm Ghostty scans once and closes its palette. Leave
  the panel open through several two-second polls and confirm socket/CLI
  updates merge without the modal reopening.
- With a middle row highlighted, refresh an unchanged result set and confirm
  the list model is not replaced. Then reorder or add rows and confirm the
  same UUID stays highlighted at the same visual offset. Remove that row and
  confirm selection returns to the first result. Repeat with a short list that
  cannot scroll and confirm only the highlight is preserved.
- Populate several kinds at once. Confirm each exact kind has one accessible
  heading, groups remain in stable order, and ranking is preserved within each
  group. Confirm Herdr agents precede every other Herdr group and Herdr sessions
  follow all of them. Refresh while the selected row crosses a heading and
  confirm its visual offset is retained.
- Confirm every row is one line with a kind icon on the left and exactly one
  status or context value on the right. Exercise long titles and paths, active
  states, modified buffers, detached sessions, and special workspaces; confirm
  text elides without overlap, kind labels never repeat in the right-side
  value, and no pill-shaped metadata is rendered.
- Scroll to and highlight a middle result, close the panel, and open it again.
  Confirm the first result is highlighted and the list is at its scroll origin.
- Open the panel while the pointer is stationary over a result. Confirm that
  the pointer does not steal the keyboard highlight; move it deliberately and
  confirm the highlight follows exactly one row. Repeat across a list refresh.
- Kill the helper during a scan and during activation. Confirm the panel stays
  message-free, activation failure uses the external notification path,
  restart behavior stays bounded, no worker persists after close, and the
  prior AT-SPI state is restored.
- Hide rows, close/reopen the panel, and wait for an automatic refresh: they
  remain hidden. Reload `b.everything` or `omarchy-shell`: they return.
