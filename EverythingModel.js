.pragma library

// Pure model helpers. Keep this file free of QML object references so the
// ranking and keyboard rules can also be exercised by the Node test fixture.

// App glyphs assigned by Omarchy's current default menu and supplied by its
// default JetBrainsMono Nerd Font package. Matching stays exact so a web-app
// class such as "chrome-chatgpt.com__-Default" does not become Chrome.
var APP_GLYPHS = {
  "1password": "\udb82\udc81",
  "alacritty": "\ue795",
  "app.zen_browser.zen": "\udb81\udd9f",
  "bitwarden": "\udb81\udff5",
  "brave": "\udb81\udd9f",
  "brave-browser": "\udb81\udd9f",
  "brave-origin": "\udb81\udd9f",
  "chrome": "\udb80\udeaf",
  "chromium": "\uf268",
  "chromium-browser": "\uf268",
  "code": "\ue8da",
  "code-oss": "\ue8da",
  "com.1password.1password": "\udb82\udc81",
  "com.bitwarden.desktop": "\udb81\udff5",
  "com.brave.browser": "\udb81\udd9f",
  "com.google.chrome": "\udb80\udeaf",
  "com.heroicgameslauncher.hgl": "\udb85\udcdf",
  "com.microsoft.edge": "\udb80\udde9",
  "com.mitchellh.ghostty": "\ue795",
  "com.spotify.client": "\udb81\udcc7",
  "com.valvesoftware.steam": "\uf1b6",
  "com.visualstudio.code": "\ue8da",
  "com.vscodium.codium": "\ue8da",
  "dropbox": "\ue707",
  "edge": "\udb80\udde9",
  "firefox": "\udb80\ude39",
  "firefox-esr": "\udb80\ude39",
  "foot": "\ue795",
  "ghostty": "\ue795",
  "google-chrome": "\udb80\udeaf",
  "google-chrome-stable": "\udb80\udeaf",
  "heroic": "\udb85\udcdf",
  "heroic games launcher": "\udb85\udcdf",
  "io.neovim.nvim": "\ue6ae",
  "kitty": "\ue795",
  "lutris": "\uef94",
  "microsoft-edge": "\udb80\udde9",
  "microsoft-edge-stable": "\udb80\udde9",
  "minecraft": "\udb80\udf73",
  "minecraft-launcher": "\udb80\udf73",
  "net.lutris.lutris": "\uef94",
  "neovim": "\ue6ae",
  "nvim": "\ue6ae",
  "org.codeberg.dnkl.foot": "\ue795",
  "org.libretro.retroarch": "\udb82\udfc9",
  "org.mozilla.firefox": "\udb80\ude39",
  "org.omarchy.nvim": "\ue6ae",
  "org.signal.signal": "\udb82\udf79",
  "retroarch": "\udb82\udfc9",
  "signal": "\udb82\udf79",
  "signal-desktop": "\udb82\udf79",
  "spotify": "\udb81\udcc7",
  "steam": "\uf1b6",
  "vim": "\ue62b",
  "visual studio code": "\ue8da",
  "vscode": "\ue8da",
  "xbox cloud gaming": "\ued3e",
  "zen": "\udb81\udd9f",
  "zen-browser": "\udb81\udd9f"
}

// These identities are safe only after resolving a desktop entry. In
// particular, a raw class named "docker" need not represent Docker Desktop.
var ENTRY_ONLY_APP_GLYPHS = {
  "com.docker.desktop": "\uf21f",
  "docker": "\uf21f"
}

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

