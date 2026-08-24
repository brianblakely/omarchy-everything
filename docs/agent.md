# AI agent commands

This is a second, deliberately isolated boundary layered on top of the
discovery subsystem described in [architecture](architecture.md) and
[protocol](protocol.md). It exists so a small number of new, real invariants
— network access, a real on-disk store, one new allow-listed subprocess
family per supported agent CLI — are introduced honestly, in one place,
rather than silently expanding the discovery helper's documented guarantees.
It is off by default and has no effect on discovery, ranking, or any
existing keyboard behavior until the user opts in.

## What it is for

Typing `!` in the search field switches it from ranking things to composing
or browsing a command for the user's locally configured AI coding agent
(Claude Code, Codex, or Gemini CLI — see [Supported agents](#supported-agents)
below):

- `!` alone opens a browser of recent conversations, recent-first.
- `!ask <text>` asks a question. The agent gets no tool access at all.
- `!plan <text>` asks for a plan. The agent may read files but never edits or
  executes anything.
- `!<text>` (no keyword) runs the agent with file read/edit access, but only
  inside folders the user has explicitly added under "AI agent folders…"
  (right-click the bar icon → that link at the top of the group-visibility
  panel). `!@<folder-name> <text>` attaches one of those configured folders
  by name as extra context ahead of the prompt; unrecognized names are
  ignored rather than guessed at.
- Escape steps back to the history browser rather than fully closing while a
  conversation is open, matching the panel's existing "first Escape softens,
  second Escape closes" feel.
- Agent and system turns render as markdown (bold, lists, code spans,
  headings, links) via Qt's built-in `Text.MarkdownText`, not a custom
  renderer — no syntax highlighting inside code blocks, but headings, lists,
  emphasis, and inline code all render properly instead of showing literal
  `**`/`` ` ``. The user's own typed prompt is deliberately rendered as plain
  text instead (`Text.PlainText`) so a stray `*` or `_` they typed is never
  reinterpreted as markdown.

Nothing here bypasses permissions. `!<text>` deliberately does not use
Claude Code's `--dangerously-skip-permissions`, Codex's
`--dangerously-bypass-approvals-and-sandbox`, or Gemini's `--yolo` — the
whole point of the folder-access setting is that it means something.
`tests/test_agent_adapters.py`'s `NeverBypassTests` asserts this for every
registered adapter automatically, so a new adapter is covered without
anyone remembering to add a case for it.

## Supported agents

`omarchy-agent` (the existing `omarchy agent`/`omarchy-default-agent`
tooling) is not used as a building block here: it always `exec`s into an
interactive, fully permission-bypassed terminal session with no way to
capture structured output, which is incompatible with everything above.
Instead, `everything/agent/adapters/` drives each CLI's own real
non-interactive flags directly.

| Agent | ask | plan | run | Why |
|---|---|---|---|---|
| `claude` (Claude Code) | ✅ | ✅ | ✅ | `-p --output-format json`, `--permission-mode plan` for read-only plans, `--tools ""` for ask, `--permission-mode acceptEdits --tools Read,Write,Edit,Glob,Grep` for run, `--add-dir` for folder scope, `--resume` for continuation. |
| `codex` | ❌ | ✅ | ✅ | `codex exec --sandbox read-only` (plan) / `--sandbox workspace-write` (run), `--skip-git-repo-check` so a non-git allowed folder still works, `--json` for a real per-line event stream. No confirmed flag gives a tool-free "just answer" mode — see below. |
| `gemini` (Gemini CLI) | ❌ | ✅ | ✅ | `-p -o json --approval-mode plan` (plan, read-only) / `--approval-mode auto_edit` (run, edits only — not `yolo`), `--include-directories`, `--skip-trust` (see below). |
| `opencode` | ❌ | ❌ | ❌ | Registered (shows up in `capabilities.agents` when installed) but not wired up: `opencode run --help` exposes no permission/sandbox flag except `--auto` ("auto-approve permissions that are not explicitly denied (dangerous!)"), which the no-bypass rule above rules out, and the default non-interactive permission behavior without it is unverified. |
| `crush` | ❌ | ❌ | ❌ | Same reasoning: `crush run --help` exposes no permission/sandbox/approval flag at all, so whether it prompts interactively (would hang here) or applies some default policy is unverified. |
| `pi`, `omp`, `grok`, `copilot` | ❌ | ❌ | ❌ | No adapter exists yet. Requesting one of these agents fails with a clear `agentRunFailed` message rather than guessing. |

An adapter's `supported_modes` is the single source of truth the server
checks before running anything; a mode not in that set fails clearly
(`agentRunFailed`) instead of being silently approximated. Extending an
adapter's coverage, or adding a new one, means adding it to this table too.

Two flag-level gotchas worth keeping in mind if you touch an adapter:

- Claude Code's `--tools`/`--add-dir` are documented as taking
  `<tools...>`/`<directories...>` (variadic) and will swallow a following
  bare positional prompt as more of their own values — confirmed live:
  `claude -p --tools "" "prompt"` fails with "prompt must be provided"
  because `"prompt"` was consumed as a tool name. Every adapter's `argv`
  therefore puts the prompt first, before any flags.
- Gemini silently overrides an explicit `--approval-mode` back to `"default"`
  for a folder it doesn't consider trusted yet — confirmed live, with the
  warning `Approval mode overridden to "default" because the current folder
  is not trusted`. `--skip-trust` is required on every gemini invocation to
  prevent that from quietly defeating the requested mode.

Codex and Gemini's JSON output shapes above were implemented against their
documented flags and (for Codex) a confirmed-live JSONL event envelope; no
API credentials were available in the environment this was built in to
observe a real authenticated success payload for either, so `finalize()` in
both adapters degrades gracefully — falling back to a labeled raw JSON dump
rather than silently dropping content — if a field name doesn't match what
was guessed. Hardening this against real responses is a natural follow-up.

## Architecture: a second, isolated process

`Service.qml` gets a second, fully independent `Quickshell.Io.Process`
(`agentHelper`) with its own lease count (`agentLeases`/`agentAcquire`/
`agentRelease`), its own request/response functions (all `agent`-prefixed,
mirroring but never sharing state with `sendRequest`/`handleMessage`),
launched as `["python3", agentHelperPath, "--json-lines"]` against a new
`helper/everything_agent_helper.py` → `everything/agent/server.py`
(`AgentJsonLineServer`).

This is deliberately not an extension of the discovery protocol
(`everything/server.py`). That helper's docs, timeout model (sub-second,
bounded), lease/crash-restart tuning, and tests are written around short,
local, read-only, unauthenticated scans. An agent run is long-running
(seconds to minutes), streamed, cancellable, and networked — none of which
apply to discovery. Keeping it a second process makes "explicitly isolated"
structural: `helper/everything_helper.py`, `everything/server.py`, and their
tests stay byte-for-byte unchanged, so this feature's new risk surface
(network, secrets, long-running subprocesses) is visibly confined to new
files. `manifest.json` still declares only one `service` entry point — the
second process is an implementation detail inside it, not a second plugin.

`Everything.qml` acquires the agent lease (`agentAcquire(instanceKey)`)
whenever `popupMode` is `agent` (composing/streaming) or `agentHistory`
(browsing past conversations), and releases it otherwise — mirroring exactly
how a results-mode lease is acquired/released for the discovery helper. The
agent helper therefore only runs while a panel is actually in one of those
two modes, and only after the user has typed `!`.

## Protocol

Independently versioned (`AGENT_PROTOCOL_VERSION = 1`, defined in
`everything/agent/__init__.py`) from the discovery protocol's `version: 1` —
they are two unrelated wire contracts that happen to both start at 1. Same
conventions as [protocol.md](protocol.md): every request has a caller-unique
`id`; every response echoes it as `requestId`; unknown/malformed requests are
nonfatal.

`ready` reports which adapters exist and what each one is actually good for,
so the UI can know before ever sending a request:

```json
{"version":1,"type":"ready","capabilities":{"agents":{
  "claude":{"available":true,"modes":["ask","plan","run"]},
  "codex":{"available":true,"modes":["plan","run"]},
  "opencode":{"available":false,"modes":[],"unsupportedReason":"..."}
}}}
```

Requests:

- `agentRun {agent?, mode, prompt, allowedDirs, resumeSessionId?, conversationId?}`
  — `agent` omitted defers to `omarchy-default-agent`. `plan` and `run` are
  rejected with `agentRunFailed` if `allowedDirs` is empty (there is nothing
  to plan against, and running would otherwise silently fall back to
  whatever directory the helper process happens to be started in, which
  would defeat the entire point of the folder-access setting). `ask` needs no
  directories.
- `agentCancel {requestId}` — kills the subprocess if one is running.
- `agentConversationList` / `agentConversationGet {conversationId}` /
  `agentConversationDelete {conversationId}` — the transcript cache described
  below.

Responses: streamed `agentTurn {requestId, conversationId, turn, final:false}`
messages, terminated by exactly one `agentTurn {..., final:true, ok, message?}`.
A distinct `agentRunFailed {requestId, conversationId, message}` is used for
run-specific failures that never got as far as starting a process (unknown
mode, empty prompt, missing folders, unknown/unsupported agent) — kept
separate from the protocol-level, nonfatal `error` message
([protocol.md](protocol.md)'s shape, reused verbatim) so "this one request
failed" and "the helper hiccupped on malformed input" stay distinguishable.

A cancellation racing in before a run's task ever gets its first turn on the
event loop can throw `CancelledError` into the coroutine before any of its
own code — including a `try/except` inside it — has executed, so the single
place that reliably reports a terminal message for a cancelled run is the
task's own `add_done_callback` in `AgentJsonLineServer._on_run_task_done`,
not a handler inside `_handle_run` itself.
`tests/test_agent_protocol.py::test_cancel_stops_a_running_request` caught
exactly this as a real bug (the client hanging forever with zero output)
during development; keep the done-callback as the single source of truth for
cancellation reporting if this changes.

## Settings

Two small preferences reuse the existing `root.setting()`/`updateEntryInline`
mechanism — the same shell-owned `shell.json` entry `disabledKinds` already
uses (`Everything.qml`'s `persistDisabledKinds`) — rather than inventing a
second persistence path:

- `agentEnabled` (boolean, default `false`) — the opt-in gate. While false,
  `handleSearchTextChanged()` never calls into `Model.parseAgentCommand`, so
  typing `!` behaves exactly like it always has (a literal character in a
  normal search).
- `agentAllowedDirs` (string array, absolute paths only, deduplicated,
  trailing slashes stripped) — reachable from the bar icon's right-click
  panel via a new "AI agent folders…" link, itself only visible once
  `agentEnabled` is true.

The transcript cache (below) is not a setting — it is bulk content owned
solely by the Python agent helper, never round-tripped through `shell.json`.

## Transcript cache

**`$XDG_DATA_HOME/omarchy-everything/agent/`** (default
`~/.local/share/omarchy-everything/agent/`) — a flat `omarchy-<tool>`-style
name, matching the real sibling convention already on a stock Omarchy
install (`~/.local/share/omarchy-podcasts`, `~/.local/share/omarchy-ytmusic`
both exist; a shared `~/.local/share/omarchy/` namespace does not).
`XDG_DATA_HOME`, not `XDG_CACHE_HOME`, because a conversation is irreplaceable
user content, not a disposable/regenerable cache. Directory `0700`, every
file `0600`.

- `index.json` — one entry per conversation (`id`, `agent`, `mode`, `title`,
  `createdAt`, `updatedAt`, `turnCount`, `allowedDirs`, `providerSessionId`),
  written atomically (temp file + `os.replace`) so `agentConversationList`
  never has to read every transcript file just to render the history browser.
- `conversations/<id>.jsonl` — one JSON object per turn, append-only. Chosen
  specifically because turns arrive incrementally during a streamed run: an
  append is O(1) and crash-safe (a truncated last line is simply discarded on
  the next read), unlike a single whole-file JSON document a crash mid-write
  could corrupt.

Stored per turn: `role`, `text` (truncated at 200 KB with a trailing marker,
so one pathological response can't blow out disk), `at`. **Never stored**:
API keys or other environment values, raw file contents an agent read or
wrote, or activation-token-style secrets. `providerSessionId` (each CLI's own
local resumable session id, e.g. Claude Code's `session_id`) is stored and is
the one credential-adjacent field worth naming explicitly — it is a local
session pointer, not a bearer credential, and only `claude` currently
supports resuming it (`ClaudeAdapter.supports_resume = True`; Codex and
Gemini's session-continuation flags were not confirmed safe to build against
in the time available, so `resumeSessionId` is accepted but ignored for
them — see `runner.run_agent`, which fails clearly rather than silently
starting a fresh, context-less session when resume is requested for an
adapter that doesn't support it).

Retention is count-based: `agentRetentionCount` (not yet exposed as a UI
setting; `storage.DEFAULT_RETENTION_COUNT = 200`), oldest conversation
evicted first. Age-based retention is a reasonable follow-up, not built now.

## Known scope limits

Written down here rather than silently left implicit, since they're
deliberate v1 boundaries, not oversights:

- Only one `agentConversationGet` result is tracked at a time
  (`Service.qml`'s `agentConversationTurns`, keyed by conversation id, not by
  request id). Two monitors both browsing history and opening different
  conversations at the same instant could see the other's fetch briefly.
  Acceptable for what is inherently a single-user desktop feature; revisit if
  that stops being true.
- `!` followed by more text always starts composing a new command; it does
  not live-filter the history browser the way typing filters every other
  list in this panel (`Model.filterConversations` exists and is unit-tested,
  but `agentHistoryEntries()` currently always calls it with an empty query).
  Wiring live filtering back into `!<query>` while still leaving `!<query>`
  free to mean "start a command with this text" needs a real design decision
  about which one wins, not a default.
- `@` attachment resolution (`Model.resolveAttachment`) only matches against
  the user's configured allowed folders by name — not, e.g., an arbitrary
  running window's cwd. Consistent with `!<text>`'s own folder-scoping (you
  can only attach what you've already trusted), but narrower than "any thing
  Everything already knows about."
- No per-token streaming: adapters call the CLI's buffered/single-JSON output
  mode rather than each CLI's separate `stream-json` format, so a run's
  answer typically appears as one turn once the process finishes rather than
  growing token-by-token. `CommandRunner.run_streaming()` supports true
  incremental line delivery (`Codex`'s adapter already uses it, since
  `--json` is genuinely line-delimited); extending Claude/Gemini to their own
  `stream-json` formats is a reasonable follow-up, not required for this to
  work.

## Tests

- `tests/test_agent_adapters.py` — argv-shape assertions per adapter/mode,
  and the cross-adapter `NeverBypassTests` described above.
- `tests/test_agent_storage.py` — index/append/read/delete/retention/
  permission-bits/truncation round trip against a temp `XDG_DATA_HOME`.
- `tests/test_agent_protocol.py` — a real subprocess harness against
  `helper/everything_agent_helper.py --json-lines --test-mode`
  (`EVERYTHING_AGENT_TEST_MODE=1`), using an in-process fake adapter
  (`AgentJsonLineServer._fake_run`) so it needs no real agent CLI and no
  network access, mirroring `tests/test_protocol.py`'s style for the
  discovery helper.
- `tests/test_commands.py`'s `StreamingTests` — `CommandRunner.run_streaming`
  (line ordering, idle/overall timeout kill, cancellation, cwd, argv-array
  discipline reused from `safe_argv`).
- `tests/model.test.js` — `parseAgentCommand`, `resolveAttachment`,
  `normalizeAllowedDirs`, `filterConversations`, plus source-pattern
  assertions that the opt-in gate is real (agent detection is provably
  skipped while `agentEnabled` is false) and that the agent helper is a
  genuinely separate `Process`.
- Not currently covered by a scripted `tests/qml.test.sh` interaction (typing
  `!`, verifying `popupMode` transitions end to end through a live
  Quickshell instance, folder add/remove through the mock shell's
  `updateEntryInline`): the existing fixture's `updateEntryInline` mock is
  already fully generic (any settings key round-trips, not just
  `disabledKinds`), and the plain `qmllint` + boot smoke test already passes
  with every change in this document, but a dedicated scripted flow the way
  `tests/fixtures/qml-entrypoints/shell.qml` already does for
  lease/refresh/scroll behavior would still be a valuable follow-up.
