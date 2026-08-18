# Provider behavior

## Hyprland windows

Everything reads current `hyprctl -j clients` data and emits every mapped
managed client. Workspace, group, scratchpad, and hidden state only add
context; they never exclude a client. Activation rechecks PID and Linux process
birth before focusing the exact address through current `hl.dsp.focus`.
Layer surfaces are outside the clients API and are not results.

Foot and Alacritty have no internal Linux tab/split adapter in the supported
versions, so their only native things are their exact managed windows. tmux,
Herdr, and Neovim nested inside them are still expanded. This
matches [Alacritty's explicit non-goal of providing tabs or splits](https://github.com/alacritty/alacritty#faq).

## Browser and application tabs

The AT-SPI provider looks for actionable `PAGE_TAB_LIST`/`PAGE_TAB` objects
outside every `DOCUMENT_*` subtree. It rejects dock, tool, sidebar, inspector,
and developer-tool strips, then chooses a browser's primary strip by real page
tab count with depth as a tie-breaker. This supports horizontal, vertical, and
custom native tab-strip layouts without accepting page-authored ARIA tabs.

Recognized current Omarchy browser classes cover Chromium, Chrome, Brave
variants, Edge, Firefox, Zen, Vivaldi, Helium, and LibreWolf. PWA and private
windows use the same strict per-window matching. Generic GTK/Qt applications
must expose a shallow, fully actionable native tab strip. DOM/editor tabs with
no reliable external adapter remain represented by their outer window.

AT-SPI exposes titles. URLs, favicons, and browser history are not part of the
0.0.1 contract. The browser-side assumptions are intentionally limited to the
[Chromium accessibility architecture](https://chromium.googlesource.com/chromium/src/%2B/main/docs/accessibility/overview.md)
and equivalent native AT-SPI trees in the other listed families.

## Kitty

Only current-user sockets named `$XDG_RUNTIME_DIR/omarchy-kitty-<PID>` are
accepted. Socket ownership, type, live Kitty PID, and process start tick are
validated before `kitten @ … ls` enumerates OS windows, tabs, and Kitty windows
(panes). Numeric tab/window IDs are activated with `focus-tab` or
`focus-window`, then the exact matching Hyprland client is focused. Socket and
process identity—including socket device/inode and process birth—are part of
every ID and are revalidated to prevent PID/socket reuse. Command construction
follows Kitty's [remote-control protocol](https://sw.kovidgoyal.net/kitty/remote-control/).

## Ghostty 1.3.1

Native GTK tab titles come from strict AT-SPI tabs. Pane/surface coverage is a
capability-tested bridge to the command palette implementation shipped in
Ghostty 1.3.1; it is not presented as a public Ghostty IPC API.
[Ghostty's pinned 1.3.1 source](https://github.com/ghostty-org/ghostty/tree/v1.3.1/src)
is the compatibility boundary.

On each panel opening, Everything:

1. Verifies the running class and exact `ghostty +version` output.
2. Capability-probes `toggle_command_palette` with `ghostty +list-actions`
   and reads effective bindings with `ghostty +list-keybinds --plain`.
3. Requires the `win.toggle-command-palette` capability, opens the palette,
   requires the command `EditableText` and populated list to share the same
   live modal, and sets `Focus:` through `EditableText` (never injected typing).
4. Walks the complete virtualized result list with verified, exact-address
   navigation and always closes the dialog during cleanup.
5. Stores process birth, title, canonical cwd, duplicate occurrence, and
   filtered ordinal as the surface fingerprint.

Activation opens the palette again, rebuilds the entire ordered fingerprint,
and verifies each navigation step before Enter. Ghostty's own
`surface.present()` then selects the proper window, tab, and split. A changed
or ambiguous fingerprint fails closed.

Standalone native tabs use only the running configuration's effective
`goto_tab`, `last_tab`, or `next_tab` binding, with AT-SPI verification before
and after. Global, all-window, unconsumed, and sequence bindings are rejected.

For nested targets, a multi-surface Ghostty process is accepted only when
exact terminal title plus canonical cwd identifies one surface; a process with
one surface is intrinsically unambiguous. Otherwise Everything opens a fresh
attached client or Neovim remote UI instead of guessing.

## tmux

Discovery covers same-user sockets in `/tmp/tmux-<UID>`, tmux-named runtime
entries, and explicit `-S` sockets found in same-user process argv. Sessions,
windows, and panes use immutable `$`, `@`, and `%` native IDs. A target with one
uniquely matched local client uses `switch-client` and focuses that client's
terminal. Detached, remote-only, or ambiguous-host targets open a fresh local
terminal attached directly to the session and target. Existing remote clients
are never selected as hosts.

## Herdr

`herdr session list --json` supplies running local session sockets. Everything
accepts only absolute current-user Unix sockets, requests a
`session.snapshot`, and requires protocol 20 before emitting session,
workspace, tab, pane, and agent rows with current agent state.

Activation sends exact `workspace.focus`, `tab.focus`, or `pane.focus` socket
requests. One unambiguous attached local client is focused; detached or
ambiguous-host sessions open a fresh `herdr session attach`. Remote sessions
are not discovered.

## Neovim

Everything accepts current-user Unix sockets in the current runtime directory
or its one-level private tempdir, `${TMPDIR:-/tmp}/nvim.<username>`, or explicit
live `--listen` argv. Discovery is same-user, non-symlink, and entry bounded; a
fixed `--remote-expr` confirms the owning Nvim PID and reads listed buffers plus
changed, loaded, displayed, current, and last-used state.

Activation revalidates socket owner, process birth, buffer number, and
canonical name. The first existing window/tab showing the buffer is selected
when present, and its container is focused in existing-only mode so neither a
new terminal attach nor a fresh remote UI is opened for that case. Otherwise
`:hide buffer` switches safely without abandoning a modified buffer. The
containing tmux or exact inherited Herdr pane is routed first, with cwd used
only as a unique fallback. For a hidden buffer whose multiplexer or
multi-split Ghostty host cannot be proven unique, Everything opens
`nvim --server <socket> --remote-ui` in a fresh terminal.

## Other applications

Every other managed window remains searchable: this includes current Omarchy
applications such as Nautilus, Obsidian, LibreOffice, Kdenlive, OBS, Pinta,
Xournal++, Evince, LocalSend, Moonlight, mpv/imv, OMA apps, and optional
editors. Strict externally actionable native tabs may add rows, but an adapter
failure never removes the outer-window fallback.
