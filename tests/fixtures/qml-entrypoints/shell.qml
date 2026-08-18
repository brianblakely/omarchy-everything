import QtQuick
import Quickshell

ShellRoot {
  id: root

  readonly property string sourceDir: Quickshell.env("EVERYTHING_SOURCE_DIR")
  property var serviceObject: null
  property var widgetObject: null
  property var searchObject: null
  property var listObject: null
  property var keyCatcherObject: null
  property int refreshTestStage: 0
  property string selectedBeforeRefresh: ""
  property string shortListSelection: ""
  property real selectedOffsetBeforeRefresh: 0
  property var rankedBeforeRefresh: null

  function manifestData(source) {
    return {
      schemaVersion: 1,
      id: "b.everything",
      name: "Everything",
      version: "0.0.1-test",
      kinds: ["service", "bar-widget"],
      entryPoints: { service: "Service.qml", barWidget: "Everything.qml" },
      __sourceDir: source
    }
  }

  function component(fileName) {
    return Qt.createComponent(encodeURI("file://" + sourceDir + "/" + fileName), Component.PreferSynchronous)
  }

  function findNamed(object, name) {
    if (!object) return null
    if (String(object.objectName || "") === name) return object
    var descendants = object.children || []
    for (var i = 0; i < descendants.length; i++) {
      var match = findNamed(descendants[i], name)
      if (match) return match
    }
    return null
  }

  function rows(reverseOrder, tokenGeneration) {
    var out = []
    for (var i = 0; i < 40; i++) {
      out.push({
        id: "test:" + String(i).padStart(2, "0"),
        uiUuid: "00000000-0000-5000-8000-" + String(i).padStart(12, "0"),
        kind: "window",
        provider: "Test",
        title: "Shared thing",
        context: "Refresh fixture",
        searchTerms: [],
        parentId: "",
        badges: [],
        active: false,
        recency: reverseOrder ? i : 100 - i,
        activationToken: "token-" + String(tokenGeneration || "one") + "-" + i
      })
    }
    return out
  }

  function resultId(index) {
    if (index < 0 || index >= widgetObject.rankedItems.length) return ""
    return String(widgetObject.rankedItems[index].id || "")
  }

  function failRefreshTest(message) {
    console.error("EVERYTHING_REFRESH_ERROR " + message)
    refreshTestTimer.stop()
    Qt.quit()
  }

  function refreshTestTick() {
    if (refreshTestStage === 0) {
      searchObject = findNamed(widgetObject, "everything-search")
      listObject = findNamed(widgetObject, "everything-results")
      keyCatcherObject = findNamed(widgetObject, "everything-key-catcher")
      if (!searchObject || !listObject || !keyCatcherObject) {
        failRefreshTest("controls not found")
        return
      }
      serviceObject.items = rows(false, "one")
    } else if (refreshTestStage === 1) {
      searchObject.text = "shared"
    } else if (refreshTestStage === 2) {
      if (widgetObject.rankedItems.length !== 40) {
        failRefreshTest("initial result count")
        return
      }
      widgetObject.focusList(16)
      keyCatcherObject.moveRequested(0, 1)
      if (listObject.currentIndex !== 17) {
        failRefreshTest("shell vertical movement was not routed")
        return
      }
      keyCatcherObject.moveRequested(-1, 0)
      if (listObject.currentIndex !== 16) {
        failRefreshTest("shell horizontal movement was not routed")
        return
      }
      listObject.contentY = listObject.originY + widgetObject.rowHeight * 14 + 7
      selectedBeforeRefresh = resultId(listObject.currentIndex)
      selectedOffsetBeforeRefresh = listObject.currentIndex * widgetObject.rowHeight - listObject.contentY
      rankedBeforeRefresh = widgetObject.rankedItems
      serviceObject.items = rows(false, "two")
    } else if (refreshTestStage === 3) {
      if (widgetObject.rankedItems !== rankedBeforeRefresh) {
        failRefreshTest("unchanged list was replaced")
        return
      }
      serviceObject.items = rows(true, "three")
    } else if (refreshTestStage === 4) {
      if (searchObject.text !== "shared") {
        failRefreshTest("query changed")
        return
      }
      if (resultId(listObject.currentIndex) !== selectedBeforeRefresh) {
        failRefreshTest("selection changed")
        return
      }
      if (listObject.contentHeight > listObject.height + 0.5) {
        var selectedOffset = listObject.currentIndex * widgetObject.rowHeight - listObject.contentY
        if (Math.abs(selectedOffset - selectedOffsetBeforeRefresh) > 1) {
          failRefreshTest("highlight moved")
          return
        }
      }
      serviceObject.items = rows(true, "four").filter(function(row) {
        return row.id !== selectedBeforeRefresh
      })
    } else if (refreshTestStage === 5) {
      if (listObject.currentIndex !== 0) {
        failRefreshTest("removed selection did not return to the first row")
        return
      }
      serviceObject.items = rows(false, "five").slice(0, 3)
    } else if (refreshTestStage === 6) {
      if (widgetObject.rankedItems.length !== 3) {
        failRefreshTest("short list result count")
        return
      }
      widgetObject.focusList(0)
      shortListSelection = resultId(listObject.currentIndex)
      serviceObject.items = rows(true, "six").slice(0, 3)
    } else if (refreshTestStage === 7) {
      if (resultId(listObject.currentIndex) !== shortListSelection) {
        failRefreshTest("short list selection changed")
        return
      }
      if (listObject.contentHeight > listObject.height + 0.5) {
        failRefreshTest("short list unexpectedly scrolls")
        return
      }
      console.log("EVERYTHING_REFRESH_OK")
      refreshTestTimer.stop()
      Qt.quit()
      return
    }
    refreshTestStage += 1
  }

  function loadEntries() {
    var serviceComponent = component("Service.qml")
    if (serviceComponent.status !== Component.Ready) {
      console.error("EVERYTHING_LOAD_ERROR service: " + serviceComponent.errorString())
      Qt.quit()
      return
    }
    serviceObject = serviceComponent.createObject(host, {
      manifest: manifestData(""),
      shell: mockShell,
      omarchyPath: Quickshell.env("OMARCHY_PATH")
    })
    if (!serviceObject) {
      console.error("EVERYTHING_CREATE_ERROR service: " + serviceComponent.errorString())
      Qt.quit()
      return
    }
    console.log("EVERYTHING_LOAD_OK service")

    serviceObject.acquire("monitor-a")
    serviceObject.acquire("monitor-b")
    if (serviceObject.leaseCount !== 2) console.error("EVERYTHING_LEASE_ERROR acquire")
    serviceObject.release("monitor-a")
    if (serviceObject.leaseCount !== 1) console.error("EVERYTHING_LEASE_ERROR release-one")
    serviceObject.release("monitor-b")
    if (serviceObject.leaseCount !== 0) console.error("EVERYTHING_LEASE_ERROR release-all")
    console.log("EVERYTHING_LEASE_OK")

    var widgetComponent = component("Everything.qml")
    if (widgetComponent.status !== Component.Ready) {
      console.error("EVERYTHING_LOAD_ERROR widget: " + widgetComponent.errorString())
      Qt.quit()
      return
    }
    widgetObject = widgetComponent.createObject(host, { bar: mockBar, moduleName: "b.everything" })
    if (!widgetObject) {
      console.error("EVERYTHING_CREATE_ERROR widget: " + widgetComponent.errorString())
      Qt.quit()
      return
    }
    console.log("EVERYTHING_LOAD_OK widget")
    refreshTestTimer.start()
  }

  Item { id: host }

  QtObject {
    id: mockShell
    function serviceFor(id) { return id === "b.everything" ? root.serviceObject : null }
  }

  QtObject {
    id: mockBar
    property var shell: mockShell
    property string position: "top"
    property string fontFamily: "sans-serif"
    property color foreground: "#ffffff"
    property color barForeground: "#ffffff"
    property color urgent: "#ff5555"
    property bool vertical: false
    property bool foregroundAnimationEnabled: false
    property int barSize: 36
    property var activePopout: null
    property var clickTargets: []
    function registerClickTarget(target) { clickTargets = clickTargets.concat([target]) }
    function unregisterClickTarget(target) { clickTargets = clickTargets.filter(function(value) { return value !== target }) }
    function requestPopout(owner) { activePopout = owner }
    function releasePopout(owner) { if (activePopout === owner) activePopout = null }
    function showTooltip(_target, _text) {}
    function hideTooltip(_target) {}
  }

  Timer {
    interval: 1
    running: true
    repeat: false
    onTriggered: root.loadEntries()
  }

  Timer {
    id: refreshTestTimer
    interval: 20
    repeat: true
    onTriggered: root.refreshTestTick()
  }
}
