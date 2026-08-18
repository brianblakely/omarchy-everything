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
  const hidden = sandbox.withHidden({}, "one")
  const reopened = sandbox.rank([item("one", "One", ""), item("two", "Two", "")], "", hidden)
  assert.deepEqual(Array.from(reopened, row => row.id), ["two"], "hidden ids persist across model refreshes")
  assert.equal(sandbox.nextIndexAfterRemoval(2, 3), 1)
  assert.equal(sandbox.nextIndexAfterRemoval(0, 1), -1)
}

{
  const rows = [item("one", "One", ""), item("two", "Two", ""), item("three", "Three", "")]
  assert.equal(sandbox.indexOfId(rows, "two"), 1)
  assert.equal(sandbox.indexAfterRefresh(rows, "two", 0), 1, "refresh follows the stable thing id")
  assert.equal(sandbox.indexAfterRefresh(rows, "closed", 2), 2, "a closed thing keeps the nearest index")
  assert.equal(sandbox.indexAfterRefresh([], "two", 1), -1)
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
}

const qml = fs.readFileSync(path.join(root, "Everything.qml"), "utf8")
const searchHandler = qml.slice(qml.indexOf("id: searchField"), qml.indexOf("id: statusText"))
const listHandler = qml.slice(qml.indexOf("id: resultList"), qml.indexOf("delegate: Item"))
assert.doesNotMatch(searchHandler, /Key_Backspace|Key_Delete/, "search owns editing keys")
assert.match(qml, /focusTarget:\s*keyCatcher/, "the shell key catcher receives initial panel focus")
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
assert.match(qml, /onItemsChanged\(\)[\s\S]*scheduleRankedItems\(true\)/, "provider refresh preserves UI state")
assert.match(qml, /indexAfterRefresh\(rankedItems, selectedThingId/, "selection is restored by stable thing id")
assert.doesNotMatch(qml, /centerOnBar\s*:/, "panel uses the shell's default icon anchoring")
assert.doesNotMatch(qml, /function\s+(?:open|close|togglePanel)\s*\(/,
  "panel uses the inherited shell lifecycle")
assert.match(qml, /onPressed:[^\n]*root\.toggle\(\)/, "bar button uses the inherited shell toggle")

const serviceQml = fs.readFileSync(path.join(root, "Service.qml"), "utf8")
assert.match(serviceQml, /reconcileItems\(items, incoming\)/, "token-only snapshots keep the visible model stable")
assert.match(serviceQml, /requestScan\(false, true\)/, "background refreshes do not flash status text")

console.log("model.test.js: all tests passed")
