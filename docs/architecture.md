# Architecture

Everything has a small QML presentation layer and a leased Python discovery
helper. The hard boundary between them is the versioned JSON-lines protocol.
Native integrations remain behind provider adapters.

## System shape

| Layer | Owner | Inputs | Outputs |
| --- | --- | --- | --- |
| Plugin registration | `manifest.json` | Omarchy plugin schema | Service and bar-widget entry points |
| Per-monitor presentation | `Everything.qml` | Shell service items and user input | Search, selection, hiding, activation requests |
| Pure presentation model | `EverythingModel.js` | Item arrays, query, hidden IDs | Ranked arrays and reconciliation decisions |
| Shell-wide state | `Service.qml` | Panel leases and helper messages | Merged items, transient hidden IDs, helper requests |
| Process boundary | `helper/everything_helper.py`, `everything/server.py` | Versioned JSON lines | Correlated snapshots, activation results, nonfatal errors |
| Discovery core | `everything/discovery.py`, `everything/model.py` | Provider results | Deduplicated things and opaque activation tokens |
| Native adapters | `everything/providers/` | Current local APIs and validated runtime metadata | Actionable things, routing metadata, exact activation |
| Shared local access | `everything/commands.py`, `everything/processes.py`, `everything/atspi_runtime.py` | Bounded local state | Safe argv execution, process routes, temporary AT-SPI state |

The dependency direction is:

```text
Everything.qml -> Service.qml -> JSON lines -> server/discovery -> providers
       |               |                              |
       v               v                              v
EverythingModel.js  public items               local native APIs
```

Providers do not depend on QML. QML does not receive provider activation
structures or call native tools directly. See [the protocol](protocol.md) for
the wire schema and [provider behavior](providers.md) for adapter guarantees.

## Frontend ownership

`Everything.qml` is one bar instance per monitor. It owns the panel, search
focus, highlighted UUID, collapsed-kind map, list scroll state, accessibility,
and close-before-activation ordering. It uses the shell's `KeyboardPanel`, icon
anchoring, and `PanelKeyCatcher`; shell navigation remains authoritative after
search hands focus to the list. Vertical directions move between visible rows
or collapsed headings, while horizontal directions collapse or expand the
current group. A collapsed group retains its heading as the visible accessible
focus target and never exposes a hidden row to activation or removal. Each
opening clears and focuses search, expands every group, selects the first ranked
thing, and resets the list to its scroll origin. UUID and visual-offset
preservation applies only to refreshes while that opening remains active.
Any keyboard path that reaches the first ranked thing also resets the list to
its scroll origin; pointer selection and refresh reconciliation do not.
Pointer-driven selection passes through the
shell's `PointerMoveGate`; opening, keyboard navigation, and list mutations
reset that gate so delegates appearing beneath a stationary pointer cannot
change the highlighted thing.
The bar chevron remains inside the shell's standard `BarIconButton` slot. Its
painted bounds are optically centered without shifting the widget geometry,
pointer target, or `KeyboardPanel` anchor.
The presentation renders no status row; scan progress, empty searches, counts,
and provider warnings never become panel messages. Activation failure can still
use the shell's external notification path after the panel closes.

`Service.qml` is shell-wide. It owns helper leases, request correlation,
provider partials, activation-token lookup, transient hidden IDs, polling, and
helper restart/stop behavior. A panel acquires a stable instance lease while
open and releases it when closed.

