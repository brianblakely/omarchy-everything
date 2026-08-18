const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")

const root = path.resolve(__dirname, "..")
const source = fs.readFileSync(path.join(root, "EverythingModel.js"), "utf8")
  .replace(/^\.pragma library\s*/m, "")
const sandbox = {}
vm.createContext(sandbox)
vm.runInContext(source, sandbox, { filename: "EverythingModel.js" })

const item = (id, title, context, extra = {}) => ({
  id,
  uiUuid: `test-uuid:${id}`,
  kind: "window",
  provider: "Test",
  title,
  context,
  searchTerms: [],
  badges: [],
  active: false,
  recency: 0,
  ...extra,
})

{
  const rows = [
    item("context", "Unrelated", "Project Alpha", { active: true, recency: 4000 }),
    item("title", "Alpha notes", "Old", { recency: -4000 }),
  ]
  assert.equal(sandbox.rank(rows, "alpha", {}).length, 1,
    "context-only matches are excluded")
  assert.equal(sandbox.rank(rows, "alpha", {})[0].id, "title", "title match wins before active/recency")
}

{
  const rows = [
    item("recent", "same", "same", { recency: 20 }),
    item("active", "same", "same", { active: true, recency: -20 }),
  ]
  assert.equal(sandbox.rank(rows, "same", {})[0].id, "active", "active thing wins before recency")
}

{
  const rows = [
    item("provider", "Unrelated", "Elsewhere", {
      provider: "Alpha", active: true, recency: 4000,
    }),
    item("context", "Unrelated", "Alpha project", { recency: -4000 }),
    item("badge", "Unrelated", "Elsewhere", { badges: ["Alpha"] }),
    item("term", "Unrelated", "Elsewhere", { searchTerms: ["Alpha"] }),
  ]
  assert.equal(sandbox.rank(rows, "alpha", {}).length, 0,
    "provider, context, badges, and hidden terms are not searchable")
  assert.equal(
    sandbox.rank([item("old", "A", ""), item("new", "B", "", { recency: 10 })], "", {})[0].id,
    "new",
    "recency breaks otherwise equal unfiltered rows",
  )
}

{
  const rows = [
    item("window", "Unrelated", "", { kind: "window" }),
    item("buffer", "Unrelated", "", { kind: "neovim-buffer" }),
  ]
  assert.deepEqual(Array.from(sandbox.rank(rows, "windows", {}), row => row.id), ["window"],
    "the displayed Windows group name is searchable")
  assert.deepEqual(Array.from(sandbox.rank(rows, "buffers", {}), row => row.id), ["buffer"],
    "the displayed Buffers group name is searchable")
}

{
  const rows = [
    item("pane", "Pane", "", { kind: "herdr-pane" }),
    item("session", "Session", "", { kind: "herdr-session" }),
    item("agent", "Agent", "", { kind: "herdr-agent" }),
    item("tab", "Tab", "", { kind: "herdr-tab" }),
    item("workspace", "Workspace", "", { kind: "herdr-workspace" }),
    item("tmux-pane", "Pane", "", { kind: "tmux-pane" }),
    item("tmux-session", "Session", "", { kind: "tmux-session" }),
    item("tmux-window", "Window", "", { kind: "tmux-window" }),
  ]
  assert.deepEqual(
    Array.from(sandbox.rank(rows, "", {}), row => row.id),
    [
      "agent", "workspace", "tab", "pane", "session",
      "tmux-session", "tmux-window", "tmux-pane",
    ],
    "Herdr groups precede tmux, with agents first and Herdr sessions last",
  )
}

