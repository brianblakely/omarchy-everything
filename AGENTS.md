# Agent guide

Everything is a native Omarchy Quattro plugin for finding and switching to
actionable local things. This file is an index, not the project specification.
Follow the linked document for the boundary you are changing.

## Documentation map

- [Architecture](docs/architecture.md) — ownership, dependency direction,
  data flow, identity, lifecycle, and cross-boundary invariants.
- [JSON-lines protocol](docs/protocol.md) — QML/helper messages, item contract,
  request correlation, activation tokens, and service leases.
- [Provider behavior](docs/providers.md) — discovery and activation guarantees
  for each supported application or container.
- [Security and runtime access](docs/security.md) — subprocesses, sockets,
  `/proc`, AT-SPI, synthetic input, trust checks, and persistence limits.
- [Testing](docs/testing.md) — automated coverage, fixtures, smoke tests, and
  the manual acceptance matrix.
- [README](README.md) — user-facing behavior, installation, controls, and
  limitations. Preserve its prose; make only changes required by the feature.

## Code map

| Responsibility | Primary files | Read with |
| --- | --- | --- |
| Plugin registration | `manifest.json` | Architecture |
| Per-monitor panel, focus, and list state | `Everything.qml` | Architecture, Testing |
| Pure ranking and reconciliation | `EverythingModel.js` | Architecture, Protocol |
| Shell-wide leases, helper process, and partial merges | `Service.qml` | Architecture, Protocol |
| JSON-lines process and cancellation | `helper/everything_helper.py`, `everything/server.py` | Protocol, Security |
| Scan orchestration and activation retry | `everything/discovery.py` | Architecture, Protocol |
| Thing identity and opaque tokens | `everything/model.py` | Architecture, Protocol |
| Native adapters and routing | `everything/providers/` | Providers, Security |
| AT-SPI, commands, and process metadata | `everything/atspi_runtime.py`, `everything/commands.py`, `everything/processes.py` | Security |
| Automated and live verification | `tests/` | Testing |

## Working rules

- Keep the dependency direction and ownership boundaries in
  [Architecture](docs/architecture.md). Do not move native discovery,
  activation details, or raw activation data into QML.
- Use “thing” consistently for an actionable result. Processes are routing
  metadata and never become results merely because they exist.
- Target the current Omarchy Quattro and packaged application interfaces. Do
  not add legacy compatibility paths or Codex plugin metadata.
- Preserve default shell panel placement and keyboard behavior. Extend shell
  primitives instead of replacing their lifecycle, anchoring, or navigation.
- Work in this repository only. Do not patch, install, or hot-reload a live
  plugin copy unless the user explicitly asks for that operation.
- Run `tests/all.sh` for implementation changes. Add focused tests at the
  boundary being changed.

## Documentation maintenance

Architecture documentation is part of the change, not follow-up work.

- When a change alters ownership, dependency direction, a public contract,
  lifecycle, trust boundary, provider guarantee, or test strategy, update the
  corresponding document under `docs/` in the same change.
- When introducing a new architectural boundary, create a focused
  `docs/<boundary>.md`, link it from this index and
  [Architecture](docs/architecture.md), and state its owner, inputs/outputs,
  invariants, failure behavior, and verification route.
- Keep this file as a semantic map. Put rationale, edge cases, schemas, command
  lists, and operational detail in the linked documents rather than copying
  them here.
