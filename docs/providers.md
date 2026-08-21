# Provider behavior

## Hyprland windows

Everything reads current `hyprctl -j clients` data and emits every mapped
managed client. Workspace, group, scratchpad, and hidden state only add
context; they never exclude a client. Activation rechecks PID and Linux process
birth before focusing the exact address through current `hl.dsp.focus`.
Layer surfaces are outside the clients API and are not results.
The mapped-only client set is the routing input for child providers; unmapped
clients retained briefly by Hyprland cannot host tabs, panes, or buffers. A
separate matching-only set retains those records for AT-SPI top-level
disambiguation. Top-level titles must match even when only one same-PID client
is present, a top matched to an unmapped record is rejected, and multiple tops
claiming one address all fail closed. This prevents a closed window's lingering
accessibility tree from being rebound to another live window in the same
process.

Window presentation also retains the client's ordered icon hint, class,
initial class, and initial title. QML resolves those Hyprland-reported values
against the shell's current desktop entries, including the host/path identity
used by Omarchy web apps. An exact identity in Omarchy's current default app
map uses its Nerd Font glyph. Other clients use the resolved desktop-entry or
direct-hint image, recolored to the same foreground as a glyph; an unresolved
client uses the generic window glyph. Entry-only identities are never inferred
from a raw class, and web apps do not inherit their host browser's glyph. These
hints are display-only and never participate in activation identity.

Foot and Alacritty have no internal Linux tab/split adapter in the supported
versions, so their only native things are their exact managed windows. tmux,
Herdr, and Neovim nested inside them are still expanded. This
matches [Alacritty's explicit non-goal of providing tabs or splits](https://github.com/alacritty/alacritty#faq).

## Browser and application tabs

The AT-SPI provider looks for actionable `PAGE_TAB_LIST`/`PAGE_TAB` objects
outside every `DOCUMENT_*` subtree. It rejects dock, tool, sidebar, inspector,
and developer-tool strips. A tab must be either a direct child of its tab list
or the sole child of one transparent `GROUPING` wrapper, matching current
GTK 4/libadwaita tab bars without recursively accepting arbitrary controls.
Within the globally bounded AT-SPI walk, absolute application-tree depth is not
used as a native/tab distinction; document ancestry is. The provider then
chooses a browser's primary strip by real page-tab count with depth as a
tie-breaker. This supports horizontal, vertical, and custom native tab-strip
layouts without accepting page-authored ARIA tabs.

When a managed browser is first seen, discovery gives its native controls a
bounded settle pass: Chromium can publish the top-level frame before its tab
strip has arrived on AT-SPI. Only exact browser addresses whose tab strips
were actually observed become settled. An uncovered address remains eligible
for the same bounded wait on a later poll, and a previously covered address
becomes unsettled if a later first pass loses its strip. A cold or temporarily
incomplete accessibility tree therefore cannot permanently suppress its tabs.
Managed-window rows still publish immediately, and later browser rows merge
into the same open panel.
Current Pinta and Nautilus windows also receive a bounded pass when first seen.
Their toolkit top level, native tab list, and exact GTK action route can become
available at different times, so the initial panel generation is not allowed
to treat the first empty accessibility frame as final. Unlike a browser, an
application may legitimately expose no tab yet. Its window identity is
therefore marked attempted after the first bounded pass; subsequent ordinary
polls still discover newly added tabs without imposing the settle delay on
every generation.
The first AT-SPI generation, and the first generation after the exact
browser/Pinta/Nautilus client set changes, traverses only those priority
clients. Once that set has published, a later poll also traverses generic
GTK/Qt applications and merges their actionable tabs. Generic application
tabs can consequently appear one poll later, while a slow unrelated toolkit
tree cannot delay the first actionable rows for a newly opened priority
window.
The settle waits are cancellable asyncio delays. The tree reads before and
after each wait run on the dedicated AT-SPI owner thread alongside every other
libatspi call. The protocol loop remains independent, and no additional
accessibility worker or listener thread shares the native connection.

Recognized current Omarchy browser classes cover Chromium, Chrome, Brave
variants, Edge, Firefox, Zen, Vivaldi, Helium, and LibreWolf. Normal private
windows use the same strict per-window matching. App-mode/PWA windows are
identified from the current browser-derived class or Omarchy launch-time web
identity and emit no tab row—not even a generic application-tab row—because
their single browser tab is not distinct from the managed window. Generic
GTK/Qt applications must expose both the bounded native structure above and a
preferred AT-SPI tab action. A component interface alone is not an activation
guarantee and does not make a generic application tab a thing.
Every browser/application tab must also resolve to an exact mapped window from
the current Hyprland scan. If that parent closes while its accessibility tree
lingers, the next provider refresh publishes no child tab rows.
DOM/editor tabs with no reliable external adapter remain represented by their
outer window. An application-tab row uses the final component of its managed
application class as its provider and displayed metadata. This preserves the
owning app's name when a toolkit exposes only a runtime name such as Pinta's
`dotnet` AT-SPI application.

AT-SPI exposes titles. URLs, favicons, and browser history are not part of the
0.0.1 contract. The browser-side assumptions are intentionally limited to the
[Chromium accessibility architecture](https://chromium.googlesource.com/chromium/src/%2B/main/docs/accessibility/overview.md)
and equivalent native AT-SPI trees in the other listed families.
Tab identity combines a toolkit accessibility ID with its unique remote object
path, falling back to its validated structural path when necessary; repeated
type-like GTK IDs such as `AdwTab` therefore cannot collide. Activation invokes
the native tab's exposed preferred action (including Chromium's `dodefault`)
before focusing its exact managed window.

Current packaged Pinta and Nautilus use GTK 4/libadwaita tabs that expose only
a non-operative AT-SPI component-focus interface. They are admitted through
two exact `org.gtk.Actions` adapters instead:

- Pinta must have exactly one session-bus connection owned by its managed PID
  that exports the integer `active_document` action at
  `/com/github/PintaProject/Pinta`. Its live state must identify the same tab
  index and exact title exposed by the matched AT-SPI top level. Activation
  invokes `active_document` with that validated direct index and polls until
  the exported state confirms it.
- Nautilus must own `org.gnome.Nautilus` and expose exactly one enabled integer
  `go-to-tab` action under `/org/gnome/Nautilus/window/<number>`. Nautilus does
  not update that action's exported state with tab selection, so more than one
  exported window is ambiguous and application-tab rows fail closed. The
  single-window route activates the exact integer index.

Both adapters revalidate process ownership, action name/signature, tab count,
index, and the target's native identity immediately around activation. Other
component-only tabs remain omitted while their exact outer-window row stays
available.

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

The line metadata stays structural and compact: sessions show Attached or
Detached, windows show their session name, and panes show their window name.
Native IDs, socket paths, cwd chains, and deeper ancestry remain available to
the provider for identity and routing but are not rendered in that value.

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
Named buffer rows use the filename as their title and its canonical containing
directory as their display context. An unnamed buffer uses the editor's
canonical working directory. Status badges remain available to accessibility
and activation continues to use the separately revalidated canonical name.
The presentation model reduces that context to its final path component for
the row's metadata; routing retains the complete canonical path.

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