{
  const rows = [item("one", "Alpha Beta", ""), item("two", "Alpha", "Gamma")]
  assert.deepEqual(Array.from(sandbox.rank(rows, "alpha be", {}), row => row.id), ["one"],
    "a contiguous multi-word title substring matches")
  assert.deepEqual(Array.from(sandbox.rank(rows, "alp bet", {}), row => row.id), [],
    "separate query fragments do not match across a gap")
  assert.deepEqual(Array.from(sandbox.rank(rows, "ab", {}), row => row.id), [],
    "non-contiguous character subsequences do not match")
  assert.deepEqual(Array.from(sandbox.rank(rows, "PHA B", {}), row => row.id), ["one"],
    "contiguous substring matching is case-insensitive")
  assert.deepEqual(Array.from(sandbox.rank([
    item("browser", "Unrelated", "", { kind: "browser-tab" }),
  ], "browser tab", {}), row => row.id), ["browser"],
  "a contiguous displayed-group substring matches")
  assert.deepEqual(Array.from(sandbox.rank([
    item("split", "Alpha", "", { kind: "window" }),
  ], "alpha windows", {}), row => row.id), [],
  "one query cannot be split between title and group")
}

{
  const rows = [
    item("pane-new", "Pane", "", { kind: "terminal-pane", recency: 20 }),
    item("window-old", "Window old", "", { kind: "window", recency: 1 }),
    item("tab", "Tab", "", { kind: "browser-tab", recency: 30 }),
    item("window-new", "Window new", "", { kind: "window", recency: 10 }),
    item("buffer", "Buffer", "", { kind: "neovim-buffer", recency: 40 }),
  ]
  assert.deepEqual(
    Array.from(sandbox.rank(rows, "", {}), row => row.id),
    ["window-new", "window-old", "tab", "pane-new", "buffer"],
    "results are grouped by kind and ranked within each group",
  )
  assert.equal(sandbox.kindSectionLabel("browser-tab"), "Browser tabs")
  assert.equal(sandbox.kindSectionLabel("neovim-buffer"), "Buffers")
  assert.equal(sandbox.sectionedRowTop(sandbox.rank(rows, "", {}), 0, 36, 24), 24)
  assert.equal(sandbox.sectionedRowTop(sandbox.rank(rows, "", {}), 2, 36, 24), 120)
}

{
  const rows = [
    item("window-one", "One", "", { kind: "window" }),
    item("window-two", "Two", "", { kind: "window" }),
    item("agent-one", "One", "", { kind: "herdr-agent" }),
    item("agent-two", "Two", "", { kind: "herdr-agent" }),
    item("tmux-one", "One", "", { kind: "tmux-pane" }),
    item("tmux-two", "Two", "", { kind: "tmux-pane" }),
  ]
  const collapsed = { "herdr-agent": true, "tmux-pane": true }
  assert.equal(sandbox.groupStartIndex(rows, 3), 2)
  assert.equal(sandbox.groupEndIndex(rows, 2), 3)
  assert.equal(sandbox.adjacentNavigableIndex(rows, 1, 1, collapsed), 2,
    "vertical movement enters a collapsed group at its heading")
  assert.equal(sandbox.adjacentNavigableIndex(rows, 3, 1, collapsed), 4,
    "vertical movement leaves a collapsed group without visiting hidden rows")
  assert.equal(sandbox.adjacentNavigableIndex(rows, 4, -1, collapsed), 2,
    "reverse movement targets the preceding collapsed heading")
  assert.equal(sandbox.boundaryNavigableIndex(rows, 1, collapsed), 4,
    "last targets the heading when the final group is collapsed")
  assert.equal(sandbox.sectionedRowTop(rows, 4, 36, 24, collapsed), 144,
    "collapsed rows contribute no height while every group retains its heading")
}

{
  const rows = [
    item("scratchpad", "Alpha scratchpad", "", {
      badges: ["Window", "Workspace special:scratch", "Scratchpad"],
      active: true,
      recency: 4000,
    }),
    item("workspace-10", "Alpha", "", {
      badges: ["Window", "Workspace 10"], active: true, recency: 4000,
    }),
    item("workspace-2", "Alpha notes", "", {
      badges: ["Window", "Workspace 2"], recency: 10,
    }),
    item("workspace-1", "Notes about alpha", "", {
      badges: ["Window", "Workspace 1"], recency: -4000,
    }),
  ]
  assert.deepEqual(
    Array.from(sandbox.rank(rows, "alpha", {}), row => row.id),
    ["workspace-1", "workspace-2", "workspace-10", "scratchpad"],
    "window metadata sorts naturally with Scratchpad after regular workspaces",
  )
}

