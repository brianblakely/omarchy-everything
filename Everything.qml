pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import qs.Commons
import qs.Ui
import "EverythingModel.js" as Model

Panel {
  id: root
  moduleName: "b.everything"
  ipcTarget: "b.everything"
  manageIpc: false

  readonly property var everythingService: root.bar && root.bar.shell
    && typeof root.bar.shell.serviceFor === "function"
    ? root.bar.shell.serviceFor("b.everything") : null
  readonly property var appLibrary: root.bar && root.bar.shell
    && root.bar.shell.appLibrary !== undefined ? root.bar.shell.appLibrary : null
  readonly property var desktopEntries: DesktopEntries.applications.values || []
  readonly property var itemRelations: Model.relationIndex(
    everythingService ? everythingService.items : [])
  readonly property var supportedGroups: Model.supportedGroupCatalog()
  readonly property var disabledKinds: Model.normalizeDisabledKinds(
    root.setting("disabledKinds", []))
  readonly property color foreground: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dimForeground: Qt.darker(foreground, 1.55)
  readonly property real rowHeight: Style.font.body * 1.5
  readonly property int sectionHeight: Style.space(24)
  readonly property int groupChecklistRowHeight: Style.space(36)
  readonly property string resultsMode: "results"
  readonly property string groupsMode: "groups"
  readonly property bool resultsModeOpen: root.opened && popupMode === resultsMode
  property var rankedItems: []
  property var collapsedKinds: ({})
  property string popupMode: resultsMode
  property string selectedItemUuid: ""
  property real savedSelectedOffset: 0
  property bool savedListFocus: false
  property bool savedKeyCatcherFocus: false
  property bool savedSearchFocus: false
  property bool pendingSelectionSurvived: false
  property bool resultUpdateInProgress: false
  property bool rankUpdateScheduled: false
  property int resultUpdateSerial: 0
  property bool pointerCursorActive: false
  // A widget may acquire its service lease before its QsWindow/screen exists.
  // Keep the owner key stable and instance-local so an early "unknown" screen
  // can never collide with another monitor or leak a lease after reparenting.
  readonly property string instanceKey: "everything:" + Date.now() + ":"
    + Math.random().toString(36).slice(2)

  function disarmPointer() {
    pointerCursorActive = false
    pointerMoveGate.reset()
  }

  function kindDisabled(kind) {
    return disabledKinds.indexOf(String(kind || "")) >= 0
  }

  function persistDisabledKinds(value) {
    var nextKinds = Model.normalizeDisabledKinds(value)
    if (Model.sameStringList(disabledKinds, nextKinds)) return

    var entry = { id: root.moduleName }
    for (var key in root.settings) if (key !== "id") entry[key] = root.settings[key]
    entry.disabledKinds = nextKinds

    // Update this monitor immediately. The shell write then injects the same
    // settings object into every live monitor instance without rebuilding it.
    root.settings = entry
    if (root.bar && root.bar.shell
        && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  function setKindEnabled(kind, enabled) {
    var value = String(kind || "")
    var shouldDisable = enabled !== true
    var catalogKind = false
    for (var index = 0; index < supportedGroups.length; index++) {
      if (supportedGroups[index].kind === value) {
        catalogKind = true
        break
      }
    }
    if (!catalogKind || kindDisabled(value) === shouldDisable) return

    var nextKinds = disabledKinds.slice()
    var disabledIndex = nextKinds.indexOf(value)
    if (!shouldDisable && disabledIndex >= 0) nextKinds.splice(disabledIndex, 1)
    else if (shouldDisable && disabledIndex < 0) nextKinds.push(value)
    persistDisabledKinds(nextKinds)
  }

  function toggleKindVisibility(kind) {
    setKindEnabled(kind, kindDisabled(kind))
  }

  function resetGroupChecklist() {
    groupList.currentIndex = supportedGroups.length > 0 ? 0 : -1
    groupList.contentY = groupList.originY
    Qt.callLater(function() {
      if (root.opened && root.popupMode === root.groupsMode)
        groupList.forceActiveFocus()
    })
  }

  function enterPopupMode(mode) {
    var wanted = mode === groupsMode ? groupsMode : resultsMode
    if (popupMode === wanted) return
    popupMode = wanted
    if (!root.opened) return

    if (wanted === groupsMode) {
      resetGroupChecklist()
    } else {
      searchField.text = ""
      if (appLibrary && typeof appLibrary.refreshIcons === "function")
        appLibrary.refreshIcons()
      rebuildRankedItems()
      resetResultsForOpen()
    }
  }

  function togglePopupMode(mode) {
    var wanted = mode === groupsMode ? groupsMode : resultsMode
    if (root.opened && popupMode === wanted) {
      root.close()
      return
    }
    if (root.opened) {
      enterPopupMode(wanted)
      return
    }
    popupMode = wanted
    root.open()
  }

  function setGroupChecklistIndex(index) {
    if (supportedGroups.length <= 0) {
      groupList.currentIndex = -1
      return
    }
    var bounded = Math.max(0, Math.min(supportedGroups.length - 1,
      Math.floor(Number(index || 0))))
    groupList.currentIndex = bounded
    groupList.positionViewAtIndex(bounded, ListView.Contain)
  }

  function moveGroupChecklist(delta) {
    if (supportedGroups.length <= 0 || Number(delta || 0) === 0) return
    var current = groupList.currentIndex < 0 ? 0 : groupList.currentIndex
    setGroupChecklistIndex(current + (delta < 0 ? -1 : 1))
    groupList.forceActiveFocus()
  }

  function toggleCurrentGroupVisibility() {
    var index = groupList.currentIndex
    if (index < 0 || index >= supportedGroups.length) return
    toggleKindVisibility(supportedGroups[index].kind)
  }

  function selectFromPointer(index, item, mouse) {
    if (!pointerMoveGate.moved(item, mouse)) return
    setCurrentIndex(index, false)
    pointerCursorActive = true
  }

  function focusSearch() {
    disarmPointer()
    searchField.forceActiveFocus()
  }

  function groupCollapsed(kind) {
    return collapsedKinds && collapsedKinds[String(kind || "")] === true
  }

  function currentGroupKind() {
    var index = resultList.currentIndex
    if (index < 0 || index >= rankedItems.length) return ""
    return String(rankedItems[index] && rankedItems[index].kind || "")
  }

  function selectionIsVisibleRow(index) {
    return index >= 0 && index < rankedItems.length
      && !groupCollapsed(rankedItems[index].kind)
  }

  function focusList(index) {
    if (resultList.count <= 0) return
    disarmPointer()
    setCurrentIndex(index === undefined ? 0 : index, true)
    if (resultList.currentIndex === 0)
      resultList.contentY = resultList.originY
    resultList.forceActiveFocus()
  }

  function setCurrentIndex(index, reveal) {
    if (resultList.count <= 0 || rankedItems.length <= 0) {
      resultList.currentIndex = -1
      selectedItemUuid = ""
      return
    }
    var bounded = Math.max(0, Math.min(Number(index || 0), resultList.count - 1))
    resultList.currentIndex = bounded
    selectedItemUuid = Model.itemUuid(rankedItems[bounded])
    if (reveal === true) revealSelection(bounded, false)
  }

  function moveSelection(delta) {
    if (resultList.count <= 0 || Number(delta || 0) === 0) return
    var direction = delta < 0 ? -1 : 1
    var steps = Math.max(1, Math.floor(Math.abs(Number(delta))))
    var candidate = resultList.currentIndex
    if (candidate < 0)
      candidate = Model.boundaryNavigableIndex(rankedItems, direction, collapsedKinds)
    for (var step = 0; step < steps; step++) {
      var next = Model.adjacentNavigableIndex(
        rankedItems, candidate, direction, collapsedKinds)
      if (next === candidate) break
      candidate = next
    }
    focusList(candidate)
  }

  function focusBoundary(direction) {
    focusList(Model.boundaryNavigableIndex(rankedItems, direction, collapsedKinds))
  }

  function setGroupCollapsed(kind, collapsed) {
    var value = String(kind || "")
    var wanted = collapsed === true
    if (!value || groupCollapsed(value) === wanted) return

    var nextKinds = {}
    for (var key in collapsedKinds) {
      if (collapsedKinds[key] === true) nextKinds[key] = true
    }
    if (wanted) nextKinds[value] = true
    else delete nextKinds[value]
    collapsedKinds = nextKinds
    disarmPointer()
    var index = resultList.currentIndex
    if (typeof resultList.forceLayout === "function") resultList.forceLayout()
    revealSelection(index, wanted)
  }

  function collapseCurrentGroup() {
    var kind = currentGroupKind()
    if (kind) setGroupCollapsed(kind, true)
  }

  function expandCurrentGroup() {
    var kind = currentGroupKind()
    if (kind) setGroupCollapsed(kind, false)
  }

  function toggleGroupFromHeading(kind) {
    var index = -1
    for (var itemIndex = 0; itemIndex < rankedItems.length; itemIndex++) {
      if (String(rankedItems[itemIndex].kind || "") === String(kind || "")) {
        index = itemIndex
        break
      }
    }
    if (index < 0) return
    setCurrentIndex(index, false)
    resultList.forceActiveFocus()
    setGroupCollapsed(kind, !groupCollapsed(kind))
  }

  function activateAt(index) {
    if (index < 0 || index >= rankedItems.length || !everythingService
        || !selectionIsVisibleRow(index)) return
    var target = rankedItems[index]
    // Release the layer-shell keyboard grab before asking another surface to
    // accept focus. Service.qml keeps the helper alive for the pending action.
    root.close()
    Qt.callLater(function() { everythingService.activate(target) })
  }

  function activateCurrent() {
    if (groupCollapsed(currentGroupKind())) {
      expandCurrentGroup()
      return
    }
    activateAt(resultList.currentIndex)
  }

  function hideAt(index) {
    if (index < 0 || index >= rankedItems.length || !everythingService
        || !selectionIsVisibleRow(index)) return
    everythingService.hideItem(rankedItems[index].id)
  }

  function handleEscape() {
    if (searchField.text.length > 0) {
      searchField.text = ""
      focusSearch()
    } else {
      root.close()
    }
  }

  function rowTopAt(index) {
    return Model.sectionedRowTop(
      rankedItems, index, rowHeight, sectionHeight, collapsedKinds)
  }

  function rowVisualTop(index) {
    if (index >= 0 && typeof resultList.itemAtIndex === "function") {
      var delegateItem = resultList.itemAtIndex(index)
      if (delegateItem) return Number(delegateItem.y)
    }
    return resultList.originY + rowTopAt(index)
  }

  function selectionVisualTop(index) {
    var top = rowVisualTop(index)
    if (index >= 0 && index < rankedItems.length
        && groupCollapsed(rankedItems[index].kind)) top -= sectionHeight
    return top
  }

  function revealSelection(index, alignTop) {
    if (index < 0 || index >= rankedItems.length) return
    if (typeof resultList.forceLayout === "function") resultList.forceLayout()
    var top = selectionVisualTop(index)
    var extent = groupCollapsed(rankedItems[index].kind) ? sectionHeight : rowHeight
    var wanted = resultList.contentY
    if (alignTop === true || top < wanted) wanted = top
    else if (top + extent > wanted + resultList.height)
      wanted = top + extent - resultList.height
    resultList.contentY = Model.clampContentY(
      wanted, resultList.originY, resultList.contentHeight, resultList.height)
  }

  function pageDelta(direction) {
    if (resultList.count <= 0 || direction === 0) return 0
    var current = Math.max(0, Math.min(resultList.count - 1, resultList.currentIndex))
    var target = selectionVisualTop(current)
      + (direction > 0 ? resultList.height : -resultList.height)
    var candidate = current
    var steps = 0
    while (true) {
      var next = Model.adjacentNavigableIndex(
        rankedItems, candidate, direction, collapsedKinds)
      if (next === candidate) break
      var nextTop = selectionVisualTop(next)
      if ((direction > 0 && nextTop > target)
          || (direction < 0 && nextTop < target)) break
      candidate = next
      steps++
    }
    if (steps === 0 && Model.adjacentNavigableIndex(
        rankedItems, candidate, direction, collapsedKinds) !== candidate) steps = 1
    return direction > 0 ? steps : -steps
  }

  function rememberFocusState() {
    savedKeyCatcherFocus = keyCatcher.activeFocus
    savedListFocus = resultList.activeFocus || savedKeyCatcherFocus
    savedSearchFocus = searchField.activeFocus
  }

  function rememberResultState() {
    rememberFocusState()
    var current = resultList.currentIndex
    if (current >= 0 && current < rankedItems.length) {
      selectedItemUuid = Model.itemUuid(rankedItems[current])
    }
    savedSelectedOffset = current >= 0
      ? resultList.contentY - selectionVisualTop(current) : 0
  }

  function applyOpenResultReset() {
    var index = rankedItems.length > 0 ? 0 : -1
    resultList.currentIndex = index
    selectedItemUuid = index >= 0 ? Model.itemUuid(rankedItems[index]) : ""
    savedSelectedOffset = 0
    resultList.contentY = resultList.originY
  }

  function resetResultsForOpen() {
    // A restore queued during the previous opening must never override the
    // fresh-open state after the panel becomes visible again.
    disarmPointer()
    resultUpdateSerial += 1
    collapsedKinds = ({})
    resultUpdateInProgress = false
    pendingSelectionSurvived = false
    applyOpenResultReset()
    Qt.callLater(function() {
      if (!root.opened) return
      if (typeof resultList.forceLayout === "function") resultList.forceLayout()
      root.applyOpenResultReset()
      searchField.forceActiveFocus()
    })
  }

  function scheduleRankedItems() {
    if (rankUpdateScheduled) return
    rankUpdateScheduled = true
    Qt.callLater(function() {
      root.rankUpdateScheduled = false
      root.rebuildRankedItems()
    })
  }

  function rebuildRankedItems() {
    var nextItems = Model.rank(
      everythingService ? everythingService.items : [],
      searchField.text,
      everythingService ? everythingService.hiddenIds : {},
      disabledKinds)
    if (Model.sameRankedItems(rankedItems, nextItems)) return
    if (!resultUpdateInProgress) rememberResultState()
    disarmPointer()
    resultUpdateInProgress = true
    rankedItems = nextItems
    resultUpdateSerial += 1
    var serial = resultUpdateSerial
    Qt.callLater(function() {
      if (serial === root.resultUpdateSerial) root.restoreResultSelection(serial)
    })
  }

  function restoreResultSelection(serial) {
    if (serial !== resultUpdateSerial) return
    if (typeof resultList.forceLayout === "function") resultList.forceLayout()
    pendingSelectionSurvived = Model.indexOfUuid(rankedItems, selectedItemUuid) >= 0
    var index = Model.indexAfterRefresh(rankedItems, selectedItemUuid)
    resultList.currentIndex = index
    selectedItemUuid = index >= 0 ? Model.itemUuid(rankedItems[index]) : ""
    if (!pendingSelectionSurvived) resultList.contentY = resultList.originY
    Qt.callLater(function() {
      if (serial === root.resultUpdateSerial) root.finishResultRestore(serial)
    })
  }

  function finishResultRestore(serial) {
    if (serial !== resultUpdateSerial) return
    if (typeof resultList.forceLayout === "function") resultList.forceLayout()
    var index = Model.indexOfUuid(rankedItems, selectedItemUuid)
    if (index < 0) index = rankedItems.length > 0 ? 0 : -1
    resultList.currentIndex = index
    selectedItemUuid = index >= 0 ? Model.itemUuid(rankedItems[index]) : ""

    if (pendingSelectionSurvived && index >= 0
        && resultList.contentHeight > resultList.height + 0.5) {
      resultList.contentY = Model.clampContentY(selectionVisualTop(index) + savedSelectedOffset,
        resultList.originY, resultList.contentHeight, resultList.height)
    } else if (!pendingSelectionSurvived) {
      resultList.contentY = resultList.originY
    }

    if (savedKeyCatcherFocus) keyCatcher.forceActiveFocus()
    else if (savedListFocus && index >= 0) resultList.forceActiveFocus()
    else if (savedSearchFocus) searchField.forceActiveFocus()
    resultUpdateInProgress = false
  }

  function breadcrumb(item) {
    return Model.breadcrumbFromIndex(item, itemRelations)
  }

  function usableIconSource(value) {
    var source = String(value || "")
    var generic = String(Quickshell.iconPath("application-x-executable", true) || "")
    return source && source !== generic ? source : ""
  }

  function resolveWindowDesktopEntry(item) {
    if (!item || String(item.kind || "") !== "window") return ""
    var hints = Model.iconHintList(item)
    if (hints.length === 0) return null

    var entry = Model.matchDesktopEntry(hints, desktopEntries)
    if (!entry) {
      for (var lookup = 0; lookup < hints.length && !entry; lookup++) {
        try { entry = DesktopEntries.heuristicLookup(hints[lookup]) } catch (_error) { }
      }
    }
    return entry || null
  }

  function windowIconSource(item, resolvedEntry) {
    if (!item || String(item.kind || "") !== "window") return ""
    var hints = Model.iconHintList(item)
    if (hints.length === 0) return ""

    var entry = resolvedEntry || resolveWindowDesktopEntry(item)
    if (entry && entry.icon) {
      if (appLibrary && typeof appLibrary.iconSource === "function") {
        var librarySource = usableIconSource(appLibrary.iconSource(entry.icon))
        if (librarySource) return librarySource
      }
      var entrySource = usableIconSource(Quickshell.iconPath(String(entry.icon), true))
      if (entrySource) return entrySource
    }

    // A direct icon name from Hyprland can be useful even when it has no
    // corresponding desktop entry. Unknown names remain a local glyph
    // fallback; they are never treated as arbitrary URLs.
    for (var hint = 0; hint < hints.length; hint++) {
      var directSource = usableIconSource(Quickshell.iconPath(hints[hint], true))
      if (directSource) return directSource
    }
    return ""
  }

  function handleSupplementalListKey(event) {
    var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
    var action = ""
    if (ctrl && event.key === Qt.Key_N) action = "next"
    else if (ctrl && event.key === Qt.Key_P) action = "previous"
    else if (event.key === Qt.Key_Home) action = "first"
    else if (event.key === Qt.Key_End) action = "last"
    else if (event.key === Qt.Key_PageDown || (ctrl && event.key === Qt.Key_D)) action = "page-next"
    else if (event.key === Qt.Key_PageUp || (ctrl && event.key === Qt.Key_U)) action = "page-previous"
    else if (event.key === Qt.Key_Backspace || event.key === Qt.Key_Delete) action = "hide"

    if (!action) return
    event.accepted = true
    if (action === "next") moveSelection(1)
    else if (action === "previous") moveSelection(-1)
    else if (action === "first") focusBoundary(-1)
    else if (action === "last") focusBoundary(1)
    else if (action === "page-next") moveSelection(pageDelta(1))
    else if (action === "page-previous") moveSelection(pageDelta(-1))
    else if (action === "hide") hideAt(resultList.currentIndex)
  }

  onOpenedChanged: {
    if (root.opened) {
      if (popupMode === groupsMode) {
        resetGroupChecklist()
      } else {
        searchField.text = ""
        if (appLibrary && typeof appLibrary.refreshIcons === "function")
          appLibrary.refreshIcons()
        rebuildRankedItems()
        resetResultsForOpen()
      }
    } else {
      popupMode = resultsMode
    }
  }

  onResultsModeOpenChanged: {
    if (!everythingService) return
    if (resultsModeOpen) everythingService.acquire(instanceKey)
    else everythingService.release(instanceKey)
  }

  onEverythingServiceChanged: {
    if (resultsModeOpen && everythingService) everythingService.acquire(instanceKey)
    scheduleRankedItems()
  }
  onDisabledKindsChanged: scheduleRankedItems()
  Component.onCompleted: scheduleRankedItems()
  Component.onDestruction: if (everythingService) everythingService.release(instanceKey)

  Connections {
    target: root.everythingService
    ignoreUnknownSignals: true
    function onItemsChanged() { root.scheduleRankedItems() }
    function onHiddenIdsChanged() { root.scheduleRankedItems() }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  PointerMoveGate {
    id: pointerMoveGate
    referenceItem: resultList
  }

  BarIconButton {
    id: button
    objectName: "everything-bar-button"
    anchors.fill: parent
    bar: root.bar
    text: "\uf078"
    useActiveColor: false
    iconComponent: Component {
      Item {
        id: chevronFrame
        objectName: "everything-bar-chevron"
        // QML pixel-aligns the even optical canvas inside the odd bar slot.
        // Counter that half-pixel shift without moving the slot or hit target.
        readonly property real buttonCenterX: button.width / 2
          - Math.round((button.width - width) / 2)
        readonly property real centerErrorX: chevron.x
          + chevron.paintedCenterX - buttonCenterX

        OpticalGlyph {
          id: chevron
          width: parent.width
          height: parent.height
          x: chevronFrame.buttonCenterX - paintedCenterX
          text: button.text
          fontFamily: button.fontFamily
          fontSize: button.fontSize
          color: button.active && button.useActiveColor
            ? button.activeColor : button.foreground
        }
      }
    }
    active: root.opened
    tooltipText: "Everything"
    activeFocusOnTab: true
    Keys.onReturnPressed: root.togglePopupMode(root.resultsMode)
    Keys.onEnterPressed: root.togglePopupMode(root.resultsMode)
    Keys.onSpacePressed: root.togglePopupMode(root.resultsMode)
    onPressed: function(buttonCode) {
      root.togglePopupMode(buttonCode === Qt.RightButton
        ? root.groupsMode : root.resultsMode)
    }

    Accessible.role: Accessible.Button
    Accessible.name: "Open Everything"
    Accessible.description: "Search things with the primary action; choose visible groups with right-click"
    Accessible.focusable: true
    Accessible.focused: activeFocus
    Accessible.onPressAction: root.togglePopupMode(root.resultsMode)

    Rectangle {
      anchors.fill: parent
      anchors.margins: Style.space(2)
      visible: button.activeFocus
      color: "transparent"
      radius: Style.cornerRadius
      border.width: Math.max(1, Style.normalBorderWidth)
      border.color: Color.accent
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: root.popupMode === root.groupsMode ? groupList : searchField
    contentWidth: popup.fittedContentWidth(Style.space(620))
    contentHeight: popup.cappedContentHeight(Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      objectName: "everything-key-catcher"
      anchors.fill: parent
      blocked: root.popupMode === root.resultsMode && searchField.activeFocus

      onMoveRequested: function(dx, dy) {
        if (root.popupMode === root.groupsMode) {
          if (dy !== 0) root.moveGroupChecklist(dy)
        } else if (dy !== 0) root.moveSelection(dy)
        else if (dx < 0) root.collapseCurrentGroup()
        else if (dx > 0) root.expandCurrentGroup()
      }
      onActivateRequested: {
        if (root.popupMode === root.groupsMode) root.toggleCurrentGroupVisibility()
        else root.activateCurrent()
      }
      onCloseRequested: {
        if (root.popupMode === root.groupsMode) root.close()
        else root.handleEscape()
      }
      onDeleteRequested: if (root.popupMode === root.resultsMode)
        root.hideAt(resultList.currentIndex)
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (root.popupMode !== root.resultsMode) return
        if (text === "/") root.focusSearch()
        else if (text === "g") root.focusBoundary(-1)
        else if (text === "G") root.focusBoundary(1)
      }

      Item {
        id: content
        anchors.fill: parent
        Accessible.role: Accessible.Pane
        Accessible.name: root.popupMode === root.groupsMode
          ? "Everything group visibility panel" : "Everything search and switch panel"

      TextField {
        id: searchField
        objectName: "everything-search"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        visible: root.popupMode === root.resultsMode
        enabled: visible
        placeholderText: "Search everything…"
        foreground: root.foreground
        activeFocusOnTab: true
        Accessible.role: Accessible.EditableText
        Accessible.name: "Search things"
        Accessible.description: "Type a contiguous title or group-name substring"
        Accessible.editable: true
        Accessible.focusable: true
        Accessible.focused: activeFocus
        onActiveFocusChanged: if (activeFocus) root.disarmPointer()
        onTextChanged: root.scheduleRankedItems()

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Down || (event.key === Qt.Key_Tab
              && (event.modifiers & Qt.ShiftModifier) === 0)) {
            event.accepted = true
            root.focusBoundary(-1)
          } else if (event.key === Qt.Key_Escape) {
            event.accepted = true
            root.handleEscape()
          }
        }
      }

      ListView {
        id: resultList
        objectName: "everything-results"
        anchors.top: searchField.bottom
        anchors.topMargin: Style.space(4)
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(6)
        visible: root.popupMode === root.resultsMode
        enabled: visible
        clip: true
        model: root.rankedItems
        currentIndex: -1
        activeFocusOnTab: count > 0
        boundsBehavior: Flickable.StopAtBounds
        keyNavigationEnabled: false
        highlightMoveDuration: 80
        Accessible.role: Accessible.List
        Accessible.name: "Ranked thing list"
        Accessible.description: "Use Up and Down to select; Left and Right collapse or expand the current group"
        Accessible.focusable: count > 0
        Accessible.focused: activeFocus

        section.property: "kind"
        section.criteria: ViewSection.FullString
        section.delegate: Item {
          id: sectionHeading
          required property string section
          objectName: "everything-section-" + section
          width: ListView.view.width
          height: root.sectionHeight
          readonly property bool collapsed: root.groupCollapsed(section)
          readonly property bool highlighted: collapsed
            && (resultList.activeFocus || keyCatcher.activeFocus)
            && root.currentGroupKind() === section

          Accessible.role: Accessible.Heading
          Accessible.name: Model.kindSectionLabel(sectionHeading.section)
            + (collapsed ? ", collapsed" : ", expanded")
          Accessible.focusable: collapsed
          Accessible.focused: highlighted
          Accessible.onPressAction: root.toggleGroupFromHeading(section)

          Rectangle {
            anchors.fill: parent
            anchors.bottomMargin: Style.space(1)
            radius: Style.cornerRadius
            color: sectionHeading.highlighted
              ? Style.focusFillFor(root.foreground, Color.accent)
              : "transparent"
          }

          Text {
            id: sectionDisclosure
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            text: sectionHeading.collapsed ? "\uf054" : "\uf078"
            color: sectionHeading.highlighted ? root.foreground : root.dimForeground
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Text {
            anchors.left: sectionDisclosure.right
            anchors.leftMargin: Style.space(6)
            anchors.right: parent.right
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            text: Model.kindSectionLabel(sectionHeading.section)
            color: root.dimForeground
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
            elide: Text.ElideRight
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.toggleGroupFromHeading(sectionHeading.section)
          }
        }

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) { root.handleSupplementalListKey(event) }
        onCountChanged: {
          if (!root.resultUpdateInProgress) {
            if (count <= 0) root.setCurrentIndex(-1, false)
            else if (currentIndex < 0) root.setCurrentIndex(0, false)
            else if (currentIndex >= count) root.setCurrentIndex(count - 1, false)
          }
        }

        ScrollBar.vertical: ScrollBar {
          objectName: "everything-scrollbar"
          policy: ScrollBar.AsNeeded
          leftPadding: Style.space(4)
          rightPadding: 0
          palette.mid: Color.accent
          palette.dark: Color.accent
        }

        delegate: Item {
          id: row
          required property var modelData
          required property int index
          width: resultList.width
          height: groupCollapsed ? 0 : root.rowHeight
          visible: !groupCollapsed
          enabled: !groupCollapsed
          readonly property bool groupCollapsed: root.groupCollapsed(modelData.kind)
          readonly property bool highlighted: !groupCollapsed && (root.pointerCursorActive
              || resultList.activeFocus || keyCatcher.activeFocus)
            && resultList.currentIndex === index
          readonly property string crumb: root.breadcrumb(modelData)
          readonly property string metadata: Model.metadataForItem(
            modelData, root.itemRelations)
          readonly property var windowEntry: root.resolveWindowDesktopEntry(modelData)
          readonly property string windowAppGlyph: Model.windowAppGlyph(modelData, windowEntry)
          readonly property string windowIconSource: windowAppGlyph.length === 0
            ? root.windowIconSource(modelData, windowEntry) : ""

          Accessible.role: Accessible.ListItem
          Accessible.name: String(modelData.title || "Untitled")
          Accessible.description: [String(modelData.provider || ""), Model.kindLabel(modelData.kind)]
            .concat(Array.isArray(modelData.badges) ? modelData.badges : [])
            .concat(modelData.active === true ? ["Current thing"] : [])
            .concat(crumb ? [crumb] : [])
            .filter(function(value) { return value.length > 0 }).join(", ")
          Accessible.selectable: true
          Accessible.selected: highlighted
          Accessible.focusable: true
          Accessible.focused: highlighted
          Accessible.onPressAction: root.activateAt(index)

          Rectangle {
            anchors.fill: parent
            anchors.bottomMargin: Style.space(1)
            radius: Style.cornerRadius
            color: row.highlighted
              ? Style.focusFillFor(root.foreground, Color.accent)
              : "transparent"
          }

          Item {
            id: thingIcon
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            width: Style.space(24)
            height: parent.height
            Accessible.role: Accessible.Graphic
            Accessible.name: Model.kindLabel(row.modelData.kind) + " icon"

            Image {
              id: applicationIcon
              objectName: "everything-window-icon-" + row.index
              anchors.centerIn: parent
              width: Math.min(parent.width, Style.font.icon)
              height: width
              visible: row.windowAppGlyph.length === 0
                && row.windowIconSource.length > 0 && status !== Image.Error
              source: row.windowIconSource
              fillMode: Image.PreserveAspectFit
              asynchronous: true
              smooth: true
              sourceSize.width: width
              sourceSize.height: height
              layer.enabled: visible
              layer.effect: MultiEffect {
                colorization: 1.0
                colorizationColor: row.highlighted ? root.foreground : root.dimForeground
              }
            }

            OpticalGlyph {
              id: mappedWindowGlyph
              objectName: "everything-window-glyph-" + row.index
              anchors.fill: parent
              visible: row.windowAppGlyph.length > 0
              text: row.windowAppGlyph
              color: row.highlighted ? root.foreground : root.dimForeground
              fontFamily: Style.font.family
              fontSize: Style.font.icon
            }

            Text {
              id: fallbackThingIcon
              anchors.fill: parent
              visible: row.windowAppGlyph.length === 0 && !applicationIcon.visible
              text: Model.kindIcon(row.modelData.kind)
              color: row.highlighted ? root.foreground : root.dimForeground
              font.family: Style.font.family
              font.pixelSize: Style.font.icon
              horizontalAlignment: Text.AlignHCenter
              verticalAlignment: Text.AlignVCenter
            }
          }

          Text {
            id: metadataLabel
            objectName: "everything-metadata-" + row.index
            anchors.right: parent.right
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            visible: text.length > 0
            width: visible ? Math.min(implicitWidth, resultList.width * 0.4) : 0
            text: row.metadata
            color: root.dimForeground
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideMiddle
            Accessible.role: Accessible.StaticText
            Accessible.name: text
          }

          Text {
            id: titleLabel
            anchors.left: thingIcon.right
            anchors.leftMargin: Style.space(6)
            anchors.right: metadataLabel.left
            anchors.rightMargin: metadataLabel.visible ? Style.space(10) : 0
            anchors.verticalCenter: parent.verticalCenter
            text: String(row.modelData.title || "Untitled")
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            lineHeightMode: Text.FixedHeight
            lineHeight: root.rowHeight
            elide: Text.ElideRight
          }

          MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: root.selectFromPointer(row.index, row, {
              x: rowMouse.mouseX,
              y: rowMouse.mouseY
            })
            onPositionChanged: function(mouse) {
              root.selectFromPointer(row.index, row, mouse)
            }
            onClicked: {
              root.setCurrentIndex(row.index, false)
              root.pointerCursorActive = true
              root.activateAt(row.index)
            }
          }
        }
      }

      ListView {
        id: groupList
        objectName: "everything-groups"
        anchors.fill: parent
        anchors.topMargin: Style.space(4)
        anchors.bottomMargin: Style.space(6)
        visible: root.popupMode === root.groupsMode
        enabled: visible
        clip: true
        model: root.supportedGroups
        currentIndex: 0
        activeFocusOnTab: true
        boundsBehavior: Flickable.StopAtBounds
        keyNavigationEnabled: false
        highlightMoveDuration: 80
        Accessible.role: Accessible.List
        Accessible.name: "Visible thing groups"
        Accessible.description: "Checked groups appear in Everything search results"
        Accessible.focusable: true
        Accessible.focused: activeFocus

        ScrollBar.vertical: ScrollBar {
          policy: ScrollBar.AsNeeded
          leftPadding: Style.space(4)
          rightPadding: 0
          palette.mid: Color.accent
          palette.dark: Color.accent
        }

        delegate: Item {
          id: groupRow
          required property var modelData
          required property int index
          objectName: "everything-group-" + modelData.kind
          width: groupList.width
          height: root.groupChecklistRowHeight
          readonly property bool checked: !root.kindDisabled(modelData.kind)
          readonly property bool highlighted: groupList.currentIndex === index
            && (groupList.activeFocus || keyCatcher.activeFocus)

          function activate() {
            root.setGroupChecklistIndex(index)
            groupList.forceActiveFocus()
            root.toggleKindVisibility(modelData.kind)
          }

          Accessible.role: Accessible.CheckBox
          Accessible.name: modelData.sectionLabel
          Accessible.description: checked
            ? "Shown in Everything search results" : "Hidden from Everything search results"
          Accessible.checkable: true
          Accessible.checked: checked
          Accessible.focusable: true
          Accessible.focused: highlighted
          Accessible.onPressAction: groupRow.activate()
          Accessible.onToggleAction: groupRow.activate()

          Rectangle {
            anchors.fill: parent
            anchors.bottomMargin: Style.space(1)
            radius: Style.cornerRadius
            color: groupRow.highlighted
              ? Style.focusFillFor(root.foreground, Color.accent)
              : "transparent"
          }

          Text {
            id: groupCheckmark
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(24)
            text: groupRow.checked ? "\uf14a" : "\uf0c8"
            color: groupRow.checked ? Color.accent : root.dimForeground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
          }

          Text {
            id: groupIcon
            anchors.left: groupCheckmark.right
            anchors.leftMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(24)
            text: groupRow.modelData.icon
            color: groupRow.highlighted ? root.foreground : root.dimForeground
            font.family: Style.font.family
            font.pixelSize: Style.font.icon
            horizontalAlignment: Text.AlignHCenter
          }

          Text {
            anchors.left: groupIcon.right
            anchors.leftMargin: Style.space(8)
            anchors.right: parent.right
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            text: groupRow.modelData.sectionLabel
            color: groupRow.checked ? root.foreground : root.dimForeground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }

          MouseArea {
            objectName: "everything-group-pointer-" + groupRow.modelData.kind
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: groupRow.activate()
          }
        }
      }

    }
  }
}
}
