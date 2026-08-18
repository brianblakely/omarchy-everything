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
  readonly property int rowHeight: Style.space(62)
  readonly property var rankedItems: Model.rank(
    everythingService ? everythingService.items : [],
    searchField.text,
    everythingService ? everythingService.hiddenIds : {})
  // A widget may acquire its service lease before its QsWindow/screen exists.
  // Keep the owner key stable and instance-local so an early "unknown" screen
  // can never collide with another monitor or leak a lease after reparenting.
  readonly property string instanceKey: "everything:" + Date.now() + ":"
    + Math.random().toString(36).slice(2)

  function open() {
    if (!root.opened) root.controller.show()
    searchField.text = ""
    if (everythingService) everythingService.acquire(instanceKey)
    Qt.callLater(function() {
      if (root.opened) searchField.forceActiveFocus()
    })
  }

  function close() {
    root.controller.hide()
  }

  function togglePanel() {
    if (root.opened) root.close()
    else root.open()
  }

  function focusSearch() {
    searchField.forceActiveFocus()
  }

  function focusList(index) {
    if (resultList.count <= 0) return
    resultList.currentIndex = Math.max(0, Math.min(index === undefined ? 0 : index, resultList.count - 1))
    resultList.forceActiveFocus()
    resultList.positionViewAtIndex(resultList.currentIndex, ListView.Contain)
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
    var nextIndex = Model.nextIndexAfterRemoval(index, rankedItems.length)
    everythingService.hideItem(rankedItems[index].id)
    Qt.callLater(function() {
      if (nextIndex >= 0) root.focusList(nextIndex)
      else searchField.forceActiveFocus()
    })
  }

  function handleEscape() {
    if (searchField.text.length > 0) {
      searchField.text = ""
      searchField.forceActiveFocus()
    } else {
      root.close()
    }
  }

  function pageSize() {
    return Math.max(1, Math.floor(resultList.height / rowHeight))
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

  function handleListKey(event) {
    var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
    var shift = (event.modifiers & Qt.ShiftModifier) !== 0
    var action = ""
    if (event.key === Qt.Key_Down) action = "next"
    else if (event.key === Qt.Key_Up) action = "previous"
    else if (ctrl && event.key === Qt.Key_N) action = "next"
    else if (ctrl && event.key === Qt.Key_P) action = "previous"
    else if (event.key === Qt.Key_Home || (!ctrl && !shift && event.text === "g")) action = "first"
    else if (event.key === Qt.Key_End || (!ctrl && event.text === "G")) action = "last"
    else if (event.key === Qt.Key_PageDown || (ctrl && event.key === Qt.Key_D)) action = "page-next"
    else if (event.key === Qt.Key_PageUp || (ctrl && event.key === Qt.Key_U)) action = "page-previous"
    else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) action = "activate"
    else if (event.key === Qt.Key_Slash || event.text === "/") action = "search"
    else if (event.key === Qt.Key_Backspace || event.key === Qt.Key_Delete) action = "hide"
    else if (event.key === Qt.Key_Escape) action = "escape"
    else if (event.key === Qt.Key_Backtab || (event.key === Qt.Key_Tab && shift)) action = "search"

    if (!action) return
    event.accepted = true
    if (action === "next") moveSelection(1)
    else if (action === "previous") moveSelection(-1)
    else if (action === "first") focusList(0)
    else if (action === "last") focusList(resultList.count - 1)
    else if (action === "page-next") moveSelection(pageSize())
    else if (action === "page-previous") moveSelection(-pageSize())
    else if (action === "activate") activateAt(resultList.currentIndex)
    else if (action === "search") focusSearch()
    else if (action === "hide") hideAt(resultList.currentIndex)
    else if (action === "escape") handleEscape()
  }

  onOpenedChanged: {
    if (root.opened) {
      if (everythingService) everythingService.acquire(instanceKey)
      Qt.callLater(function() { searchField.forceActiveFocus() })
    } else if (everythingService) {
      everythingService.release(instanceKey)
    }
  }

  onEverythingServiceChanged: if (root.opened && everythingService) everythingService.acquire(instanceKey)
  Component.onDestruction: if (everythingService) everythingService.release(instanceKey)

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf078"
    active: root.opened
    tooltipText: "Everything"
    activeFocusOnTab: true
    Keys.onReturnPressed: root.togglePanel()
    Keys.onEnterPressed: root.togglePanel()
    Keys.onSpacePressed: root.togglePanel()
    onPressed: function(_buttonCode) { root.togglePanel() }

    Accessible.role: Accessible.Button
    Accessible.name: "Open Everything thing switcher"
    Accessible.description: "Search windows, tabs, panes, sessions, agents, and buffers"
    Accessible.focusable: true
    Accessible.focused: activeFocus
    Accessible.onPressAction: root.togglePanel()

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
    focusTarget: searchField
    centerOnBar: true
    contentWidth: popup.fittedContentWidth(Style.space(620))
    contentHeight: popup.cappedContentHeight(Style.space(620))

    Item {
      id: content
      anchors.fill: parent
      Accessible.role: Accessible.Pane
      Accessible.name: "Everything thing switcher"

      Row {
        id: heading
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: Style.space(34)
        spacing: Style.space(8)

        Text {
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width - refreshButton.width - parent.spacing
          text: "Everything"
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.subtitle
          font.bold: true
          Accessible.role: Accessible.Heading
          Accessible.name: text
        }

        Button {
          id: refreshButton
          anchors.verticalCenter: parent.verticalCenter
          text: "Refresh"
          iconText: "󰑐"
          foreground: root.foreground
          focusable: true
          enabled: !!root.everythingService && !root.everythingService.scanning
          onClicked: if (root.everythingService) root.everythingService.refresh()
          Accessible.role: Accessible.Button
          Accessible.name: "Refresh all thing providers"
          Accessible.focusable: true
          Accessible.focused: activeFocus
          Accessible.onPressAction: if (root.everythingService) root.everythingService.refresh()
        }
      }

      TextField {
        id: searchField
        anchors.top: heading.bottom
        anchors.topMargin: Style.space(8)
        anchors.left: parent.left
        anchors.right: parent.right
        placeholderText: "Search every thing…"
        foreground: root.foreground
        activeFocusOnTab: true
        Accessible.role: Accessible.EditableText
        Accessible.name: "Search things"
        Accessible.description: "Type to fuzzily filter the result list"
        Accessible.editable: true
        Accessible.focusable: true
        Accessible.focused: activeFocus

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
        anchors.topMargin: Style.space(7)
        anchors.left: parent.left
        anchors.right: parent.right
        height: Style.space(22)
        text: {
          if (!root.everythingService) return "Starting Everything…"
          if (root.everythingService.statusMessage) return root.everythingService.statusMessage
          if (root.rankedItems.length === 0 && searchField.text) return "No matches"
          if (root.everythingService.warnings.length > 0)
            return "Some providers are unavailable · " + root.everythingService.warnings[root.everythingService.warnings.length - 1]
          return root.rankedItems.length + (root.rankedItems.length === 1 ? " thing" : " things")
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
        Accessible.name: "Ranked thing results"
        Accessible.description: "Use arrow keys to select and Enter to switch"
        Accessible.focusable: count > 0
        Accessible.focused: activeFocus

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) { root.handleListKey(event) }
        onCountChanged: {
          if (count <= 0) currentIndex = -1
          else if (currentIndex < 0) currentIndex = 0
          else if (currentIndex >= count) currentIndex = count - 1
        }

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        delegate: Item {
          id: row
          required property var modelData
          required property int index
          width: resultList.width
          height: root.rowHeight
          readonly property bool highlighted: resultList.activeFocus && resultList.currentIndex === index
          readonly property string crumb: root.breadcrumb(modelData)

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
            anchors.bottomMargin: Style.space(2)
            radius: Style.cornerRadius
            color: row.highlighted
              ? Style.focusFillFor(root.foreground, Color.accent)
              : (rowMouse.containsMouse ? Style.hoverFillFor(root.foreground, Color.accent) : "transparent")
            border.width: row.highlighted ? Math.max(1, Style.normalBorderWidth) : 0
            border.color: Color.accent
          }

          Column {
            anchors.left: parent.left
            anchors.leftMargin: Style.space(10)
            anchors.right: badgeRow.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(3)

            Text {
              width: parent.width
              text: String(row.modelData.title || "Untitled")
              color: root.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              font.bold: row.highlighted || row.modelData.active === true
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              visible: text.length > 0
              text: row.crumb
              color: root.dimForeground
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              elide: Text.ElideMiddle
            }
          }

          Row {
            id: badgeRow
            anchors.right: parent.right
            anchors.rightMargin: Style.space(9)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)

            Repeater {
              model: [String(row.modelData.provider || "Local"), Model.kindLabel(row.modelData.kind)]
                .concat(Array.isArray(row.modelData.badges) ? row.modelData.badges.slice(1, 3) : [])

              Rectangle {
                id: badge
                required property string modelData
                width: badgeLabel.implicitWidth + Style.space(10)
                height: badgeLabel.implicitHeight + Style.space(5)
                radius: height / 2
                color: Style.normalFillFor(root.foreground, Color.accent)

                Text {
                  id: badgeLabel
                  anchors.centerIn: parent
                  text: badge.modelData
                  color: root.dimForeground
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }

                Accessible.role: Accessible.StaticText
                Accessible.name: badge.modelData
              }
            }
          }

          MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: resultList.currentIndex = row.index
            onClicked: {
              resultList.currentIndex = row.index
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
        text: "↑↓ move  ·  Enter switch  ·  / search  ·  Delete hide  ·  Esc clear/close"
        color: root.dimForeground
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        Accessible.role: Accessible.StaticText
        Accessible.name: "Keyboard help: arrows move, Enter switches, slash searches, Delete hides, Escape clears or closes"
      }
    }
  }
}