{
  const rows = [
    item("parent-zulu", "Zulu", "", { kind: "herdr-tab" }),
    item("child-zulu", "Child Zulu", "Fallback", {
      kind: "herdr-pane", parentId: "parent-zulu", badges: ["Herdr pane"],
    }),
    item("parent-alpha", "Alpha", "", { kind: "herdr-tab" }),
    item("child-alpha", "Child Alpha", "Fallback", {
      kind: "herdr-pane", parentId: "parent-alpha", badges: ["Herdr pane"],
    }),
  ]
  assert.deepEqual(
    Array.from(sandbox.rank(rows, "child", {
      "parent-alpha": true,
      "parent-zulu": true,
    }), row => row.id),
    ["child-alpha", "child-zulu"],
    "parent-derived Herdr metadata controls ordering even when parents are filtered",
  )
}

{
  assert.equal(sandbox.kindIcon("herdr-agent"), "󱚣",
    "Herdr agents use Omarchy's agent-usage robot glyph")
  assert.notEqual(sandbox.kindIcon("window"), sandbox.kindIcon("neovim-buffer"))
  const entries = [
    {
      id: "foot.desktop", name: "Foot", startupClass: "foot",
      execString: "foot", icon: "foot",
    },
    {
      id: "Slack Loadup.desktop", name: "Slack Loadup", startupClass: "",
      execString: "omarchy-launch-webapp https://app.slack.com/client/T0BD9A3HVQF",
      icon: "slack-loadup",
    },
  ]
  assert.equal(sandbox.matchDesktopEntry(["foot"], entries), entries[0],
    "Hyprland application classes resolve native desktop entries")
  assert.equal(sandbox.matchDesktopEntry([
    "chrome-app.slack.com__client_T0BD9A3HVQF-Default",
    "app.slack.com_/client/T0BD9A3HVQF",
  ], entries), entries[1], "Hyprland web-app identity resolves its own icon")
  assert.equal(sandbox.windowAppGlyph(
    item("foot-window", "Foot", "", { iconHints: ["foot"] }), entries[0]),
    "\ue795", "known Omarchy apps use their default-font glyph")
  assert.equal(sandbox.windowAppGlyph(item("ghostty-window", "Ghostty", "", {
    iconHints: ["com.mitchellh.ghostty"],
  }), null), "\ue795", "an exact Hyprland app identity can select a known glyph")
  assert.equal(sandbox.windowAppGlyph(item("slack-window", "Slack", "", {
    iconHints: [
      "chrome-app.slack.com__client_T0BD9A3HVQF-Default",
      "google-chrome",
    ],
  }), entries[1]), "", "web apps do not inherit their host browser's glyph")
  assert.equal(sandbox.windowAppGlyph(item("docker-window", "Docker", "", {
    iconHints: ["unrelated-class"],
  }), {
    id: "com.docker.desktop.desktop", name: "Docker Desktop",
    startupClass: "", execString: "docker-desktop", icon: "docker",
  }), "\uf21f", "entry-only identities select a glyph after desktop-entry resolution")
  assert.equal(sandbox.windowAppGlyph(item("raw-docker", "Docker", "", {
    iconHints: ["docker"],
  }), null), "", "entry-only identities never match an unverified raw class")
  assert.equal(sandbox.windowAppGlyph(item("not-window", "Foot", "", {
    kind: "terminal-pane", iconHints: ["foot"],
  }), entries[0]), "", "app glyph mapping is limited to managed-window rows")
  assert.equal(sandbox.vitalMetadata(
    item("window", "Window", "App · workspace 4", { badges: ["Window", "Workspace 4"] }), ""),
    "Workspace 4")
  assert.equal(sandbox.vitalMetadata(
    item("qt-window", "Window", "App · workspace 1", {
      badges: { 0: "Window", 1: "Workspace 1", length: 2 },
    }), ""), "Workspace 1", "Qt-style list metadata excludes the kind")
  assert.equal(sandbox.vitalMetadata(
    item("joined-window", "Window", "App · workspace 1", {
      badges: "Window,Workspace 1",
    }), ""), "Workspace 1", "comma-serialized badge metadata excludes the kind")
  assert.equal(sandbox.vitalMetadata(
    item("buffer", "File", "/tmp/project", {
      kind: "neovim-buffer", badges: ["Buffer", "Modified", "Visible"],
    }), "Container › /tmp/project"),
    "project", "buffer metadata is its directory leaf, not a full path, status, or ancestry")
  assert.equal(sandbox.vitalMetadata(
    item("trailing-buffer", "File", "/tmp/project/src/", {
      kind: "neovim-buffer", badges: ["Buffer"],
    }), ""), "src", "buffer metadata ignores trailing path separators")
  assert.equal(sandbox.vitalMetadata(
    item("root-buffer", "File", "/", {
      kind: "neovim-buffer", badges: ["Buffer"],
    }), ""), "/", "the filesystem root remains meaningful buffer metadata")
  assert.equal(sandbox.vitalMetadata(
    item("browser", "Site", "Browser · native tab", { kind: "browser-tab", provider: "Firefox", badges: ["Tab", "Title only"] }), ""),
    "Firefox")
  assert.equal(sandbox.vitalMetadata(
    item("pane", "Shell", "/src", { kind: "terminal-pane", badges: ["Pane"] }), "Project › /src"),
    "Project › /src")
  assert.equal(sandbox.vitalMetadata(
    item("tmux-window", "Editor", "tmux window @4", { kind: "tmux-window", provider: "tmux", badges: ["Window"] }),
    "dev › tmux window @4", "dev"), "dev", "tmux windows show their session name")
  assert.equal(sandbox.vitalMetadata(
    item("tmux-pane", "Shell", "/src/project", { kind: "tmux-pane", provider: "tmux", badges: ["Pane"] }),
    "dev › editor › /src/project", "editor"), "editor", "tmux panes show their window name")
  assert.equal(sandbox.vitalMetadata(
    item("orphaned-tmux-pane", "Shell", "/src/project", {
      kind: "tmux-pane", provider: "tmux", badges: ["Pane"],
    }), "dev › editor › /src/project", ""), "tmux",
  "tmux child metadata never falls back to a native id or cwd chain")
  assert.equal(sandbox.vitalMetadata(
    item("surface", "Shell", "Ghostty surface", { kind: "terminal-pane", provider: "Ghostty", badges: ["Surface"] }),
    "Terminal › Ghostty surface"), "Terminal")
  const kinds = [
    "window", "browser-tab", "app-tab", "terminal-tab", "terminal-pane",
    "tmux-session", "tmux-window", "tmux-pane", "herdr-session",
    "herdr-workspace", "herdr-tab", "herdr-pane", "herdr-agent", "neovim-buffer",
  ]
  for (const kind of kinds) {
    const label = sandbox.kindLabel(kind)
    const metadata = sandbox.vitalMetadata(
      item(kind, "Title", "Useful context", { kind, provider: "Provider", badges: [label] }), "")
    assert.notEqual(metadata, label, `${kind} metadata does not repeat its kind`)
  }
  for (const kind of ["herdr-workspace", "herdr-tab", "herdr-pane"]) {
    assert.equal(sandbox.vitalMetadata(
      item(kind, "Child", "Fallback", { kind, badges: [sandbox.kindLabel(kind), "Working"] }),
      "Ancestor › Fallback", "Immediate parent"), "Immediate parent",
    `${kind} metadata is its immediate parent name`)
  }
  assert.equal(sandbox.vitalMetadata(
    item("herdr-agent", "Agent", "Fallback", { kind: "herdr-agent", badges: ["Claude", "Working"] }),
    "Ancestor › Fallback", "Parent pane"), "Working",
  "Herdr agents keep status metadata")
  assert.equal(sandbox.vitalMetadata(
    item("herdr-session", "Session", "Fallback", { kind: "herdr-session", badges: ["Session", "Attached"] }),
    "Fallback", "Ignored parent"), "Attached",
  "Herdr sessions keep session metadata")
}

