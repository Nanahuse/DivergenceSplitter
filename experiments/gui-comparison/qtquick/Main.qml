import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    required property var backend
    width: 1100
    height: 760
    minimumWidth: 760
    minimumHeight: 520
    visible: true
    title: "DivergenceSplitter comparison - Qt Quick"
    property bool dark: backend.initialDark
    property string pending: ""
    palette.window: dark ? "#23252a" : "#efefef"
    palette.windowText: dark ? "white" : "black"
    palette.base: dark ? "#191b1f" : "white"
    palette.text: dark ? "white" : "black"
    palette.button: dark ? "#32353c" : "#efefef"
    palette.buttonText: dark ? "white" : "black"
    palette.highlight: "#3278b8"
    onClosing: function(close) {
        backend.resetCancel()
        if (!backend.finishing && backend.dirty) {
            close.accepted = false
            pending = "close"
            unsaved.open()
        } else backend.closeAccepted()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        RowLayout {
            Button { id: start; text: "Start"; onClicked: backend.setRunning(true) }
            Button { id: stop; text: "Stop"; onClicked: backend.setRunning(false) }
            Button {
                id: reset
                objectName: "reset"
                text: backend.resetText
                Layout.preferredWidth: 160
                onPressed: backend.resetPress()
                onReleased: backend.resetCancel()
                onCanceled: backend.resetCancel()
                onActiveFocusChanged: if (!activeFocus) backend.resetCancel()
            }
            Button { id: mutate; text: "Add/remove diagnostic branch"; onClicked: backend.mutate() }
            Button { id: theme; text: "Light / dark"; onClicked: root.dark = !root.dark }
        }
        Label { text: backend.status; Layout.fillWidth: true }
        TabBar {
            id: tabs
            Layout.fillWidth: true
            onCurrentIndexChanged: backend.pageChanged(currentIndex)
            TabButton { text: "Monitor" }
            TabButton { text: "Diagnostics" }
            TabButton { text: "Profile" }
        }
        StackLayout {
            Layout.fillHeight: true
            Layout.fillWidth: true
            currentIndex: tabs.currentIndex
            RowLayout {
                Image {
                    source: backend.previewSource
                    cache: false
                    fillMode: Image.PreserveAspectFit
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 580
                }
                ScrollView {
                    Layout.fillHeight: true
                    Layout.preferredWidth: 350
                    clip: true
                    ListView {
                        model: backend.cards
                        spacing: 8
                        delegate: Frame {
                            required property string display
                            required property string summary
                            width: ListView.view.width
                            height: 84
                            ColumnLayout {
                                anchors.fill: parent
                                Label { text: display; font.bold: true }
                                Label { text: summary; font.pixelSize: 13 }
                            }
                        }
                    }
                }
            }
            ColumnLayout {
                RowLayout {
                    Label { text: "Scenario / Rule / Condition / Detector"; Layout.fillWidth: true }
                    Label { text: "Score / state"; Layout.preferredWidth: 180 }
                }
                TreeView {
                    id: tree
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: backend.diagnostics
                    columnWidthProvider: function(column) { return column === 0 ? Math.max(300, width - 200) : 200 }
                    delegate: TreeViewDelegate { implicitHeight: 28; implicitWidth: 300 }
                    ScrollBar.vertical: ScrollBar {}
                    onExpanded: Qt.callLater(backend.expansionChanged)
                    onCollapsed: Qt.callLater(backend.expansionChanged)
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 124
                    clip: true
                    Row {
                        spacing: 8
                        Repeater {
                            model: backend.referenceSources
                            Image { required property string modelData; source: modelData; cache: false; width: 160; height: 100; fillMode: Image.PreserveAspectFit }
                        }
                    }
                }
            }
            ColumnLayout {
                RowLayout {
                    ComboBox { model: ["Synthetic camera", "Synthetic file"]; currentIndex: backend.source; onActivated: backend.editSource(currentIndex) }
                    TextField { id: file; Layout.fillWidth: true; text: backend.file; placeholderText: "Mock source file path / 日本語入力"; onTextEdited: backend.editFile(text) }
                    Button { id: browse; text: "Browse..."; onClicked: fileDialog.open() }
                }
                Label { text: "Scenario name                                    Port             Enabled" }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ListView {
                        id: profileList
                        model: backend.profiles
                        spacing: 4
                        delegate: RowLayout {
                            id: scenario
                            required property int index
                            required property string scenarioName
                            required property int scenarioPort
                            required property bool scenarioEnabled
                            width: ListView.view.width
                            TextField { id: name; Layout.fillWidth: true; text: scenario.scenarioName; onEditingFinished: backend.editScenario(scenario.index, 0, text) }
                            TextField { text: scenario.scenarioPort; Layout.preferredWidth: 110; validator: IntValidator { bottom: 1; top: 65535 }; onEditingFinished: backend.editScenario(scenario.index, 1, text) }
                            CheckBox { id: enabled; checked: scenario.scenarioEnabled; onToggled: backend.editScenario(scenario.index, 2, checked) }
                            Button { text: "Remove"; onClicked: { profileList.currentIndex = scenario.index; remove.clicked() } }
                            function editForTest(value, active) { name.text = value; name.editingFinished(); enabled.checked = active; enabled.toggled() }
                        }
                    }
                }
                RowLayout {
                    Button { id: add; text: "Add Scenario"; onClicked: backend.addScenario() }
                    Button { id: remove; text: "Remove Scenario"; onClicked: backend.removeScenario(profileList.currentIndex) }
                    Button { id: apply; text: "Apply"; onClicked: backend.apply() }
                    Button { id: discard; text: "Discard"; onClicked: backend.discard() }
                    Button { id: fresh; text: "New Profile"; onClicked: { if (backend.dirty) { root.pending = "fresh"; unsaved.open() } else backend.fresh() } }
                    Label { text: backend.dirty ? "Unapplied changes" : "Applied" }
                }
                Label { text: backend.errors; color: root.dark ? "#ffaaaa" : "#a00000"; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }
    }
    FileDialog {
        id: fileDialog
        title: "Select mock input source"
        nameFilters: ["Video files (*.avi *.mp4)", "All files (*)"]
        onAccepted: backend.selectFile(selectedFile)
        onRejected: backend.fileCancelled()
    }
    MessageDialog {
        id: unsaved
        title: "Unsaved Profile"
        text: "Discard unapplied changes?"
        buttons: MessageDialog.Discard | MessageDialog.Cancel
        onButtonClicked: function(button, role) {
            if (button === MessageDialog.Discard) {
                backend.discard()
                if (root.pending === "close") root.close()
                else backend.fresh()
            } else backend.discardCancelled()
        }
        onRejected: backend.discardCancelled()
    }
    Timer {
        id: cancelDialog
        interval: 250
        property string kind
        onTriggered: {
            if (kind === "file" && fileDialog.visible) fileDialog.reject()
            else if (kind === "unsaved" && unsaved.visible) unsaved.reject()
            else throw new Error("Test did not open the requested dialog")
        }
    }
    Timer {
        id: openUnsaved
        interval: 600
        onTriggered: { fresh.clicked(); cancelDialog.kind = "unsaved"; cancelDialog.restart() }
    }

    // Contract driver uses the same controls, model indexes and pointer delivery as the UI.
    function showPage(page) { tabs.currentIndex = page }
    function expandedNodes() {
        let ids = []
        for (let row = 0; row < tree.rows; ++row)
            if (tree.isExpanded(row)) ids.push(backend.diagnostics.data(tree.index(row, 0), 256))
        return ids
    }
    function visibleNodes() {
        let ids = []
        for (let row = Math.max(0, tree.topRow); row <= tree.bottomRow; ++row)
            ids.push(backend.diagnostics.data(tree.index(row, 0), 256))
        return ids
    }
    function topologyChanged() { Qt.callLater(function() { tree.forceLayout(); backend.expansionChanged() }) }
    function expandNode(index) {
        tree.expandToIndex(index)
        tree.forceLayout()
        tree.expand(tree.rowAtIndex(index))
        tree.forceLayout()
        backend.expansionChanged()
    }
    function collapseNode(index) { tree.collapse(tree.rowAtIndex(index)); tree.forceLayout(); backend.expansionChanged() }
    function viewProbe() { return { scroll: tree.contentY, busy: fileDialog.visible || unsaved.visible || openUnsaved.running || cancelDialog.running } }
    function testAction(action) {
        switch (action) {
        case 5: mutate.clicked(); break
        case 6: profileList.itemAtIndex(0).editForTest("", true); break
        case 7: profileList.itemAtIndex(0).editForTest("Edited scenario", false); break
        case 8: apply.clicked(); break
        case 9: add.clicked(); break
        case 10: profileList.currentIndex = profileList.count - 1; remove.clicked(); break
        case 11:
            profileList.itemAtIndex(0).editForTest("Edited scenario", true)
            openUnsaved.restart(); break
        case 12: browse.clicked(); cancelDialog.kind = "file"; cancelDialog.restart(); break
        case 13: discard.clicked(); break
        case 17: theme.clicked(); break
        case 18: root.width = 800; root.height = 600; break
        case 19: start.clicked(); break
        case 20: stop.clicked(); break
        case 21:
            for (let row = 0; row < tree.rows; ++row)
                if (tree.depth(row) === 0) tree.expand(row)
            tree.forceLayout(); tree.contentY = 2; backend.expansionChanged(); break
        }
    }
}
