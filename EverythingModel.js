.pragma library

// Pure model helpers. Keep this file free of QML object references so the
// ranking and keyboard rules can also be exercised by the Node test fixture.

function normalized(value) {
  var text = String(value === undefined || value === null ? "" : value).toLowerCase()
  try {
    text = text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
  } catch (_error) {
    // Qt's JS engine on supported Quattro builds has normalize(); keeping the
    // fallback makes malformed external titles harmless.
  }
  return text.replace(/\s+/g, " ").trim()
}

function queryTokens(query) {
  var value = normalized(query)
  return value ? value.split(" ").filter(function(token) { return token.length > 0 }) : []
}

function fuzzyScore(haystack, needle) {
  var hay = normalized(haystack)
  var token = normalized(needle)
  if (!token) return 0
  if (!hay) return -1

  var exact = hay === token
  var prefix = hay.indexOf(token) === 0
  var contiguous = hay.indexOf(token)
  if (exact) return 12000
  if (prefix) return 9000 - Math.min(1000, hay.length - token.length)
  if (contiguous >= 0) return 7000 - Math.min(2000, contiguous * 16 + hay.length - token.length)

  var cursor = 0
  var first = -1
  var previous = -1
  var gaps = 0
  var boundaryBonus = 0
  for (var i = 0; i < token.length; i++) {
    var found = hay.indexOf(token.charAt(i), cursor)
    if (found < 0) return -1
    if (first < 0) first = found
    if (previous >= 0) gaps += found - previous - 1
    if (found === 0 || /[\s/_.:\-]/.test(hay.charAt(found - 1))) boundaryBonus += 24
    previous = found
    cursor = found + 1
  }
  return 4200 + boundaryBonus - Math.min(3000, first * 20 + gaps * 28 + hay.length)
}

function stringList(value) {
  if (Array.isArray(value)) return value.map(function(entry) { return String(entry) })
  if (value === undefined || value === null || value === "") return []
  return [String(value)]
}

function kindLabel(kind) {
  var labels = {
    "window": "Window",
    "browser-tab": "Browser tab",
    "app-tab": "App tab",
    "terminal-tab": "Terminal tab",
    "terminal-pane": "Terminal pane",
    "tmux-session": "tmux session",
    "tmux-window": "tmux window",
    "tmux-pane": "tmux pane",
    "herdr-session": "Herdr session",
    "herdr-workspace": "Herdr workspace",
    "herdr-tab": "Herdr tab",
    "herdr-pane": "Herdr pane",
    "herdr-agent": "Herdr agent",
    "neovim-buffer": "Neovim buffer"
  }
  return labels[String(kind)] || String(kind || "Thing")
}

function rankedEntry(item, tokens, sourceIndex) {
  var title = normalized(item.title)
  var context = normalized(item.context)
  var typeText = normalized(String(item.provider || "") + " " + kindLabel(item.kind)
                            + " " + stringList(item.badges).join(" ")
                            + " " + stringList(item.searchTerms).join(" "))
  var titleHits = 0
  var contextHits = 0
  var typeHits = 0
  var quality = 0

  for (var i = 0; i < tokens.length; i++) {
    var token = tokens[i]
    var titleScore = fuzzyScore(title, token)
    var contextScore = fuzzyScore(context, token)
    var typeScore = fuzzyScore(typeText, token)
    if (titleScore >= 0) {
      titleHits++
      quality += titleScore
    } else if (contextScore >= 0) {
      contextHits++
      quality += contextScore
    } else if (typeScore >= 0) {
      typeHits++
      quality += typeScore
    } else {
      return null
    }
  }

  var recency = Number(item.recency || 0)
  if (!isFinite(recency)) recency = 0
  // Keep ranking fields separate so even an unusually long query cannot
  // overflow a numeric bucket and invert the documented lexicographic order.
  return {
    item: item,
    titleHits: titleHits,
    contextHits: contextHits,
    typeHits: typeHits,
    quality: quality,
    active: item.active === true ? 1 : 0,
    recency: Math.max(-4000, Math.min(4000, recency)),
    sourceIndex: sourceIndex
  }
}

function rank(items, query, hiddenIds) {
  var source = Array.isArray(items) ? items : []
  var hidden = hiddenIds || {}
  var tokens = queryTokens(query)
  var ranked = []
  for (var i = 0; i < source.length; i++) {
    var item = source[i]
    if (!item || !item.id || hidden[String(item.id)] === true) continue
    var entry = rankedEntry(item, tokens, i)
    if (entry) ranked.push(entry)
  }
  ranked.sort(function(a, b) {
    var fields = ["titleHits", "contextHits", "typeHits", "quality", "active", "recency"]
    for (var field = 0; field < fields.length; field++) {
      var name = fields[field]
      if (a[name] !== b[name]) return b[name] - a[name]
    }
    var titleOrder = normalized(a.item.title).localeCompare(normalized(b.item.title))
    if (titleOrder !== 0) return titleOrder
    var idOrder = String(a.item.id).localeCompare(String(b.item.id))
    return idOrder !== 0 ? idOrder : a.sourceIndex - b.sourceIndex
  })
  return ranked.map(function(entry) { return entry.item })
}