{
  const hidden = sandbox.withHidden({}, "one")
  const reopened = sandbox.rank([item("one", "One", ""), item("two", "Two", "")], "", hidden)
  assert.deepEqual(Array.from(reopened, row => row.id), ["two"], "hidden ids persist across model refreshes")
}

{
  const rows = [item("one", "One", ""), item("two", "Two", ""), item("three", "Three", "")]
  assert.equal(sandbox.indexOfUuid(rows, "test-uuid:two"), 1)
  assert.equal(sandbox.indexAfterRefresh(rows, "test-uuid:two"), 1,
    "refresh follows the deterministic UI UUID")
  assert.equal(sandbox.indexAfterRefresh(rows, "test-uuid:closed"), 0,
    "a removed thing selects the first row")
  assert.equal(sandbox.indexAfterRefresh([], "test-uuid:two"), -1)
  assert.equal(sandbox.clampContentY(900, 0, 1000, 400), 600)
  assert.equal(sandbox.anchoredContentY(5, 60, 7, 0, 1000, 400), 307)
}

{
  const current = [
    item("one", "One", "", { activationToken: "old-one" }),
    item("two", "Two", "", { activationToken: "old-two" }),
  ]
  const tokenOnlyRefresh = [
    item("two", "Two", "", { activationToken: "new-two" }),
    item("one", "One", "", { activationToken: "new-one" }),
  ]
  const stable = sandbox.reconcileItems(current, tokenOnlyRefresh)
  assert.equal(stable.changed, false, "token-only refresh does not replace the visible model")
  assert.equal(stable.items, current)
  assert.equal(current[0].activationToken, "new-one")
  const changed = sandbox.reconcileItems(current, [
    item("one", "Renamed", "", { activationToken: "latest" }),
    tokenOnlyRefresh[0],
  ])
  assert.equal(changed.changed, true, "a visible field change publishes a new model")
  assert.equal(changed.items[0].title, "Renamed")

  const sameRank = [
    item("one", "One", "", { activationToken: "another-one" }),
    item("two", "Two", "", { activationToken: "another-two" }),
  ]
  assert.equal(sandbox.sameRankedItems(current, sameRank), true,
    "an identical ranked sequence does not update the UI")
  const metadataOnlyRank = [
    item("one", "One", "", { recency: 123, searchTerms: ["latest"], activationToken: "newest-one" }),
    item("two", "Two", "", { recency: 456, searchTerms: ["fresh"], activationToken: "newest-two" }),
  ]
  assert.equal(sandbox.sameRankedItems(current, metadataOnlyRank), true,
    "ranking metadata does not replace an unchanged rendered sequence")
  const metadataRefresh = sandbox.reconcileItems(current, metadataOnlyRank)
  assert.equal(metadataRefresh.changed, true,
    "the source model retains fresh ranking metadata")
  assert.equal(metadataRefresh.items[0].recency, 123)
  assert.equal(sandbox.sameRankedItems(current, sameRank.slice().reverse()), false,
    "a reordered ranked sequence updates the UI")
  assert.equal(sandbox.sameRankedItems(current, changed.items), false,
    "changed rendered traits update the UI")
  const iconChanged = [
    item("one", "One", "", { iconHints: ["new-icon"] }),
    current[1],
  ]
  assert.equal(sandbox.sameRankedItems(current, iconChanged), false,
    "a changed window icon hint updates the rendered row")
}

