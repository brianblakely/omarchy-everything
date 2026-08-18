# JSON-lines protocol

`Service.qml` starts `helper/everything_helper.py --json-lines` as an argv
array. UTF-8 JSON objects travel one per line over stdin/stdout. Protocol and
plugin versions are independent: every message has `version: 1`, while the
initial handshake reports plugin version `0.0.1`.

The handshake is the only uncorrelated response:

```json
{"version":1,"type":"ready","pluginVersion":"0.0.1","capabilities":{"partialSnapshots":true,"atspi":true,"ghosttyPalette":true}}
```

Every request has a caller-unique `id`. Every response caused by that request
copies it into `requestId`. Unknown requests and provider failures are
nonfatal; the helper continues accepting lines.

## Requests

Scan, optionally including the one-shot Ghostty palette probe:

```json
{"version":1,"id":"scan-7","type":"scan","options":{"ghostty":true}}
```

Activate a public item using its process-local opaque token:

```json
{"version":1,"id":"activate-8","type":"activate","itemId":"provider:native-id","token":"v1.opaque"}
```

Shut down cleanly and restore temporary runtime state:

```json
{"version":1,"id":"shutdown-9","type":"shutdown"}
```

A newer scan cancels an unfinished older scan. Shutdown cancels scans and
activations before the AT-SPI guard is released.

## Responses

Providers stream partial snapshots as they finish. Hyprland is deliberately
published first:

```json
{"version":1,"type":"snapshot","requestId":"scan-7","provider":"hyprland","full":false,"items":[],"warnings":[]}
```

The final snapshot contains the merged view and a provider map:

```json
{"version":1,"type":"snapshot","requestId":"scan-7","full":true,"items":[],"providers":{},"warnings":[]}
```

Activation always completes with an explicit result. `stale: true` means the
native identity closed, was reused, or no longer matches its scan fingerprint:

```json
{"version":1,"type":"activation","requestId":"activate-8","itemId":"provider:native-id","ok":false,"stale":true,"message":"That viewport closed before it could be focused"}
```

Malformed input and isolated provider failures use:

```json
{"version":1,"type":"error","requestId":"scan-7","provider":"kitty","message":"Kitty: …","nonfatal":true}
```

A failed provider also publishes an empty partial for its own rows so stale
internal targets disappear; its outer Hyprland window is owned by a different
provider and remains available.

## Item contract

Every public item contains:

| Field | Meaning |
|---|---|
| `id` | Stable provider/native identity, including process birth or socket identity where reuse is possible |
| `kind` | One supported actionable viewport kind |
| `provider` | Human-readable provider badge |
| `title` | Primary search and display title |
| `context` | Cwd, application, workspace, or container context |
| `searchTerms` | Additional non-rendered matching terms |
| `parentId` | Parent viewport used to build breadcrumbs |
| `badges` | Status/type annotations |
| `active` | Whether this is the provider's current viewport |
| `recency` | Provider-local ranking hint |
| `activationToken` | Authenticated, process-local opaque activation reference |

Supported kinds are `window`, `browser-tab`, `app-tab`, `terminal-tab`,
`terminal-pane`, `tmux-session`, `tmux-window`, `tmux-pane`, `herdr-session`,
`herdr-workspace`, `herdr-tab`, `herdr-pane`, `herdr-agent`, and
`neovim-buffer`.

Activation bodies never enter QML as a separate field. They are authenticated
inside the token with a helper-process secret. Provider generations make old
tokens stale; activation performs one exact-ID refresh and retry before
returning an error.

## Service lease

Each bar instance owns a unique in-memory lease. The first open panel starts
the helper; the last close requests shutdown unless an activation is pending.
The panel closes before `Qt.callLater` sends activation, releasing the
layer-shell keyboard grab before another surface receives focus. A helper
restart clears queued tokens because process-local secrets intentionally do
not survive restart.
