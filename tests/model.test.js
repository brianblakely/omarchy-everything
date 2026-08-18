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
    item("type", "Unrelated", "Elsewhere", { provider: "Alpha", active: true, recency: 4000 }),
    item("context", "Unrelated", "Alpha project", { recency: -4000 }),
  ]
  assert.equal(sandbox.rank(rows, "alpha", {})[0].id, "context", "context match wins before type/current")
  assert.equal(
    sandbox.rank([item("old", "A", ""), item("new", "B", "", { recency: 10 })], "", {})[0].id,
    "new",
    "recency breaks otherwise equal unfiltered rows",
  )
}

{
  const rows = [item("one", "Alpha Beta", ""), item("two", "Alpha", "Gamma")]
  assert.deepEqual(Array.from(sandbox.rank(rows, "alp bet", {}), row => row.id), ["one"])
  assert.equal(sandbox.rank(rows, "ab", {})[0].id, "one", "subsequence fuzzy matching works")
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
  assert.equal(sandbox.kindSectionLabel("neovim-buffer"), "Neovim buffers")
  assert.equal(sandbox.sectionedRowTop(sandbox.rank(rows, "", {}), 0, 36, 24), 24)
  assert.equal(sandbox.sectionedRowTop(sandbox.rank(rows, "", {}), 2, 36, 24), 120)
}

{
  assert.notEqual(sandbox.kindIcon("window"), sandbox.kindIcon("neovim-buffer"))
  assert.equal(sandbox.vitalMetadata(
    item("window", "Window", "App · workspace 4", { badges: ["Window", "Workspace 4"] }), ""),
  "Workspace 4")
  assert.equal(sandbox.vitalMetadata(
    item("buffer", "File", "/tmp/file", { kind: "neovim-buffer", badges: ["Buffer", "Modified", "Visible"] }), ""),
  "Modified")
  assert.equal(sandbox.vitalMetadata(
    item("browser", "Site", "Browser · native tab", { kind: "browser-tab", provider: "Firefox", badges: ["Tab", "Title only"] }), ""),
  "Firefox")
  assert.equal(sandbox.vitalMetadata(
    item("pane", "Shell", "/src", { kind: "terminal-pane", badges: ["Pane"] }), "Project › /src"),
  "Project › /src")
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
}

const qml = fs.readFileSync(path.join(root, "Everything.qml"), "utf8")
const searchHandler = qml.slice(qml.indexOf("id: searchField"), qml.indexOf("id: statusText"))
const resultListStart = qml.indexOf("id: resultList")
const resultDelegateStart = qml.indexOf("\n        delegate: Item", resultListStart)
const listHandler = qml.slice(resultListStart, resultDelegateStart)
const statusHandler = qml.slice(qml.indexOf("id: statusText"), resultListStart)
assert.doesNotMatch(searchHandler, /Key_Backspace|Key_Delete/, "search owns editing keys")
assert.match(qml, /focusTarget:\s*resultList/,
  "the list owns focus while the shell key catcher remains its navigation wrapper")
assert.match(qml, /PanelKeyCatcher\s*\{[\s\S]*blocked:\s*searchField\.activeFocus/,
  "the standard shell key catcher yields only while search is being edited")
assert.match(qml, /onMoveRequested:[\s\S]*dy !== 0 \? dy : dx[\s\S]*moveSelection\(delta\)/,
  "the shell's H J K L and arrow directions drive the list")
assert.match(qml, /onActivateRequested:\s*root\.activateAt/,
  "the shell's Enter and Space action activates the selected thing")
assert.match(qml, /onDeleteRequested:\s*root\.hideAt/,
  "the shell's X action hides the selected thing")
assert.match(qml, /onTabRequested:[^\n]*root\.switchPanel\(direction\)/,
  "the shell owns Tab navigation between panels")
assert.match(listHandler, /Keys\.onPressed[\s\S]*handleSupplementalListKey/,
  "the list retains only supplemental page and control-key aliases")
assert.doesNotMatch(listHandler, /Key_Down|Key_Up|Key_Left|Key_Right|Key_Return|Key_Enter|Key_Tab|Key_Escape/,
  "the list does not override standard shell navigation")
assert.match(qml, /Key_Backspace[\s\S]*Key_Delete[\s\S]*action = "hide"/, "Backspace and Delete hide list rows")
assert.match(qml, /root\.close\(\)[\s\S]*Qt\.callLater[\s\S]*everythingService\.activate/, "panel closes before activation")
assert.match(qml, /onItemsChanged\(\)[\s\S]*scheduleRankedItems\(\)/,
  "provider refresh rebuilds through identity-aware reconciliation")
assert.match(qml, /sameRankedItems\(rankedItems, nextItems\)[\s\S]*return/,
  "an unchanged ranked list is not assigned to the UI")
assert.match(qml, /indexAfterRefresh\(rankedItems, selectedItemUuid/,
  "selection is restored by deterministic UI UUID")
assert.match(qml, /function rowVisualTop[\s\S]*itemAtIndex[\s\S]*delegateItem\.y/,
  "scroll restoration reads the selected delegate's live geometry")
assert.match(qml, /contentHeight > resultList\.height[\s\S]*clampContentY\(rowVisualTop\(index\) \+ savedSelectedOffset/,
  "scroll offset is restored only when the sectioned list can scroll")
assert.match(qml, /function resetResultsForOpen\(\)[\s\S]*resultUpdateSerial \+= 1[\s\S]*applyOpenResultReset\(\)/,
  "opening invalidates stale refresh restores and resets the selected thing")
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
assert.match(qml, /readonly property int rowHeight:\s*Style\.space\(36\)/,
  "result rows use the compact single-line layout")
assert.match(qml, /section\.property:\s*"kind"[\s\S]*section\.delegate:[\s\S]*Accessible\.Heading/,
  "the list renders accessible kind headings")
assert.match(qml, /id:\s*thingIcon[\s\S]*Model\.kindIcon\(row\.modelData\.kind\)/,
  "every row displays its deterministic kind icon")
assert.match(qml, /id:\s*metadataLabel[\s\S]*text:\s*row\.metadata/,
  "every row renders one selected metadata value")
assert.doesNotMatch(qml, /id:\s*badgeRow|id:\s*badgeLabel|radius:\s*height \/ 2/,
  "result rows do not render metadata pills")
assert.doesNotMatch(qml, /refreshButton|Refresh all providers|everythingService\.refresh\(\)/,
  "automatic discovery does not expose a redundant manual refresh control")
assert.match(statusHandler, /visible:\s*text\.length > 0[\s\S]*height:\s*visible \? Style\.space\(22\) : 0/,
  "the status row collapses when it has no actionable message")
assert.doesNotMatch(statusHandler, /rankedItems\.length \+|\? " thing" : " things"/,
  "the panel does not display a result count")
assert.doesNotMatch(qml, /centerOnBar\s*:/, "panel uses the shell's default icon anchoring")
assert.doesNotMatch(qml, /function\s+(?:open|close|togglePanel)\s*\(/,
  "panel uses the inherited shell lifecycle")
assert.match(qml, /onPressed:[^\n]*root\.toggle\(\)/, "bar button uses the inherited shell toggle")

const serviceQml = fs.readFileSync(path.join(root, "Service.qml"), "utf8")
assert.match(serviceQml, /reconcileItems\(items, incoming\)/, "token-only snapshots keep the visible model stable")
assert.match(serviceQml, /requestScan\(false, true\)/, "background refreshes do not flash status text")
assert.doesNotMatch(serviceQml, /function refresh\s*\(/,
  "the service has no unused manual refresh entry point")

console.log("model.test.js: all tests passed")
