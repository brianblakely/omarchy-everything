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
focus, highlighted UUID, list scroll state, accessibility, and close-before-
activation ordering. It uses the shell's `KeyboardPanel`, icon anchoring, and
`PanelKeyCatcher`; shell navigation remains authoritative. Each opening clears
search, selects the first ranked thing, and resets the list to its scroll
origin. UUID and visual-offset preservation applies only to refreshes while
that opening remains active. Pointer-driven selection passes through the
shell's `PointerMoveGate`; opening, keyboard navigation, and list mutations
reset that gate so delegates appearing beneath a stationary pointer cannot
change the highlighted thing.

`Service.qml` is shell-wide. It owns helper leases, request correlation,
provider partials, activation-token lookup, transient hidden IDs, polling, and
helper restart/stop behavior. A panel acquires a stable instance lease while
open and releases it when closed.

`EverythingModel.js` stays pure and free of QML object references. Source
metadata may change without replacing the visible list. A UI update is needed
only when the ordered UUID sequence or a rendered trait changes; genuine list
changes preserve the highlighted UUID and its visual offset when possible.
It orders exact kind groups deterministically and ranks rows within each group.
QML owns the accessible section headings and restores visual offset from the
live selected delegate geometry, falling back to deterministic section geometry
when that delegate has not been instantiated. The pure model also derives each
row's kind icon and selects one vital metadata value; QML renders only that
icon, title, and value on a single line. Kind labels are excluded from metadata;
provider-specific kind-bearing fallbacks are reduced to their useful identity
or location before display. Badge normalization accepts both JavaScript arrays
and Qt typed lists, including their comma-joined bridge representation, before
the kind filter runs.

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
  are preserved.
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
