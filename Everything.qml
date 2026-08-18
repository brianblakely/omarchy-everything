pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
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
  readonly property color foreground: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dimForeground: Qt.darker(foreground, 1.55)
  readonly property real rowHeight: Style.font.body * 1.5
  readonly property int sectionHeight: Style.space(24)
  property var rankedItems: []
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

  function selectFromPointer(index, item, mouse) {
    if (!pointerMoveGate.moved(item, mouse)) return
    setCurrentIndex(index, false)
    pointerCursorActive = true
  }

  function focusSearch() {
    disarmPointer()
    searchField.forceActiveFocus()
  }

  function focusList(index) {
    if (resultList.count <= 0) return
    disarmPointer()
    setCurrentIndex(index === undefined ? 0 : index, true)
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
    if (reveal === true) resultList.positionViewAtIndex(bounded, ListView.Contain)
  }

  function moveSelection(delta) {
    if (resultList.count <= 0) return
    focusList(Math.max(0, Math.min(resultList.count - 1, resultList.currentIndex + delta)))
  }

  function activateAt(index) {
    if (index < 0 || index >= rankedItems.length || !everythingService) return
    var target = rankedItems[index]
    // Release the layer-shell keyboard grab before asking another surface to
    // accept focus. Service.qml keeps the helper alive for the pending action.
    root.close()
    Qt.callLater(function() { everythingService.activate(target) })
  }

  function hideAt(index) {
    if (index < 0 || index >= rankedItems.length || !everythingService) return
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
    return Model.sectionedRowTop(rankedItems, index, rowHeight, sectionHeight)
  }

  function rowVisualTop(index) {
    if (index >= 0 && typeof resultList.itemAtIndex === "function") {
      var delegateItem = resultList.itemAtIndex(index)
      if (delegateItem) return Number(delegateItem.y)
    }
    return resultList.originY + rowTopAt(index)
  }

  function pageDelta(direction) {
    if (resultList.count <= 0 || direction === 0) return 0
    var current = Math.max(0, Math.min(resultList.count - 1, resultList.currentIndex))
    var target = rowVisualTop(current) + (direction > 0 ? resultList.height : -resultList.height)
    var candidate = current
    if (direction > 0) {
      while (candidate + 1 < resultList.count && rowVisualTop(candidate + 1) <= target)
        candidate++
      if (candidate === current && candidate + 1 < resultList.count) candidate++
    } else {
      while (candidate - 1 >= 0 && rowVisualTop(candidate - 1) >= target)
        candidate--
      if (candidate === current && candidate > 0) candidate--
    }
    return candidate - current
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
      ? resultList.contentY - rowVisualTop(current) : 0
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
    resultUpdateInProgress = false
    pendingSelectionSurvived = false
    applyOpenResultReset()
    Qt.callLater(function() {
      if (!root.opened) return
      if (typeof resultList.forceLayout === "function") resultList.forceLayout()
      root.applyOpenResultReset()
      resultList.forceActiveFocus()
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
      everythingService ? everythingService.hiddenIds : {})
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
      resultList.contentY = Model.clampContentY(rowVisualTop(index) + savedSelectedOffset,
        resultList.originY, resultList.contentHeight, resultList.height)
    } else if (!pendingSelectionSurvived) {
      resultList.contentY = resultList.originY
    }

    if (savedKeyCatcherFocus) keyCatcher.forceActiveFocus()
    else if (savedListFocus && index >= 0) resultList.forceActiveFocus()
    else if (savedSearchFocus) searchField.forceActiveFocus()
    resultUpdateInProgress = false
  }

  function itemForId(id) {
    if (!id || !everythingService) return null
    var source = everythingService.items || []
    for (var i = 0; i < source.length; i++)
      if (String(source[i].id) === String(id)) return source[i]
    return null
  }

  function breadcrumb(item) {
    var values = []
    var seen = {}
    var cursor = item
    for (var depth = 0; cursor && cursor.parentId && depth < 12; depth++) {
      var parentId = String(cursor.parentId)
      if (seen[parentId]) break
      seen[parentId] = true
      var parent = itemForId(parentId)
      if (!parent) break
      values.unshift(String(parent.title || ""))
      cursor = parent
    }
    var context = item && item.context ? String(item.context) : ""
    if (context && (values.length === 0 || values[values.length - 1] !== context))
      values.push(context)
    return values.join("  ›  ")
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
    else if (action === "first") focusList(0)
    else if (action === "last") focusList(resultList.count - 1)
    else if (action === "page-next") moveSelection(pageDelta(1))
    else if (action === "page-previous") moveSelection(pageDelta(-1))
    else if (action === "hide") hideAt(resultList.currentIndex)
  }

  onOpenedChanged: {
    if (root.opened) {
      searchField.text = ""
      rebuildRankedItems()
      resetResultsForOpen()
      if (everythingService) everythingService.acquire(instanceKey)
    } else if (everythingService) {
      everythingService.release(instanceKey)
    }
  }

  onEverythingServiceChanged: {
    if (root.opened && everythingService) everythingService.acquire(instanceKey)
    scheduleRankedItems()
  }
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
    anchors.fill: parent
    bar: root.bar
    text: "\uf078"
    active: root.opened
    tooltipText: "Everything"
    activeFocusOnTab: true
    Keys.onReturnPressed: root.toggle()
    Keys.onEnterPressed: root.toggle()
    Keys.onSpacePressed: root.toggle()
    onPressed: function(_buttonCode) { root.toggle() }

    Accessible.role: Accessible.Button
    Accessible.name: "Open Everything"
    Accessible.description: "Search windows, tabs, panes, sessions, agents, and buffers"
    Accessible.focusable: true
    Accessible.focused: activeFocus
    Accessible.onPressAction: root.toggle()

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
    focusTarget: resultList
    contentWidth: popup.fittedContentWidth(Style.space(620))
    contentHeight: popup.cappedContentHeight(Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      objectName: "everything-key-catcher"
      anchors.fill: parent
      blocked: searchField.activeFocus

      onMoveRequested: function(dx, dy) {
        var delta = dy !== 0 ? dy : dx
        if (delta !== 0) root.moveSelection(delta)
      }
      onActivateRequested: root.activateAt(resultList.currentIndex)
      onCloseRequested: root.handleEscape()
      onDeleteRequested: root.hideAt(resultList.currentIndex)
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (text === "/") root.focusSearch()
        else if (text === "g") root.focusList(0)
        else if (text === "G") root.focusList(resultList.count - 1)
      }

      Item {
        id: content
        anchors.fill: parent
        Accessible.role: Accessible.Pane
        Accessible.name: "Everything search and switch panel"

      TextField {
        id: searchField
        objectName: "everything-search"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        placeholderText: "Search all things…"
        foreground: root.foreground
        activeFocusOnTab: true
        Accessible.role: Accessible.EditableText
        Accessible.name: "Search things"
        Accessible.description: "Type to fuzzily filter the result list"
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
            root.focusList(0)
          } else if (event.key === Qt.Key_Escape) {
            event.accepted = true
            root.handleEscape()
          }
        }
      }

      Text {
        id: statusText
        anchors.top: searchField.bottom
        anchors.topMargin: visible ? Style.space(7) : 0
        anchors.left: parent.left
        anchors.right: parent.right
        visible: text.length > 0
        height: visible ? Style.space(22) : 0
        text: {
          if (!root.everythingService) return "Starting Everything…"
          if (root.everythingService.statusMessage) return root.everythingService.statusMessage
          if (root.rankedItems.length === 0 && searchField.text) return "No matches"
          if (root.everythingService.warnings.length > 0)
            return "Some providers are unavailable · " + root.everythingService.warnings[root.everythingService.warnings.length - 1]
          return ""
        }
        color: root.everythingService && root.everythingService.warnings.length > 0
          ? Color.urgent : root.dimForeground
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        Accessible.description: "Everything status"
      }

      ListView {
        id: resultList
        objectName: "everything-results"
        anchors.top: statusText.bottom
        anchors.topMargin: Style.space(4)
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: footer.top
        anchors.bottomMargin: Style.space(6)
        clip: true
        model: root.rankedItems
        currentIndex: -1
        activeFocusOnTab: count > 0
        boundsBehavior: Flickable.StopAtBounds
        keyNavigationEnabled: false
        highlightMoveDuration: 80
        Accessible.role: Accessible.List
        Accessible.name: "Ranked thing list"
        Accessible.description: "Use arrow keys or H J K L to select and Enter to switch"
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

          Accessible.role: Accessible.Heading
          Accessible.name: Model.kindSectionLabel(sectionHeading.section)

          Text {
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
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

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        delegate: Item {
          id: row
          required property var modelData
          required property int index
          width: resultList.width
          height: root.rowHeight
          readonly property bool highlighted: (root.pointerCursorActive
              || resultList.activeFocus || keyCatcher.activeFocus)
            && resultList.currentIndex === index
          readonly property string crumb: root.breadcrumb(modelData)
          readonly property string metadata: Model.vitalMetadata(modelData, crumb)

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

          Text {
            id: thingIcon
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(24)
            text: Model.kindIcon(row.modelData.kind)
            color: row.highlighted || row.modelData.active === true
              ? root.foreground : root.dimForeground
            font.family: Style.font.family
            font.pixelSize: Style.font.icon
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            Accessible.role: Accessible.Graphic
            Accessible.name: Model.kindLabel(row.modelData.kind) + " icon"
          }

          Text {
            id: metadataLabel
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

      Text {
        id: footer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Style.space(20)
        text: "HJKL/↑↓ move  ·  Enter switch  ·  / search  ·  X hide  ·  Esc clear/close"
        color: root.dimForeground
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        Accessible.role: Accessible.StaticText
        Accessible.name: "Keyboard help: H J K L or arrows move, Enter switches, slash searches, X hides, Escape clears or closes"
      }
    }
  }
}
}
