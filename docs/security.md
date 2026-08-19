# Security and runtime access

Everything is local-only. Runtime code performs no HTTP, DNS, telemetry,
update, or other network request. The plugin has no install hook, privileged
operation, `sudo`, browser extension, native-messaging host, persistent daemon,
or background worker after its last service lease closes. Installation may use
Omarchy's normal Git-based plugin manager; that fetch is not performed by the
plugin.

All subprocesses are created from argv arrays through
`asyncio.create_subprocess_exec`, Quickshell `Process.command`, or
`Quickshell.execDetached`. No command is passed through a shell. NUL and line
breaks are rejected in argv values, and foreground commands have bounded
timeouts. External provider failure is nonfatal.

## Commands

The helper may execute only these command families:

- `hyprctl -j clients` and `hyprctl -j activewindow` for managed-client state.
- `hyprctl dispatch <Lua expression>` for exact-address `hl.dsp.focus` and the
  targeted `hl.dsp.send_key_state` cases documented below.
- `kitten @ --to unix:<validated-socket> ls`, `focus-tab --match id:<number>`,
  and `focus-window --match id:<number>`.
- `ghostty +version`, `ghostty +list-actions`, and
  `ghostty +list-keybinds --plain` while a Ghostty client is actually managed.
- `tmux -S <validated-socket> list-sessions`, `list-windows -a`,
  `list-panes -a`, `list-clients`, and `switch-client`; or a new local
  `omarchy-launch-terminal tmux -S … attach-session …` client.
- `herdr session list --json`; Herdr focus itself uses its validated Unix
  socket. Detached/ambiguous targets may run
  `omarchy-launch-terminal herdr session attach <name>`.
- `nvim --server <validated-socket> --remote-expr <fixed expression>` to read
  or switch a buffer; ambiguous hosts may run
  `omarchy-launch-terminal nvim --server <socket> --remote-ui`.
- `$OMARCHY_PATH/bin/omarchy-notification-send --app-name Everything …` after
  a stale or failed user activation.
- `python3 <plugin>/helper/everything_helper.py --json-lines` and its private
  `--atspi-guard <parent-pid>` child.

Arguments derived from titles, paths, sockets, or native IDs remain individual
argv fields. The fixed Neovim expression receives only a validated integer
buffer number; names are rechecked, not interpolated into Vimscript.

## Local sockets

The following Unix sockets may be opened after ownership and socket-type
checks:

- Kitty: `$XDG_RUNTIME_DIR/omarchy-kitty-<PID>`; device/inode, ownership,
  socket type, PID, and process birth are revalidated before activation.
- tmux: entries below `/tmp/tmux-<UID>`, tmux-named entries directly below
  `$XDG_RUNTIME_DIR`, and absolute custom `-S` paths found in same-user argv.
- Herdr: absolute paths returned by local `herdr session list --json`.
- Neovim: `nvim*` sockets directly below `$XDG_RUNTIME_DIR` or one private
  tempdir beneath it, entries beneath `${TMPDIR:-/tmp}/nvim.<username>`, and
  absolute `--listen` paths from same-user Neovim argv. Traversal is limited to
  one directory level and 4096 entries per root; the fixed RPC query confirms
  the socket's current-user Nvim PID.

Herdr requests are newline-delimited JSON methods `session.snapshot`,
`workspace.focus`, `tab.focus`, and `pane.focus`. They require protocol 20 and
have bounded connect/read/write timeouts and response size.

## `/proc` reads

`/proc` is used only as same-user routing metadata. No process becomes a result
because it exists. The helper reads:

- `/proc/<pid>/stat` for parent PID and immutable process start tick;
- `/proc/<pid>/cmdline` for executable identity plus explicit tmux `-S` and
  Neovim `--listen` paths;
- `/proc/<pid>/cwd` for canonical routing context;
- up to 256 KiB of `/proc/<nvim-pid>/environ`, retaining only
  `HERDR_SOCKET_PATH` and `HERDR_PANE_ID`, to identify an inherited exact
  Herdr pane when several panes share a working directory;
- `/proc/net/unix` and `/proc/<herdr-server-pid>/fd` symlinks to associate a
  listed Herdr socket with its server process;
- directory ownership from `/proc/<pid>` to exclude other users.

Reads are bounded to numeric processes owned by the current UID. An oversized
environment read is discarded completely. Ordinary process names, command
lines, and environment values are never serialized into the public result
list.

## Temporary AT-SPI state

While a helper lease exists, a guard reads `org.a11y.Status.IsEnabled` and
`ScreenReaderEnabled` from `org.a11y.Bus`. If AT-SPI was disabled, the guard
temporarily writes only `IsEnabled=true`. It never writes
`ScreenReaderEnabled`. On normal shutdown, cancellation, SIGTERM/SIGINT, or
parent pipe EOF after a crash, the guard restores the original `IsEnabled`
value. If another actor changes screen-reader mode meanwhile, that choice is
left untouched.

AT-SPI reads application/window/tab names, roles, state, actions, and native
tab accessibility IDs. It invokes only a selected live native tab's activation
action and the capability-tested Ghostty palette action.

## Ghostty palette and synthetic keys

Ghostty's 1.3.1 command palette is a modal, capability-tested bridge. The
filter `Focus:` is written through AT-SPI `EditableText`; query text is never
typed into a PTY. The command input and populated list must be descendants of
the same live AT-SPI dialog/alert; application-wide lookalikes are rejected.

Palette navigation sends exact-address current Hyprland Lua dispatches of
`hl.dsp.send_key_state` with paired `down`/`up` states for:

- `HOME` to reset to the first filtered row;
- `DOWN` to walk or select a verified row;
- `RETURN` only after the complete target fingerprint is revalidated;
- `ESCAPE` only during cleanup while the verified palette remains open.

Before every navigation/activation pair, Everything proves that the palette
still exists and its EditableText value is exactly `Focus:`. Cleanup Escape is
allowed before the filter is installed only while the live modal search and
list are still proven present. A key is never allowed to continue if the modal
disappeared, so navigation cannot fall through to the PTY. Legacy
`sendshortcut` is not used. Successful Enter is also verified to have closed
the palette; otherwise cleanup Escape closes it and activation fails closed.

Standalone tab selection can send one effective Ghostty binding read from
`+list-keybinds --plain` for `goto_tab`, `last_tab`, or `next_tab`. Global,
all-window, unconsumed, unknown-modifier, and sequence bindings are rejected;
the exact target address and selected AT-SPI tab are verified around every
step.

The palette is always closed in cleanup. Its surface fingerprint contains
process birth, exact title, canonical cwd, duplicate occurrence, and filtered
ordinal, and is rebuilt before activation.

## Persistence

There is no runtime database or cache file. Provider snapshots, opaque-token
secrets, helper warnings, monitor leases, Ghostty scan cache, and hidden IDs
exist only in memory. Plugin or shell reload resets them. The sole persistent
Everything-owned preference is the normalized `disabledKinds` string array in
the widget's existing `shell.json` entry. QML writes it through the shell's
`updateEntryInline` API; it contains only supported public kind identifiers and
never discovered thing data, native identities, titles, paths, or tokens.