`EverythingModel.js` stays pure and free of QML object references. Source
metadata may change without replacing the visible list. A UI update is needed
only when the ordered UUID sequence or a rendered trait changes; genuine list
changes preserve the highlighted UUID and its visual offset when possible.
It orders exact kind groups deterministically, with all Herdr groups before
tmux, Herdr agents first within that family, and Herdr sessions last within it;
then it sorts rows naturally by their displayed metadata within each group.
Pure group-boundary and section-geometry helpers let QML skip hidden rows and
restore scroll position without changing or duplicating provider results.
Windows use one preceding bucket for regular workspace rows and one trailing
bucket for Scratchpad. Search
relevance, current state, and recency are tie-breakers only. Parent-derived
tmux and Herdr metadata is resolved from the complete source set before query
and hidden-ID filtering.
The normalized query must match one case-insensitive contiguous substring of
either the title or exact displayed group label. It cannot be split across
fields; context, provider, badges, and provider search terms never enter
matching.
QML owns the accessible section headings and restores visual offset from the
live selected delegate geometry, falling back to deterministic section geometry
when that delegate has not been instantiated. The pure model also derives each
row's fallback kind glyph, matches Hyprland window icon hints to the shell's
current desktop entries, selects a known glyph from Omarchy's current default
app map, and chooses one vital metadata value. QML renders that mapped glyph
first; otherwise it recolors the resolved application image with the same
highlight-aware foreground used by glyphs, then falls back to the generic
window glyph. Each row contains only that icon, title, and value on a single
line. Herdr agent rows reuse the shell's agent-usage robot glyph. Kind labels
are excluded from metadata;
provider-specific kind-bearing fallbacks are reduced to their useful identity
or location before display. Badge normalization accepts both JavaScript arrays
and Qt typed lists, including their comma-joined bridge representation, before
the kind filter runs. The model indexes the complete public parent graph once
per source update; both ranking and QML use that same index for breadcrumbs and
tmux window/pane and Herdr workspace/tab/pane metadata. These child rows show
only their immediate parent's title, while agent and session metadata retain
their status semantics. Neovim buffer metadata bypasses status priority and
shows only the final component of the canonical containing directory supplied
by its provider. The complete path remains provider context for native routing.

## Helper and provider ownership

`everything/server.py` owns stdin/stdout framing, cancellation, signal
handling, AT-SPI guard lifetime, and concurrent activation tasks.
`everything/discovery.py` owns provider scheduling, partial/full publication,
failure isolation, one stale refresh/retry, and the shared metadata used for
container routing.

Hyprland results are published first. Independent adapters then scan
concurrently. Neovim receives a cheap second scan after container metadata is
available so it can route through an exact host without guessing. Ghostty's
modal bridge runs only during a panel-opening scan or activation revalidation,
never on the normal poll. The panel exposes no manual scan control.

Each adapter returns `ProviderResult`: public `Thing` values, nonfatal
warnings, and private routing metadata. Adapter failure removes only that
adapter's internal rows; an outer managed-window result remains available.

## Identity and activation

Three identities serve different boundaries:

| Value | Purpose | Lifetime |
| --- | --- | --- |
| `Thing.id` | Stable native provider identity | Native target lifetime |
| `uiUuid` | Deterministic UI reconciliation identity | Same stable traits |
| `activationToken` | Authenticated reference to private activation data | Helper process and provider generation |

Raw activation dictionaries stay in Python. The registry authenticates tokens,
rejects stale generations, revalidates the native target, and permits exactly
one same-ID refresh/retry. Titles and other presentation text are never
activation identities.

## Lifecycle and state

- The helper exists only while at least one panel lease or activation is
  active. Closing the last panel requests shutdown after pending activation.
- Hyprland rows can arrive before slower adapters; `Service.qml` merges
  provider partials rather than replacing unrelated providers.
- Hidden IDs, warnings, provider snapshots, tokens, and Ghostty cache are
  memory-only and reset with the plugin or shell process.
- The panel closes before activation is dispatched so the shell releases its
  keyboard grab before another local surface receives focus.

Detailed message and lease behavior belongs in [the protocol](protocol.md).
Runtime authority and cleanup belong in [security](security.md).

## Invariants

- Only actionable things are results: managed windows, native tabs/panes,
  supported containers and agents, and Neovim buffers. Processes remain
  private routing metadata.
- This is an Omarchy Quattro plugin, not a Codex plugin. Current packaged
  interfaces are the only compatibility target.
- Default shell placement, anchoring, panel lifecycle, and keyboard navigation
  are preserved; optical icon corrections cannot move the shell slot, pointer
  target, or panel anchor.
- Provider commands use argv arrays with bounded timeouts and no shell
  interpolation. Untrusted runtime data is revalidated at activation.
- Provider failures are isolated and nonfatal. Ambiguous native routing fails
  closed or uses the documented fresh-client behavior instead of guessing.
- No network request, privileged operation, install hook, persistent worker,
  or on-disk hidden-state store is introduced.

See [security](security.md) for the exhaustive authority list and
[testing](testing.md) for the verification matrix.

## Evolving boundaries

When a change alters a layer's owner, inputs/outputs, dependency direction,
lifetime, trust assumptions, or failure semantics, update this document and
the specialized document in the same change. A new boundary gets a focused
page under `docs/`, linked here and from `../AGENTS.md`; document its owner,
contract, invariants, failure behavior, and tests.
