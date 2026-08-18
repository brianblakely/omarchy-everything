import QtQuick
import Quickshell

ShellRoot {
  id: root

  readonly property string sourceDir: Quickshell.env("EVERYTHING_SOURCE_DIR")
  property var serviceObject: null
  property var widgetObject: null

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
    Qt.callLater(Qt.quit)
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
}

