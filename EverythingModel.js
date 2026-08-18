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
  if (typeof value !== "string" && typeof value.length === "number") {
    var sequence = []
    for (var index = 0; index < value.length; index++) sequence.push(String(value[index]))
    return sequence
  }
  return [String(value)]
}

function badgeList(value) {
  var badges = stringList(value)
  // QML can expose a typed QVariantList to an imported JavaScript library as
  // one comma-joined string. Provider badges never contain commas, so recover
  // the protocol list here instead of displaying its serialization.
  if (badges.length === 1 && badges[0].indexOf(",") >= 0) {
    return badges[0].split(",").map(function(entry) { return entry.trim() })
      .filter(function(entry) { return entry.length > 0 })
  }
  return badges
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

function kindIcon(kind) {
  var icons = {
    "window": "\uf2d0",
    "browser-tab": "\uf0ac",
    "app-tab": "\uf24d",
    "terminal-tab": "\uf120",
    "terminal-pane": "\uf0db",
    "tmux-session": "\uf233",
    "tmux-window": "\uf24d",
    "tmux-pane": "\uf0db",
    "herdr-session": "\uf233",
    "herdr-workspace": "\uf009",
    "herdr-tab": "\uf24d",
    "herdr-pane": "\uf0db",
    "herdr-agent": "\uf544",
    "neovim-buffer": "\uf1c9"
  }
  return icons[String(kind)] || "\uf128"
}

function isKindMetadata(value) {
  var kinds = {
    "thing": true,
    "window": true,
    "windows": true,
    "tab": true,
    "tabs": true,
    "browser tab": true,
    "browser tabs": true,
    "app tab": true,
    "application tab": true,
    "application tabs": true,
    "terminal tab": true,
    "terminal tabs": true,
    "pane": true,
    "panes": true,
    "terminal pane": true,
    "terminal panes": true,
    "surface": true,
    "surfaces": true,
    "session": true,
    "sessions": true,
    "tmux session": true,
    "tmux sessions": true,
    "tmux window": true,
    "tmux windows": true,
    "tmux pane": true,
    "tmux panes": true,
    "herdr session": true,
    "herdr sessions": true,
    "workspace": true,
    "workspaces": true,
    "herdr workspace": true,
    "herdr workspaces": true,
    "herdr tab": true,
    "herdr tabs": true,
    "herdr pane": true,
    "herdr panes": true,
    "agent": true,
    "agents": true,
    "herdr agent": true,
    "herdr agents": true,
    "buffer": true,
    "buffers": true,
    "neovim buffer": true,
    "neovim buffers": true,
    "native": true,
    "title only": true
  }
  return kinds[normalized(value)] === true
}

function contextMetadata(item, breadcrumb) {
  var kind = String(item && item.kind || "")
  var provider = String(item && item.provider || "")
  if (kind === "browser-tab" || kind === "app-tab") return provider

  var value = String(breadcrumb || (item && item.context) || "").trim()
  if (kind === "tmux-window") value = value.replace(/\btmux window\s+/i, "")
  else if (kind === "tmux-pane") value = value.replace(/\btmux pane\s+/i, "")
  else if (kind === "terminal-pane"
           && normalized(item.context) === normalized(provider + " surface")) {
    var context = String(item.context || "")
    var prefix = value.slice(0, Math.max(0, value.length - context.length))
      .replace(/\s*›\s*$/, "").trim()
    value = prefix || provider
  }

  if (isKindMetadata(value)) return provider
  return value || provider
}

function vitalMetadata(item, breadcrumb, parentTitle) {
  if (!item) return ""
  var kind = String(item.kind || "")
  if (kind === "herdr-workspace" || kind === "herdr-tab" || kind === "herdr-pane") {
    var parent = String(parentTitle || "").trim()
    if (parent) return parent
  }
  var badges = badgeList(item.badges)
  var priorities = [
    "error", "blocked", "modified", "working", "scratchpad", "hidden",
    "detached", "unloaded", "visible", "attached", "group", "done", "idle"
  ]
  for (var priority = 0; priority < priorities.length; priority++) {
    for (var badge = 0; badge < badges.length; badge++) {
      if (normalized(badges[badge]) === priorities[priority]) return badges[badge]
    }
  }

  for (var index = badges.length - 1; index >= 0; index--) {
    if (!isKindMetadata(badges[index])) return badges[index]
  }
  return contextMetadata(item, breadcrumb)
}

function kindSectionLabel(kind) {
  var labels = {
    "window": "Windows",
    "browser-tab": "Browser tabs",
    "app-tab": "Application tabs",
    "terminal-tab": "Terminal tabs",
    "terminal-pane": "Terminal panes",
    "tmux-session": "tmux sessions",
    "tmux-window": "tmux windows",
    "tmux-pane": "tmux panes",
    "herdr-session": "Herdr sessions",
    "herdr-workspace": "Herdr workspaces",
    "herdr-tab": "Herdr tabs",
    "herdr-pane": "Herdr panes",
    "herdr-agent": "Herdr agents",
    "neovim-buffer": "Buffers"
  }
  return labels[String(kind)] || "Other things"
}

function kindOrder(kind) {
  var order = {
    "window": 0,
    "browser-tab": 1,
    "app-tab": 2,
    "terminal-tab": 3,
    "terminal-pane": 4,
    "tmux-session": 5,
    "tmux-window": 6,
    "tmux-pane": 7,
    "herdr-agent": 8,
    "herdr-workspace": 9,
    "herdr-tab": 10,
    "herdr-pane": 11,
    "herdr-session": 12,
    "neovim-buffer": 13
  }
  var value = order[String(kind)]
  return value === undefined ? 1000 : value
}

function rankedEntry(item, tokens, sourceIndex) {
  var title = normalized(item.title)
  var group = normalized(kindSectionLabel(item.kind))
  var titleHits = 0
  var groupHits = 0
  var quality = 0

  for (var i = 0; i < tokens.length; i++) {
    var token = tokens[i]
    var titleScore = fuzzyScore(title, token)
    var groupScore = fuzzyScore(group, token)
    if (titleScore >= 0) {
      titleHits++
      quality += titleScore
    } else if (groupScore >= 0) {
      groupHits++
      quality += groupScore
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
    groupHits: groupHits,
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
    var groupOrder = kindOrder(a.item.kind) - kindOrder(b.item.kind)
    if (groupOrder !== 0) return groupOrder
    var fields = ["titleHits", "groupHits", "quality", "active", "recency"]
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

function itemUuid(item) {
  if (!item) return ""
  return String(item.uiUuid || item.id || "")
}

function indexOfUuid(items, uuid) {
  var source = Array.isArray(items) ? items : []
  var wanted = String(uuid || "")
  if (!wanted) return -1
  for (var i = 0; i < source.length; i++) {
    if (itemUuid(source[i]) === wanted) return i
  }
  return -1
}

function indexAfterRefresh(items, selectedUuid) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0) return -1
  var exact = indexOfUuid(source, selectedUuid)
  if (exact >= 0) return exact
  return 0
}

function sectionedRowTop(items, index, rowHeight, sectionHeight) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0 || index < 0) return 0
  var bounded = Math.min(source.length - 1, Math.floor(Number(index || 0)))
  var sections = 0
  var previous = ""
  for (var i = 0; i <= bounded; i++) {
    var current = String(source[i] && source[i].kind || "")
    if (i === 0 || current !== previous) sections++
    previous = current
  }
  return bounded * Math.max(1, Number(rowHeight || 1))
    + sections * Math.max(0, Number(sectionHeight || 0))
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

function sameRenderedTraits(left, right) {
  if (!left || !right) return false
  return itemUuid(left) === itemUuid(right)
    && String(left.id || "") === String(right.id || "")
    && String(left.kind || "") === String(right.kind || "")
    && String(left.provider || "") === String(right.provider || "")
    && String(left.title || "") === String(right.title || "")
    && String(left.context || "") === String(right.context || "")
    && String(left.parentId || "") === String(right.parentId || "")
    && (left.active === true) === (right.active === true)
    && sameStringList(left.badges, right.badges)
}

function sameSourceTraits(left, right) {
  return sameRenderedTraits(left, right)
    && Number(left.recency || 0) === Number(right.recency || 0)
    && sameStringList(left.searchTerms, right.searchTerms)
}

function sameRankedItems(currentItems, incomingItems) {
  var current = Array.isArray(currentItems) ? currentItems : []
  var incoming = Array.isArray(incomingItems) ? incomingItems : []
  if (current.length !== incoming.length) return false
  for (var i = 0; i < current.length; i++) {
    if (itemUuid(current[i]) !== itemUuid(incoming[i])
        || !sameRenderedTraits(current[i], incoming[i])) return false
  }
  return true
}

function reconcileItems(currentItems, incomingItems) {
  var current = Array.isArray(currentItems) ? currentItems : []
  var incoming = Array.isArray(incomingItems) ? incomingItems : []
  var existing = {}
  var changed = current.length !== incoming.length
  for (var i = 0; i < current.length; i++) {
    var oldUuid = itemUuid(current[i])
    if (!oldUuid || existing[oldUuid]) changed = true
    else existing[oldUuid] = current[i]
  }

  var next = []
  var seen = {}
  for (var row = 0; row < incoming.length; row++) {
    var fresh = incoming[row]
    var uuid = itemUuid(fresh)
    var previous = uuid ? existing[uuid] : null
    if (!uuid || seen[uuid] || !sameSourceTraits(previous, fresh)) {
      changed = true
      next.push(fresh)
    } else {
      // Activation generations change on every provider scan. Keep the row
      // object stable when only its opaque token changes so Qt does not tear
      // down and rebuild a visually identical list.
      if (fresh.activationToken) previous.activationToken = fresh.activationToken
      next.push(previous)
    }
    if (uuid) seen[uuid] = true
  }

  if (!changed) return { items: current, changed: false }
  return { items: next, changed: true }
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