const qml = fs.readFileSync(path.join(root, "Everything.qml"), "utf8")
const resultListStart = qml.indexOf("id: resultList")
const searchHandler = qml.slice(qml.indexOf("id: searchField"), resultListStart)
const resultDelegateStart = qml.indexOf("\n        delegate: Item", resultListStart)
const listHandler = qml.slice(resultListStart, resultDelegateStart)
const resultDelegateHandler = qml.slice(resultDelegateStart, qml.indexOf("MouseArea", resultDelegateStart))
assert.doesNotMatch(searchHandler, /Key_Backspace|Key_Delete/, "search owns editing keys")
assert.match(searchHandler, /placeholderText:\s*"Search everything…"/,
  "the search placeholder uses the requested copy")
assert.match(qml, /focusTarget:\s*searchField/,
  "search is the panel's initial focus target")
assert.match(qml, /PanelKeyCatcher\s*\{[\s\S]*blocked:\s*searchField\.activeFocus/,
  "the standard shell key catcher yields only while search is being edited")
assert.match(qml,
  /onMoveRequested:[\s\S]*dy !== 0[\s\S]*moveSelection\(dy\)[\s\S]*dx < 0[\s\S]*collapseCurrentGroup\(\)[\s\S]*dx > 0[\s\S]*expandCurrentGroup\(\)/,
  "the shell's vertical directions move while horizontal directions fold groups")
assert.match(qml, /onActivateRequested:\s*root\.activateCurrent/,
  "the shell's Enter and Space action activates a row or expands a collapsed group")
assert.match(qml, /onDeleteRequested:\s*root\.hideAt/,
  "the shell's X action hides the selected thing")
assert.match(qml, /onTabRequested:[^\n]*root\.switchPanel\(direction\)/,
  "the shell owns Tab navigation between panels")
assert.match(listHandler, /Keys\.onPressed[\s\S]*handleSupplementalListKey/,
  "the list retains only supplemental page and control-key aliases")
assert.doesNotMatch(listHandler, /Key_Down|Key_Up|Key_Left|Key_Right|Key_Return|Key_Enter|Key_Tab|Key_Escape/,
  "the list does not override standard shell navigation")
assert.match(qml, /Key_Backspace[\s\S]*Key_Delete[\s\S]*action = "hide"/, "Backspace and Delete hide list rows")
assert.match(qml, /function hideAt[\s\S]*!selectionIsVisibleRow\(index\)[\s\S]*hideItem/,
  "hide keys cannot remove the hidden representative of a collapsed group")
assert.match(qml, /root\.close\(\)[\s\S]*Qt\.callLater[\s\S]*everythingService\.activate/, "panel closes before activation")
assert.match(qml, /onItemsChanged\(\)[\s\S]*scheduleRankedItems\(\)/,
  "provider refresh rebuilds through identity-aware reconciliation")
assert.match(qml, /sameRankedItems\(rankedItems, nextItems\)[\s\S]*return/,
  "an unchanged ranked list is not assigned to the UI")
assert.match(qml, /indexAfterRefresh\(rankedItems, selectedItemUuid/,
  "selection is restored by deterministic UI UUID")
assert.match(qml, /function rowVisualTop[\s\S]*itemAtIndex[\s\S]*delegateItem\.y/,
  "scroll restoration reads the selected delegate's live geometry")
assert.match(qml, /contentHeight > resultList\.height[\s\S]*clampContentY\(selectionVisualTop\(index\) \+ savedSelectedOffset/,
  "scroll offset is restored only when the sectioned list can scroll")
assert.match(qml, /function resetResultsForOpen\(\)[\s\S]*resultUpdateSerial \+= 1[\s\S]*collapsedKinds = \(\{\}\)[\s\S]*applyOpenResultReset\(\)/,
  "opening invalidates stale refresh restores, expands groups, and resets selection")
assert.match(qml, /root\.applyOpenResultReset\(\)[\s\S]*searchField\.forceActiveFocus\(\)/,
  "opening focuses search after resetting the results")
assert.match(qml, /function applyOpenResultReset\(\)[\s\S]*currentIndex = index[\s\S]*contentY = resultList\.originY/,
  "opening selects the first thing and resets the list scroll")
assert.match(qml, /onOpenedChanged:[\s\S]*searchField\.text = ""[\s\S]*rebuildRankedItems\(\)[\s\S]*resetResultsForOpen\(\)/,
  "every panel opening resets against the unfiltered ranked list")
assert.match(qml, /PointerMoveGate\s*\{[\s\S]*?referenceItem:\s*resultList[\s\S]*?\}/,
  "row pointer selection uses the shell movement gate")
assert.match(qml, /function selectFromPointer[\s\S]*if \(!pointerMoveGate\.moved\(item, mouse\)\) return[\s\S]*setCurrentIndex\(index, false\)/,
  "pointer selection changes only after measured movement")
assert.match(qml, /function disarmPointer[\s\S]*pointerCursorActive = false[\s\S]*pointerMoveGate\.reset\(\)/,
  "keyboard, opening, and list mutations can disarm pointer selection")
assert.match(qml, /onPositionChanged:[\s\S]*selectFromPointer\(row\.index, row, mouse\)/,
  "real row pointer movement is routed through the movement gate")
assert.doesNotMatch(qml, /rowMouse\.containsMouse/,
  "row styling never treats a stationary pointer as movement")
assert.doesNotMatch(qml, /id:\s*heading\b/,
  "the panel does not render a redundant title row")
assert.match(qml, /readonly property real rowHeight:\s*Style\.font\.body \* 1\.5/,
  "result row height scales to one and a half times the thing-name font")
assert.match(qml, /section\.property:\s*"kind"[\s\S]*section\.delegate:[\s\S]*Accessible\.Heading/,
  "the list renders accessible kind headings")
const scrollBarHandler = qml.slice(qml.indexOf("ScrollBar.vertical"),
  qml.indexOf("delegate: Item", qml.indexOf("ScrollBar.vertical")))
assert.match(scrollBarHandler, /leftPadding:\s*Style\.space\(4\)[\s\S]*rightPadding:\s*0/,
  "the native scrollbar nub is shifted toward the panel edge")
assert.match(scrollBarHandler, /palette\.mid:\s*Color\.accent[\s\S]*palette\.dark:\s*Color\.accent/,
  "the native scrollbar nub uses the theme accent")
assert.doesNotMatch(scrollBarHandler, /contentItem:|background:/,
  "scrollbar placement and color do not replace the native control")
assert.match(qml, /id:\s*sectionHeading[\s\S]*readonly property bool collapsed:[\s\S]*Accessible\.focused:\s*highlighted/,
  "a collapsed group leaves its accessible heading as the visible focus target")
assert.match(resultDelegateHandler,
  /height:\s*groupCollapsed \? 0 : root\.rowHeight[\s\S]*visible:\s*!groupCollapsed/,
  "collapsing a group hides its rows without removing its heading")
assert.match(qml, /import QtQuick\.Effects/,
  "the window image fallback can use the shell-compatible color effect")
assert.match(qml, /id:\s*mappedWindowGlyph[\s\S]*text:\s*row\.windowAppGlyph/,
  "known Omarchy apps render their default-font glyph")
assert.match(qml, /id:\s*applicationIcon[\s\S]*source:\s*row\.windowIconSource/,
  "unmapped window rows display the image resolved from Hyprland identity")
const applicationIconHandler = qml.slice(qml.indexOf("id: applicationIcon"),
  qml.indexOf("id: mappedWindowGlyph", qml.indexOf("id: applicationIcon")))
assert.match(applicationIconHandler, /visible:\s*row\.windowAppGlyph\.length === 0/,
  "a known glyph takes precedence over the application image")
assert.match(applicationIconHandler,
  /MultiEffect[\s\S]*colorization:\s*1\.0[\s\S]*colorizationColor:\s*row\.highlighted\s*\?\s*root\.foreground\s*:\s*root\.dimForeground/,
  "application images use the same selected and unselected colors as glyphs")
assert.doesNotMatch(applicationIconHandler, /modelData\.active/,
  "the provider's current marker does not brighten a colored application image")
assert.match(qml, /id:\s*fallbackThingIcon[\s\S]*Model\.kindIcon\(row\.modelData\.kind\)/,
  "rows retain a deterministic glyph fallback")
const fallbackIconHandler = qml.slice(qml.indexOf("id: fallbackThingIcon"),
  qml.indexOf("id: metadataLabel", qml.indexOf("id: fallbackThingIcon")))
assert.match(fallbackIconHandler, /color:\s*row\.highlighted\s*\?\s*root\.foreground\s*:\s*root\.dimForeground/,
  "only the actual highlight brightens a glyph icon")
assert.doesNotMatch(fallbackIconHandler, /modelData\.active/,
  "the provider's current marker does not imitate keyboard highlight")
assert.match(qml, /id:\s*metadataLabel[\s\S]*text:\s*row\.metadata/,
  "every row renders one selected metadata value")
assert.match(qml, /readonly property var itemRelations:\s*Model\.relationIndex/,
  "the panel indexes public parent relationships once per source update")
assert.match(qml, /metadataForItem\([\s\S]*modelData, root\.itemRelations\)/,
  "rendering and sorting derive metadata through the same pure helper")
assert.doesNotMatch(qml, /id:\s*badgeRow|id:\s*badgeLabel|radius:\s*height \/ 2/,
  "result rows do not render metadata pills")
const titleHandler = qml.slice(qml.indexOf("id: titleLabel"), qml.indexOf("MouseArea", qml.indexOf("id: titleLabel")))
assert.doesNotMatch(titleHandler, /font\.(?:bold|weight)/,
  "thing names remain regular weight in every state")
assert.match(titleHandler, /lineHeightMode:\s*Text\.FixedHeight[\s\S]*lineHeight:\s*root\.rowHeight/,
  "thing-name text uses the same one-and-a-half-times line height")
assert.doesNotMatch(resultDelegateHandler, /border\.(?:width|color)/,
  "the highlighted thing uses fill without an outline")
assert.doesNotMatch(qml, /refreshButton|Refresh all providers|everythingService\.refresh\(\)/,
  "automatic discovery does not expose a redundant manual refresh control")
assert.doesNotMatch(qml, /statusText|statusMessage|Starting Everything|No matches|Some providers are unavailable|Refreshing…/,
  "the panel renders no discovery, count, warning, or empty-state messages")
assert.doesNotMatch(qml, /id:\s*footer|HJKL\/↑↓ move|Keyboard help:/,
  "the panel renders no control-instruction footer")
assert.doesNotMatch(qml, /centerOnBar\s*:/, "panel uses the shell's default icon anchoring")
assert.doesNotMatch(qml, /function\s+(?:open|close|togglePanel)\s*\(/,
  "panel uses the inherited shell lifecycle")
assert.match(qml, /onPressed:[^\n]*root\.toggle\(\)/, "bar button uses the inherited shell toggle")

const serviceQml = fs.readFileSync(path.join(root, "Service.qml"), "utf8")
assert.match(serviceQml, /reconcileItems\(items, incoming\)/, "token-only snapshots keep the visible model stable")
assert.match(serviceQml, /requestScan\(false\)/, "background refreshes remain automatic")
assert.doesNotMatch(serviceQml, /statusMessage|activeScanQuiet/,
  "the service carries no dead panel-message state")
assert.doesNotMatch(serviceQml, /function refresh\s*\(/,
  "the service has no unused manual refresh entry point")

console.log("model.test.js: all tests passed")