function substringScore(haystack, needle) {
  var hay = normalized(haystack)
  var query = normalized(needle)
  if (!query) return 0
  if (!hay) return -1

  var exact = hay === query
  var contiguous = hay.indexOf(query)
  if (exact) return 12000
  if (contiguous === 0) return 9000 - Math.min(1000, hay.length - query.length)
  if (contiguous > 0)
    return 7000 - Math.min(2000, contiguous * 16 + hay.length - query.length)
  return -1
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

function iconHintList(value) {
  var raw = value && value.iconHints !== undefined ? value.iconHints : value
  var hints = stringList(raw)
  var output = []
  for (var index = 0; index < hints.length; index++) {
    var hint = String(hints[index] || "").trim()
    if (hint && output.indexOf(hint) < 0) output.push(hint)
  }
  return output
}

function objectString(object, property) {
  try {
    return object ? String(object[property] || "").trim() : ""
  } catch (_error) {
    return ""
  }
}

function desktopId(value) {
  var identity = normalized(value)
  return identity.slice(-8) === ".desktop" ? identity.slice(0, -8) : identity
}

function compactIdentity(value) {
  return normalized(value).replace(/[^a-z0-9]+/g, "")
}

function executableName(value) {
  var raw = String(value || "").trim()
  if (!raw) return ""
  var match = raw.match(/^(?:"([^"]+)"|'([^']+)'|([^\s]+))/)
  var executable = match ? (match[1] || match[2] || match[3] || "") : ""
  var slash = executable.lastIndexOf("/")
  if (slash >= 0) executable = executable.slice(slash + 1)
  return desktopId(executable)
}

function iconIdentity(value) {
  var identity = normalized(value).split("?")[0]
  var slash = Math.max(identity.lastIndexOf("/"), identity.lastIndexOf("\\"))
  if (slash >= 0) identity = identity.slice(slash + 1)
  return identity.replace(/\.(?:png|svg|xpm)$/i, "")
}

function normalizeWebHost(value) {
  var host = normalized(value).replace(/^www\./, "")
  return /^[a-z0-9.-]+$/.test(host) && host.indexOf(".") > 0 ? host : ""
}

function normalizeWebPath(value) {
  var path = String(value || "").trim().split(/[?#]/)[0]
  if (!path || path === "/") return ""
  if (path.charAt(0) !== "/") path = "/" + path
  return path.replace(/\/+$/, "")
}

function webIdentityFromHint(value) {
  var raw = String(value || "").trim()
  var initialMarker = raw.indexOf("_/")
  if (initialMarker > 0) {
    var initialHost = normalizeWebHost(raw.slice(0, initialMarker))
    if (initialHost) {
      return {
        host: initialHost,
        path: normalizeWebPath(raw.slice(initialMarker + 1))
      }
    }
  }

  var match = raw.match(
    /^(?:chrome|chromium|google-chrome|brave(?:-browser)?|microsoft-edge|opera|vivaldi(?:-stable)?|helium)-(.+?)-Default$/i)
  if (!match) return null
  var identity = match[1]
  var classMarker = identity.indexOf("__")
  var classHost = normalizeWebHost(classMarker >= 0 ? identity.slice(0, classMarker) : identity)
  if (!classHost) return null
  return {
    host: classHost,
    path: classMarker >= 0
      ? normalizeWebPath(identity.slice(classMarker + 2).replace(/_/g, "/"))
      : ""
  }
}

function webIdentityFromEntry(entry) {
  var match = objectString(entry, "execString").match(
    /https?:\/\/([a-z0-9.-]+)(\/[^\s"'%]*)?/i)
  if (!match) return null
  var host = normalizeWebHost(match[1])
  return host ? { host: host, path: normalizeWebPath(match[2] || "") } : null
}

function entryIdentities(entry) {
  return [
    desktopId(objectString(entry, "id")),
    normalized(objectString(entry, "startupClass")),
    normalized(objectString(entry, "name")),
    executableName(objectString(entry, "execString")),
    iconIdentity(objectString(entry, "icon"))
  ]
}

function mappedGlyph(identities, mapping) {
  for (var index = 0; index < identities.length; index++) {
    if (Object.prototype.hasOwnProperty.call(mapping, identities[index]))
      return mapping[identities[index]]
  }
  return ""
}

function windowAppGlyph(item, entry) {
  if (!item || String(item.kind || "") !== "window") return ""

  var identities = entryIdentities(entry)
  var glyph = mappedGlyph(identities, APP_GLYPHS)
    || mappedGlyph(identities, ENTRY_ONLY_APP_GLYPHS)
  if (glyph) return glyph
  // A resolved web-app entry owns its image identity. Do not fall through to
  // an incidental browser class and replace that app image with Chrome, Brave,
  // or another host-browser glyph.
  if (entry && webIdentityFromEntry(entry)) return ""

  var hints = iconHintList(item)
  var hintIdentities = []
  for (var index = 0; index < hints.length; index++) {
    var identity = desktopId(hints[index])
    if (identity && hintIdentities.indexOf(identity) < 0)
      hintIdentities.push(identity)
  }
  return mappedGlyph(hintIdentities, APP_GLYPHS)
}

function matchDesktopEntry(iconHints, entries) {
  var hints = iconHintList(iconHints)
  var values = entries && typeof entries.length === "number" ? entries : []
  var hintIndex
  var entryIndex

  // Hyprland's class and initialClass normally match either the desktop id or
  // StartupWMClass exactly. Prefer those unambiguous identities.
  for (hintIndex = 0; hintIndex < hints.length; hintIndex++) {
    var hintId = desktopId(hints[hintIndex])
    var hintClass = normalized(hints[hintIndex])
    for (entryIndex = 0; entryIndex < values.length; entryIndex++) {
      var exact = values[entryIndex]
      if (!exact) continue
      if (desktopId(objectString(exact, "id")) === hintId
          || normalized(objectString(exact, "startupClass")) === hintClass)
        return exact
    }
  }

  // Omarchy web-app classes and initial titles carry the host/path that also
  // appears in the desktop entry command. This keeps distinct PWAs on their
  // own icons instead of collapsing all of them to the browser icon.
  var webIdentity = null
  for (hintIndex = 0; hintIndex < hints.length && !webIdentity; hintIndex++)
    webIdentity = webIdentityFromHint(hints[hintIndex])
  if (webIdentity) {
    var best = null
    var bestScore = -1
    for (entryIndex = 0; entryIndex < values.length; entryIndex++) {
      var candidate = values[entryIndex]
      var entryWeb = webIdentityFromEntry(candidate)
      if (!entryWeb || entryWeb.host !== webIdentity.host) continue
      var score = 100
      if (webIdentity.path && entryWeb.path) {
        if (webIdentity.path === entryWeb.path) score += 30
        else if (webIdentity.path.indexOf(entryWeb.path) === 0
            || entryWeb.path.indexOf(webIdentity.path) === 0) score += 20
      }
      if (score > bestScore) {
        best = candidate
        bestScore = score
      }
    }
    if (best) return best
  }

  // A few current applications omit StartupWMClass but keep the same compact
  // identity in their id, executable, name, or icon.
  for (hintIndex = 0; hintIndex < hints.length; hintIndex++) {
    var compactHint = compactIdentity(hints[hintIndex])
    if (!compactHint) continue
    for (entryIndex = 0; entryIndex < values.length; entryIndex++) {
      var identities = entryIdentities(values[entryIndex])
      for (var identity = 0; identity < identities.length; identity++) {
        if (compactIdentity(identities[identity]) === compactHint)
          return values[entryIndex]
      }
    }
  }
  return null
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
    "herdr-agent": "󱚣",
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
  if (kind === "terminal-pane"
           && normalized(item.context) === normalized(provider + " surface")) {
    var context = String(item.context || "")
    var prefix = value.slice(0, Math.max(0, value.length - context.length))
      .replace(/\s*›\s*$/, "").trim()
    value = prefix || provider
  }

  if (isKindMetadata(value)) return provider
  return value || provider
}

function pathLeaf(value) {
  var path = String(value || "").trim()
  if (!path) return ""
  var withoutTrailingSlash = path.replace(/\/+$/, "")
  if (!withoutTrailingSlash) return "/"
  var separator = withoutTrailingSlash.lastIndexOf("/")
  return separator >= 0
    ? withoutTrailingSlash.slice(separator + 1) : withoutTrailingSlash
}

function vitalMetadata(item, breadcrumb, parentTitle) {
  if (!item) return ""
  var kind = String(item.kind || "")
  if (kind === "neovim-buffer") {
    var directoryLeaf = pathLeaf(item.context)
    return directoryLeaf || String(item.provider || "")
  }
  if (kind === "tmux-window" || kind === "tmux-pane") {
    var tmuxParent = String(parentTitle || "").trim()
    return tmuxParent || String(item.provider || "")
  }
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

function relationIndex(items) {
  var source = Array.isArray(items) ? items : []
  var byId = {}
  for (var index = 0; index < source.length; index++) {
    var item = source[index]
    if (item && item.id) byId[String(item.id)] = item
  }
  return byId
}

function breadcrumbFromIndex(item, byId) {
  var values = []
  var seen = {}
  var cursor = item
  var relations = byId || {}
  for (var depth = 0; cursor && cursor.parentId && depth < 12; depth++) {
    var parentId = String(cursor.parentId)
    if (seen[parentId]) break
    seen[parentId] = true
    var parent = relations[parentId]
    if (!parent) break
    values.unshift(String(parent.title || ""))
    cursor = parent
  }
  var context = item && item.context ? String(item.context) : ""
  if (context && (values.length === 0 || values[values.length - 1] !== context))
    values.push(context)
  return values.join("  ›  ")
}

function parentTitleFromIndex(item, byId) {
  if (!item || !item.parentId) return ""
  var parent = (byId || {})[String(item.parentId)]
  return parent ? String(parent.title || "") : ""
}

function metadataForItem(item, byId) {
  return vitalMetadata(item, breadcrumbFromIndex(item, byId),
    parentTitleFromIndex(item, byId))
}

function metadataSortBucket(item, metadata) {
  if (!item || String(item.kind || "") !== "window") return 0
  var badges = badgeList(item.badges)
  for (var index = 0; index < badges.length; index++) {
    if (normalized(badges[index]) === "scratchpad") return 1
  }
  return normalized(metadata) === "scratchpad" ? 1 : 0
}

function naturalCompare(left, right) {
  var a = normalized(left)
  var b = normalized(right)
  if (a === b) return 0
  if (!a) return 1
  if (!b) return -1

  var aParts = a.match(/\d+|\D+/g) || []
  var bParts = b.match(/\d+|\D+/g) || []
  var count = Math.min(aParts.length, bParts.length)
  for (var index = 0; index < count; index++) {
    var aPart = aParts[index]
    var bPart = bParts[index]
    var aNumber = /^\d+$/.test(aPart)
    var bNumber = /^\d+$/.test(bPart)
    if (aNumber && bNumber) {
      var aDigits = aPart.replace(/^0+(?=\d)/, "")
      var bDigits = bPart.replace(/^0+(?=\d)/, "")
      if (aDigits.length !== bDigits.length) return aDigits.length - bDigits.length
      if (aDigits !== bDigits) return aDigits < bDigits ? -1 : 1
      if (aPart.length !== bPart.length) return aPart.length - bPart.length
    } else if (aPart !== bPart) {
      return aPart < bPart ? -1 : 1
    }
  }
  if (aParts.length !== bParts.length) return aParts.length - bParts.length
  return a < b ? -1 : 1
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
    "herdr-agent": 5,
    "herdr-workspace": 6,
    "herdr-tab": 7,
    "herdr-pane": 8,
    "herdr-session": 9,
    "tmux-session": 10,
    "tmux-window": 11,
    "tmux-pane": 12,
    "neovim-buffer": 13
  }
  var value = order[String(kind)]
  return value === undefined ? 1000 : value
}

function rankedEntry(item, query, sourceIndex, relations) {
  var title = normalized(item.title)
  var group = normalized(kindSectionLabel(item.kind))
  var titleHits = 0
  var groupHits = 0
  var quality = 0

  if (query) {
    var titleScore = substringScore(title, query)
    var groupScore = substringScore(group, query)
    if (titleScore >= 0) {
      titleHits = 1
      quality = titleScore
    } else if (groupScore >= 0) {
      groupHits = 1
      quality = groupScore
    } else {
      return null
    }
  }

  var recency = Number(item.recency || 0)
  if (!isFinite(recency)) recency = 0
  // Keep ranking fields separate so even an unusually long query cannot
  // overflow a numeric bucket and invert the documented lexicographic order.
  var metadata = metadataForItem(item, relations)
  return {
    item: item,
    metadata: metadata,
    metadataBucket: metadataSortBucket(item, metadata),
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
  var normalizedQuery = normalized(query)
  var relations = relationIndex(source)
  var ranked = []
  for (var i = 0; i < source.length; i++) {
    var item = source[i]
    if (!item || !item.id || hidden[String(item.id)] === true) continue
    var entry = rankedEntry(item, normalizedQuery, i, relations)
    if (entry) ranked.push(entry)
  }
  ranked.sort(function(a, b) {
    var groupOrder = kindOrder(a.item.kind) - kindOrder(b.item.kind)
    if (groupOrder !== 0) return groupOrder
    if (a.metadataBucket !== b.metadataBucket)
      return a.metadataBucket - b.metadataBucket
    var metadataOrder = naturalCompare(a.metadata, b.metadata)
    if (metadataOrder !== 0) return metadataOrder
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

function groupStartIndex(items, index) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0 || index < 0) return -1
  var bounded = Math.min(source.length - 1, Math.floor(Number(index || 0)))
  var kind = String(source[bounded] && source[bounded].kind || "")
  while (bounded > 0
      && String(source[bounded - 1] && source[bounded - 1].kind || "") === kind)
    bounded--
  return bounded
}

function groupEndIndex(items, index) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0 || index < 0) return -1
  var bounded = Math.min(source.length - 1, Math.floor(Number(index || 0)))
  var kind = String(source[bounded] && source[bounded].kind || "")
  while (bounded + 1 < source.length
      && String(source[bounded + 1] && source[bounded + 1].kind || "") === kind)
    bounded++
  return bounded
}

function isCollapsedKind(collapsedKinds, kind) {
  return collapsedKinds && collapsedKinds[String(kind)] === true
}

function adjacentNavigableIndex(items, index, direction, collapsedKinds) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0) return -1
  var bounded = Math.max(0, Math.min(source.length - 1, Math.floor(Number(index || 0))))
  var step = Number(direction || 0) < 0 ? -1 : (Number(direction || 0) > 0 ? 1 : 0)
  if (step === 0) return bounded

  var currentKind = String(source[bounded] && source[bounded].kind || "")
  var cursor = bounded
  if (isCollapsedKind(collapsedKinds, currentKind)) {
    cursor = step > 0 ? groupEndIndex(source, bounded) : groupStartIndex(source, bounded)
  }
  cursor += step
  if (cursor < 0 || cursor >= source.length) return bounded

  var targetKind = String(source[cursor] && source[cursor].kind || "")
  return isCollapsedKind(collapsedKinds, targetKind)
    ? groupStartIndex(source, cursor) : cursor
}

function boundaryNavigableIndex(items, direction, collapsedKinds) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0) return -1
  if (Number(direction || 0) < 0) return 0
  var last = source.length - 1
  var kind = String(source[last] && source[last].kind || "")
  return isCollapsedKind(collapsedKinds, kind) ? groupStartIndex(source, last) : last
}

function sectionedRowTop(items, index, rowHeight, sectionHeight, collapsedKinds) {
  var source = Array.isArray(items) ? items : []
  if (source.length === 0 || index < 0) return 0
  var bounded = Math.min(source.length - 1, Math.floor(Number(index || 0)))
  var row = Math.max(1, Number(rowHeight || 1))
  var section = Math.max(0, Number(sectionHeight || 0))
  var top = 0
  var previous = ""
  for (var i = 0; i <= bounded; i++) {
    var current = String(source[i] && source[i].kind || "")
    if (i === 0 || current !== previous) top += section
    if (i < bounded && !isCollapsedKind(collapsedKinds, current)) top += row
    previous = current
  }
  return top
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
    && sameStringList(left.iconHints, right.iconHints)
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
