import QtQuick
import Quickshell
import Quickshell.Io
import "EverythingModel.js" as Model

// Shell-wide state and helper lifecycle. Bar instances acquire a lease only
// while their results mode is open. The Python helper therefore exists only
// while at least one panel needs discovery, or an activation is still in
// flight; the shell-only group checklist does not start it.
Item {
  id: root

  property var manifest: null
  property var shell: null
  property string omarchyPath: ""

  property var items: []
  property var providerItems: ({})
  property var activationTokens: ({})
  property var warnings: []
  property var hiddenIds: ({})
  property var leases: ({})
  property int leaseCount: 0
  property int pendingActivations: 0
  property int requestSerial: 0
  property string activeScanId: ""
  property bool helperReady: false
  property bool scanning: false
  property bool intentionalStop: false
  property int crashCount: 0
  property var requestQueue: []

  readonly property string sourceDir: manifest && manifest.__sourceDir
    ? String(manifest.__sourceDir) : ""
  readonly property string helperPath: sourceDir ? sourceDir + "/helper/everything_helper.py" : ""

  function nextRequestId(prefix) {
    requestSerial += 1
    return String(prefix || "request") + "-" + requestSerial
  }

  function acquire(ownerKey) {
    var key = String(ownerKey || "panel")
    if (leases[key] === true) return
    var next = {}
    for (var existing in leases) next[existing] = leases[existing]
    next[key] = true
    leases = next
    leaseCount = Object.keys(next).length
    ensureHelper()
    requestScan(true)
  }

  function release(ownerKey) {
    var key = String(ownerKey || "panel")
    if (leases[key] !== true) return
    var next = {}
    for (var existing in leases) if (existing !== key) next[existing] = leases[existing]
    leases = next
    leaseCount = Object.keys(next).length
    maybeStopTimer.restart()
  }

  function hideItem(id) {
    hiddenIds = Model.withHidden(hiddenIds, id)
  }

  function requestScan(includeGhostty) {
    if (leaseCount <= 0) return
    var requestId = nextRequestId("scan")
    activeScanId = requestId
    scanning = true
    sendRequest({
      version: 1,
      id: requestId,
      type: "scan",
      options: { ghostty: includeGhostty === true }
    })
  }

  function activate(item) {
    if (!item || !item.id) return
    var token = String(activationTokens[String(item.id)] || item.activationToken || "")
    if (!token) return
    pendingActivations += 1
    sendRequest({
      version: 1,
      id: nextRequestId("activate"),
      type: "activate",
      itemId: String(item.id),
      token: token
    })
  }

  function sendRequest(request) {
    ensureHelper()
    if (!helperReady || !helper.running) {
      var next = requestQueue.slice()
      next.push(request)
      requestQueue = next
      return
    }
    helper.write(JSON.stringify(request) + "\n")
  }

  function flushQueue() {
    if (!helperReady || !helper.running) return
    var queued = requestQueue
    requestQueue = []
    for (var i = 0; i < queued.length; i++)
      helper.write(JSON.stringify(queued[i]) + "\n")
  }

  function ensureHelper() {
    if (helper.running || !helperPath) return
    intentionalStop = false
    helper.command = ["python3", helperPath, "--json-lines"]
    helper.running = true
  }

  function stopHelper() {
    if (!helper.running) return
    intentionalStop = true
    if (helperReady) {
      helper.write(JSON.stringify({
        version: 1,
        id: nextRequestId("shutdown"),
        type: "shutdown"
      }) + "\n")
      forceStopTimer.restart()
    } else {
      helper.running = false
    }
  }

  function maybeStop() {
    if (leaseCount === 0 && pendingActivations === 0) stopHelper()
  }

  function mergePartial(provider, rows) {
    if (!provider) return
    var next = {}
    for (var key in providerItems) next[key] = providerItems[key]
    next[String(provider)] = Array.isArray(rows) ? rows : []
    providerItems = next
    publishItems(Model.mergeProviderItems(next))
  }

  function publishItems(rows) {
    var incoming = Array.isArray(rows) ? rows : []
    var tokens = {}
    for (var i = 0; i < incoming.length; i++) {
      var row = incoming[i]
      if (row && row.id && row.activationToken)
        tokens[String(row.id)] = String(row.activationToken)
    }
    activationTokens = tokens
    var reconciled = Model.reconcileItems(items, incoming)
    if (reconciled.changed) items = reconciled.items
  }

  function notifyFailure(message) {
    var text = String(message || "The thing is no longer available")
    if (!omarchyPath) return
    Quickshell.execDetached([
      omarchyPath + "/bin/omarchy-notification-send",
      "--app-name", "Everything",
      "Everything",
      text
    ])
  }

  function appendWarning(message) {
    var value = String(message || "").trim()
    if (!value) return
    var next = warnings.filter(function(entry) { return entry !== value })
    next.push(value)
    warnings = next.slice(Math.max(0, next.length - 8))
  }

  function handleMessage(line) {
    var message
    try {
      message = JSON.parse(String(line || ""))
    } catch (error) {
      appendWarning("Helper returned malformed data")
      return
    }
    if (!message || message.version !== 1 || !message.type) return

    if (message.type === "ready") {
      helperReady = true
      flushQueue()
      return
    }

    if (message.type === "snapshot") {
      var correlated = String(message.requestId || "") === activeScanId
      if (!correlated) return
      if (message.full === true) {
        publishItems(message.items)
        providerItems = message.providers && typeof message.providers === "object"
          ? message.providers : providerItems
        warnings = Array.isArray(message.warnings) ? message.warnings : warnings
        if (String(message.requestId || "") === activeScanId) {
          activeScanId = ""
          scanning = false
          crashCount = 0
        }
      } else {
        mergePartial(message.provider, message.items)
        if (Array.isArray(message.warnings))
          for (var i = 0; i < message.warnings.length; i++) appendWarning(message.warnings[i])
      }
      return
    }

    if (message.type === "activation") {
      pendingActivations = Math.max(0, pendingActivations - 1)
      if (message.ok !== true) notifyFailure(message.message || (message.stale === true
        ? "That thing closed before it could be focused"
        : "Could not focus that thing"))
      maybeStopTimer.restart()
      return
    }

    if (message.type === "error") {
      appendWarning(message.message || "A thing provider failed")
      if (message.requestId && String(message.requestId) === activeScanId && message.final === true)
        scanning = false
    }
  }

  Process {
    id: helper
    stdinEnabled: true

    stdout: SplitParser {
      onRead: function(line) { root.handleMessage(line) }
    }

    stderr: SplitParser {
      onRead: function(line) {
        var value = String(line || "").trim()
        if (value) root.appendWarning(value)
      }
    }

    onExited: function(exitCode, _exitStatus) {
      forceStopTimer.stop()
      var hadPendingActivation = root.pendingActivations > 0
      root.helperReady = false
      root.scanning = false
      root.activeScanId = ""
      if (root.intentionalStop) {
        root.intentionalStop = false
        root.requestQueue = []
        root.pendingActivations = 0
        if (hadPendingActivation)
          root.notifyFailure("Everything stopped before it could focus the thing")
        if (root.leaseCount > 0) restartTimer.restart()
        return
      }
      root.requestQueue = []
      root.pendingActivations = 0
      if (hadPendingActivation)
        root.notifyFailure("Everything stopped before it could focus the thing")
      if (root.leaseCount > 0 || root.pendingActivations > 0) {
        root.crashCount += 1
        root.appendWarning("Everything helper stopped unexpectedly (exit " + exitCode + ")")
        if (root.crashCount <= 3) restartTimer.restart()
      }
    }
  }

  Timer {
    id: pollTimer
    interval: 2000
    repeat: true
    running: root.leaseCount > 0 && root.helperReady
    onTriggered: if (!root.scanning) root.requestScan(false)
  }

  Timer {
    id: maybeStopTimer
    interval: 175
    repeat: false
    onTriggered: root.maybeStop()
  }

  Timer {
    id: forceStopTimer
    interval: 1000
    repeat: false
    onTriggered: if (helper.running) helper.running = false
  }

  Timer {
    id: restartTimer
    interval: 750
    repeat: false
    onTriggered: {
      root.ensureHelper()
      if (root.leaseCount > 0) root.requestScan(true)
    }
  }

  Component.onDestruction: {
    if (helper.running) {
      intentionalStop = true
      if (helperReady) helper.write(JSON.stringify({ version: 1, id: "destruction", type: "shutdown" }) + "\n")
      helper.running = false
    }
    if (agentHelper.running) {
      agentIntentionalStop = true
      if (agentHelperReady)
        agentHelper.write(JSON.stringify({ version: 1, id: "destruction", type: "shutdown" }) + "\n")
      agentHelper.running = false
    }
  }

  // --- Agent subsystem (opt-in, second process) ----------------------------
  // A second, fully independent helper and lease, deliberately not sharing
  // state or a process with the discovery helper above: an agent run is
  // long-running, streamed, cancellable, and networked, none of which apply
  // to the sub-second local scans above it. See docs/agent.md. Nothing here
  // starts unless a bar instance opens agent mode (see Everything.qml's
  // agentModeOpen), which itself requires the user to have opted in.

  property var agentCapabilities: ({})
  property var agentLeases: ({})
  property int agentLeaseCount: 0
  property bool agentHelperReady: false
  property bool agentIntentionalStop: false
  property int agentCrashCount: 0
  property int agentRequestSerial: 0
  property var agentRequestQueue: []
  // Keyed by requestId so concurrent runs (e.g. from more than one monitor)
  // do not clobber each other's streamed turns.
  property var agentTurnsByRequest: ({})
  property var agentFinalByRequest: ({})
  property var agentConversations: []
  // Keyed by conversationId. Only one Get is expected in flight at a time in
  // practice (a single history browser), so this stays a flat map rather
  // than also being keyed by requestId.
  property var agentConversationTurns: ({})

  readonly property string agentHelperPath: sourceDir
    ? sourceDir + "/helper/everything_agent_helper.py" : ""

  function agentNextRequestId(prefix) {
    agentRequestSerial += 1
    return "agent-" + String(prefix || "request") + "-" + agentRequestSerial
  }

  function agentAcquire(ownerKey) {
    var key = String(ownerKey || "panel")
    if (agentLeases[key] === true) return
    var next = {}
    for (var existing in agentLeases) next[existing] = agentLeases[existing]
    next[key] = true
    agentLeases = next
    agentLeaseCount = Object.keys(next).length
    agentEnsureHelper()
  }

  function agentRelease(ownerKey) {
    var key = String(ownerKey || "panel")
    if (agentLeases[key] !== true) return
    var next = {}
    for (var existing in agentLeases) if (existing !== key) next[existing] = agentLeases[existing]
    agentLeases = next
    agentLeaseCount = Object.keys(next).length
    agentMaybeStopTimer.restart()
  }

  function agentEnsureHelper() {
    if (agentHelper.running || !agentHelperPath) return
    agentIntentionalStop = false
    agentHelper.command = ["python3", agentHelperPath, "--json-lines"]
    agentHelper.running = true
  }

  function agentStopHelper() {
    if (!agentHelper.running) return
    agentIntentionalStop = true
    if (agentHelperReady) {
      agentHelper.write(JSON.stringify({
        version: 1, id: agentNextRequestId("shutdown"), type: "shutdown"
      }) + "\n")
      agentForceStopTimer.restart()
    } else {
      agentHelper.running = false
    }
  }

  function agentMaybeStop() {
    if (agentLeaseCount === 0) agentStopHelper()
  }

  function agentSendRequest(request) {
    agentEnsureHelper()
    if (!agentHelperReady || !agentHelper.running) {
      var next = agentRequestQueue.slice()
      next.push(request)
      agentRequestQueue = next
      return request.id
    }
    agentHelper.write(JSON.stringify(request) + "\n")
    return request.id
  }

  function agentFlushQueue() {
    if (!agentHelperReady || !agentHelper.running) return
    var queued = agentRequestQueue
    agentRequestQueue = []
    for (var i = 0; i < queued.length; i++) agentHelper.write(JSON.stringify(queued[i]) + "\n")
  }

  function agentRun(options) {
    var opts = options || {}
    var requestId = agentNextRequestId("run")
    var turnsNext = {}
    for (var tkey in agentTurnsByRequest) turnsNext[tkey] = agentTurnsByRequest[tkey]
    turnsNext[requestId] = []
    agentTurnsByRequest = turnsNext
    var finalNext = {}
    for (var fkey in agentFinalByRequest) if (fkey !== requestId) finalNext[fkey] = agentFinalByRequest[fkey]
    agentFinalByRequest = finalNext
    agentSendRequest({
      version: 1,
      id: requestId,
      type: "agentRun",
      agent: String(opts.agent || ""),
      mode: String(opts.mode || "run"),
      prompt: String(opts.prompt || ""),
      allowedDirs: Array.isArray(opts.allowedDirs) ? opts.allowedDirs : [],
      resumeSessionId: String(opts.resumeSessionId || ""),
      conversationId: String(opts.conversationId || "")
    })
    return requestId
  }

  function agentCancel(requestId) {
    if (!requestId) return
    agentSendRequest({
      version: 1, id: agentNextRequestId("cancel"), type: "agentCancel", requestId: String(requestId)
    })
  }

  function agentRequestConversationList() {
    agentSendRequest({ version: 1, id: agentNextRequestId("list"), type: "agentConversationList" })
  }

  function agentRequestConversationGet(conversationId) {
    if (!conversationId) return
    agentSendRequest({
      version: 1, id: agentNextRequestId("get"), type: "agentConversationGet",
      conversationId: String(conversationId)
    })
  }

  function agentRequestConversationDelete(conversationId) {
    if (!conversationId) return
    agentSendRequest({
      version: 1, id: agentNextRequestId("delete"), type: "agentConversationDelete",
      conversationId: String(conversationId)
    })
  }

  function agentHandleMessage(line) {
    var message
    try {
      message = JSON.parse(String(line || ""))
    } catch (error) {
      return
    }
    if (!message || message.version !== 1 || !message.type) return

    if (message.type === "ready") {
      agentHelperReady = true
      agentCapabilities = (message.capabilities && message.capabilities.agents) || {}
      agentFlushQueue()
      return
    }

    if (message.type === "agentTurn") {
      var requestId = String(message.requestId || "")
      if (!requestId) return
      if (message.turn) {
        var turnsUpdate = {}
        for (var tkey2 in agentTurnsByRequest) turnsUpdate[tkey2] = agentTurnsByRequest[tkey2]
        var existingTurns = Array.isArray(turnsUpdate[requestId]) ? turnsUpdate[requestId] : []
        turnsUpdate[requestId] = existingTurns.concat([message.turn])
        agentTurnsByRequest = turnsUpdate
      }
      if (message.final === true) {
        var finalUpdate = {}
        for (var fkey2 in agentFinalByRequest) finalUpdate[fkey2] = agentFinalByRequest[fkey2]
        finalUpdate[requestId] = {
          ok: message.ok === true,
          message: String(message.message || ""),
          cancelled: message.cancelled === true,
          conversationId: String(message.conversationId || "")
        }
        agentFinalByRequest = finalUpdate
      }
      return
    }

    if (message.type === "agentRunFailed") {
      var failedId = String(message.requestId || "")
      if (!failedId) return
      var failedUpdate = {}
      for (var fkey3 in agentFinalByRequest) failedUpdate[fkey3] = agentFinalByRequest[fkey3]
      failedUpdate[failedId] = {
        ok: false,
        message: String(message.message || "That agent command failed"),
        cancelled: false,
        conversationId: String(message.conversationId || "")
      }
      agentFinalByRequest = failedUpdate
      return
    }

    if (message.type === "agentConversationList") {
      agentConversations = Array.isArray(message.conversations) ? message.conversations : []
      return
    }

    if (message.type === "agentConversationGet") {
      var gotId = String(message.conversationId || "")
      if (!gotId) return
      var getUpdate = {}
      for (var gkey in agentConversationTurns) getUpdate[gkey] = agentConversationTurns[gkey]
      getUpdate[gotId] = Array.isArray(message.turns) ? message.turns : []
      agentConversationTurns = getUpdate
      return
    }

    if (message.type === "agentConversationDelete") {
      var deletedId = String(message.conversationId || "")
      if (deletedId && message.ok === true) {
        agentConversations = agentConversations.filter(function(entry) {
          return entry.id !== deletedId
        })
      }
      return
    }
    // "error" is protocol-level and nonfatal by convention (malformed
    // request, unknown conversation id); nothing currently needs to render
    // it distinctly from being quietly ignored.
  }

  Process {
    id: agentHelper
    stdinEnabled: true

    stdout: SplitParser {
      onRead: function(line) { root.agentHandleMessage(line) }
    }

    stderr: SplitParser {
      onRead: function(_line) { /* diagnostic only; agent failures are protocol messages */ }
    }

    onExited: function(exitCode, _exitStatus) {
      agentForceStopTimer.stop()
      root.agentHelperReady = false
      if (root.agentIntentionalStop) {
        root.agentIntentionalStop = false
        root.agentRequestQueue = []
        return
      }
      root.agentRequestQueue = []
      if (root.agentLeaseCount > 0) {
        root.agentCrashCount += 1
        if (root.agentCrashCount <= 3) agentRestartTimer.restart()
      }
    }
  }

  Timer {
    id: agentMaybeStopTimer
    interval: 175
    repeat: false
    onTriggered: root.agentMaybeStop()
  }

  Timer {
    id: agentForceStopTimer
    interval: 1000
    repeat: false
    onTriggered: if (agentHelper.running) agentHelper.running = false
  }

  Timer {
    id: agentRestartTimer
    interval: 750
    repeat: false
    onTriggered: root.agentEnsureHelper()
  }
}