function indexOfId(items, id) {
  var source = Array.isArray(items) ? items : []
  var wanted = String(id || "")
  if (!wanted) return -1
  for (var i = 0; i < source.length; i++) {
    if (source[i] && String(source[i].id || "") === wanted) return i
  }
  return -1
}

function indexAfterRefresh(items, selectedId, indexHint) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0) return -1
  var exact = indexOfId(source, selectedId)
  if (exact >= 0) return exact
  var hint = Number(indexHint)
  if (!isFinite(hint)) hint = 0
  return Math.max(0, Math.min(source.length - 1, Math.floor(hint)))
}

function clampContentY(value, originY, contentHeight, viewHeight) {
  var origin = Number(originY || 0)
  var content = Math.max(0, Number(contentHeight || 0))
  var visible = Math.max(0, Number(viewHeight || 0))
  var maximum = origin + Math.max(0, content - visible)
  var wanted = Number(value)
  if (!isFinite(wanted)) wanted = origin
  return Math.max(origin, Math.min(maximum, wanted))
}

function anchoredContentY(index, rowHeight, offset, originY, contentHeight, viewHeight) {
  var row = Math.max(1, Number(rowHeight || 1))
  var anchor = Math.max(0, Math.floor(Number(index || 0)))
  var wanted = Number(originY || 0) + anchor * row + Number(offset || 0)
  return clampContentY(wanted, originY, contentHeight, viewHeight)
}

function nextIndexAfterRemoval(index, lengthBefore) {
  var remaining = Math.max(0, Number(lengthBefore || 0) - 1)
  if (remaining === 0) return -1
  return Math.max(0, Math.min(Number(index || 0), remaining - 1))
}

function withHidden(hiddenIds, id) {
  var next = {}
  var current = hiddenIds || {}
  for (var key in current) next[key] = current[key]
  if (id) next[String(id)] = true
  return next
}

function sameStringList(left, right) {
  var a = stringList(left)
  var b = stringList(right)
  if (a.length !== b.length) return false
  for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

function samePresentation(left, right) {
  if (!left || !right) return false
  return String(left.id || "") === String(right.id || "")
    && String(left.kind || "") === String(right.kind || "")
    && String(left.provider || "") === String(right.provider || "")
    && String(left.title || "") === String(right.title || "")
    && String(left.context || "") === String(right.context || "")
    && String(left.parentId || "") === String(right.parentId || "")
    && (left.active === true) === (right.active === true)
    && Number(left.recency || 0) === Number(right.recency || 0)
    && sameStringList(left.searchTerms, right.searchTerms)
    && sameStringList(left.badges, right.badges)
}

function reconcileItems(currentItems, incomingItems) {
  var current = Array.isArray(currentItems) ? currentItems : []
  var incoming = Array.isArray(incomingItems) ? incomingItems : []
  var existing = {}
  var changed = current.length !== incoming.length
  for (var i = 0; i < current.length; i++) {
    var oldId = current[i] && String(current[i].id || "")
    if (!oldId || existing[oldId]) changed = true
    else existing[oldId] = current[i]
  }

  var next = []
  var seen = {}
  for (var row = 0; row < incoming.length; row++) {
    var fresh = incoming[row]
    var id = fresh && String(fresh.id || "")
    var previous = id ? existing[id] : null
    if (!id || seen[id] || !samePresentation(previous, fresh)) {
      changed = true
      next.push(fresh)
    } else {
      // Activation generations change on every provider scan. Keep the row
      // object stable when only its opaque token changes so Qt does not tear
      // down and rebuild a visually identical list.
      if (fresh.activationToken) previous.activationToken = fresh.activationToken
      next.push(previous)
    }
    if (id) seen[id] = true
  }

  if (!changed) return { items: current, changed: false }
  return { items: next, changed: true }
}

// Canonical names used by both the QML key handler and its table-driven tests.
function keyboardAction(key, ctrl, shift, text) {
  var name = String(key || "").toLowerCase()
  var typed = String(text || "")
  if (name === "down" || (ctrl && name === "n")) return "next"
  if (name === "up" || (ctrl && name === "p")) return "previous"
  if (name === "home" || (!ctrl && !shift && typed === "g")) return "first"
  if (name === "end" || (!ctrl && typed === "G")) return "last"
  if (name === "pagedown" || (ctrl && name === "d")) return "page-next"
  if (name === "pageup" || (ctrl && name === "u")) return "page-previous"
  if (name === "return" || name === "enter") return "activate"
  if (name === "slash" || typed === "/") return "search"
  if (name === "backspace" || name === "delete") return "hide"
  if (name === "escape") return "escape"
  return ""
}

function mergeProviderItems(providerItems) {
  var out = []
  var seen = {}
  var providers = providerItems || {}
  var keys = Object.keys(providers).sort()
  for (var p = 0; p < keys.length; p++) {
    var rows = Array.isArray(providers[keys[p]]) ? providers[keys[p]] : []
    for (var i = 0; i < rows.length; i++) {
      var item = rows[i]
      if (!item || !item.id || seen[String(item.id)]) continue
      seen[String(item.id)] = true
      out.push(item)
    }
  }
  return out
}
