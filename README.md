# Everything
List, search, and jump directly to every app, tab, buffer, agent... everything. An Omarchy plugin.

![Everything screenshot](preview.png)
![Another Everything screenshot](preview2.png)
![Screenshot demonstrating search](preview3.png)
![Settings panel](preview4.png)

## Install

```bash
omarchy plugin add https://github.com/brianblakely/omarchy-everything.git --enable --yes
```

## Open

Click the arrow in the bar, or use a binding:

```lua
hl.unbind("SUPER + SLASH")
o.bind("SUPER + SLASH", "Everything", "omarchy-shell shell toggle b.everything")
```

# Configure

Right-click the bar icon to choose which groups appear in Everything.

## AI agent commands

Off by default. Right-click the bar icon and choose "AI agent folders…" to
turn it on and add at least one folder the agent may work in.

Once enabled, typing `!` in the search field switches from search to an
agent command:

| Type | Does |
|---|---|
| `!` | Browse recent conversations |
| `!ask <question>` | Answer only, no file or tool access |
| `!plan <task>` | Produce a plan, no changes made |
| `!<task>` | Run it, with edits and tool use confined to your configured folders |
| `!@<folder> <task>` | Attach one of your configured folders by name as context |

It drives your configured default agent (`omarchy default agent`) directly —
currently Claude Code, Codex, or Gemini CLI. Run/plan modes never bypass that
agent's own permission prompts; they're scoped to the folders you add instead.
Conversations are kept locally under
`~/.local/share/omarchy-everything/agent/` so they can be reopened later from
`!`; delete that folder to clear your history.

## Update

```bash
omarchy plugin update b.everything
```

## Uninstall

```bash
omarchy plugin remove b.everything
```

## Keyboard Controls

| Focus | Keys | Action |
|---|---|---|
| Navigation | `K`, `Up` | Scroll up |
| Navigation | `J`, `Down` | Scroll down |
| Navigation | `H`, `Left` | Collapse the current group |
| Navigation | `L`, `Right` | Expand the current group |
| Navigation | `Home`, `End`, `g`, `G` | Scroll to top or bottom, respectively |
| Navigation | `Page Up`, `Page Down`, `Ctrl+U`, `Ctrl+D` | Move one page |
| Navigation | `Ctrl+P`, `Ctrl+N` | Move to the previous or next thing |
| Navigation | `Enter`, `Space` | Expand a collapsed group, or close Everything and activate the highlighted thing |
| Navigation | `/` | Focus the search field |
| Navigation | `X`, `Backspace`, `Delete` | Hide the highlighted thing from the list until restart |
| Navigation | `Tab`, `Shift+Tab` | Switch between search and the list |
| Search | `Down`, `Tab` | Switch to list |
| Search | `!` | Open the agent command panel (see [AI agent commands](#ai-agent-commands)) |
| Settings panel | `Enter`, `Space` | Show or hide the selected group in results |
| Other | `Escape` | Clear a search / Close Everything |
