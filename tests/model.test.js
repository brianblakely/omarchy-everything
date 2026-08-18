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

const aliases = [
  ["down", false, false, "", "next"],
  ["n", true, false, "", "next"],
  ["up", false, false, "", "previous"],
  ["p", true, false, "", "previous"],
  ["home", false, false, "", "first"],
  ["g", false, false, "g", "first"],
  ["end", false, false, "", "last"],
  ["g", false, true, "G", "last"],
  ["pagedown", false, false, "", "page-next"],
  ["d", true, false, "", "page-next"],
  ["pageup", false, false, "", "page-previous"],
  ["u", true, false, "", "page-previous"],
  ["enter", false, false, "", "activate"],
  ["slash", false, false, "/", "search"],
  ["backspace", false, false, "", "hide"],
  ["delete", false, false, "", "hide"],
  ["escape", false, false, "", "escape"],
]
for (const [key, ctrl, shift, text, expected] of aliases)
  assert.equal(sandbox.keyboardAction(key, ctrl, shift, text), expected, `${key} alias`)

const qml = fs.readFileSync(path.join(root, "Everything.qml"), "utf8")
const searchHandler = qml.slice(qml.indexOf("id: searchField"), qml.indexOf("id: statusText"))
const listHandler = qml.slice(qml.indexOf("id: resultList"), qml.indexOf("delegate: Item"))
assert.doesNotMatch(searchHandler, /Key_Backspace|Key_Delete/, "search owns editing keys")
assert.match(listHandler, /Keys\.onPressed[\s\S]*handleListKey/, "list owns thing commands")
assert.match(qml, /Key_Backspace[\s\S]*Key_Delete[\s\S]*action = "hide"/, "Backspace and Delete hide list rows")
assert.match(qml, /root\.close\(\)[\s\S]*Qt\.callLater[\s\S]*everythingService\.activate/, "panel closes before activation")
assert.match(qml, /onItemsChanged\(\)[\s\S]*scheduleRankedItems\(true\)/, "provider refresh preserves UI state")
assert.match(qml, /indexAfterRefresh\(rankedItems, selectedThingId/, "selection is restored by stable thing id")

const serviceQml = fs.readFileSync(path.join(root, "Service.qml"), "utf8")
assert.match(serviceQml, /reconcileItems\(items, incoming\)/, "token-only snapshots keep the visible model stable")
assert.match(serviceQml, /requestScan\(false, true\)/, "background refreshes do not flash status text")

console.log("model.test.js: all tests passed")
