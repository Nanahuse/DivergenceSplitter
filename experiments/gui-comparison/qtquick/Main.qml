pragma ComponentBehavior: Bound
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
    property bool dark: root.backend.initialDark
    property string pending: ""
    palette.window: dark ? "#23252a" : "#efefef"
    palette.windowText: dark ? "white" : "black"
    palette.base: dark ? "#191b1f" : "white"
    palette.text: dark ? "white" : "black"
    palette.button: dark ? "#32353c" : "#efefef"
    palette.buttonText: dark ? "white" : "black"
    palette.placeholderText: dark ? "#aeb3bd" : "#646464"
    palette.highlight: "#3278b8"
    onClosing: function (close) {
        root.backend.resetCancel();
        if (!root.backend.finishing && root.backend.dirty) {
            close.accepted = false;
            pending = "close";
            unsaved.open();
        } else
            root.backend.closeAccepted();
    }

    component ScenarioRow: RowLayout {
        id: scenario
        required property int index
        required property string scenarioName
        required property int scenarioPort
        required property bool scenarioEnabled
        width: ListView.view.width
        TextField {
            id: name
            Layout.fillWidth: true
            text: scenario.scenarioName
            onEditingFinished: root.backend.editScenario(scenario.index, 0, text)
        }
        TextField {
            text: scenario.scenarioPort
            Layout.preferredWidth: 110
            validator: IntValidator {
                bottom: 1
                top: 65535
            }
            onTextEdited: root.backend.editScenario(scenario.index, 1, text)
        }
        CheckBox {
            id: enabledInput
            Layout.preferredWidth: 64
            checked: scenario.scenarioEnabled
            onToggled: root.backend.editScenario(scenario.index, 2, checked)
        }
        Button {
            text: "Remove"
            Layout.preferredWidth: 100
            onClicked: {
                profileList.currentIndex = scenario.index;
                remove.clicked();
            }
        }
        function editForTest(value, active) {
            name.text = value;
            name.editingFinished();
            enabledInput.checked = active;
            enabledInput.toggled();
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        RowLayout {
            Button {
                id: start
                text: "Start"
                onClicked: root.backend.setRunning(true)
            }
            Button {
                id: stop
                text: "Stop"
                onClicked: root.backend.setRunning(false)
            }
            Button {
                id: reset
                objectName: "reset"
                text: root.backend.resetText
                Layout.preferredWidth: 160
                onPressed: root.backend.resetPress()
                onReleased: root.backend.resetCancel()
                onCanceled: root.backend.resetCancel()
                onPressedChanged: if (!pressed)
                    root.backend.resetCancel()
                onActiveFocusChanged: if (!activeFocus)
                    root.backend.resetCancel()
            }
            Button {
                id: mutate
                text: "Add/remove diagnostic branch"
                onClicked: root.backend.mutate()
            }
            Button {
                id: theme
                text: "Light / dark"
                onClicked: root.dark = !root.dark
            }
        }
        Label {
            text: root.backend.status
            Layout.fillWidth: true
        }
        TabBar {
            id: tabs
            Layout.fillWidth: true
            onCurrentIndexChanged: root.backend.pageChanged(currentIndex)
            TabButton {
                text: "Monitor"
            }
            TabButton {
                text: "Diagnostics"
            }
            TabButton {
                text: "Profile"
            }
        }
        StackLayout {
            Layout.fillHeight: true
            Layout.fillWidth: true
            currentIndex: tabs.currentIndex
            RowLayout {
                Image {
                    id: previewImage
                    source: root.backend.previewSource
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
                        model: root.backend.cards
                        spacing: 8
                        delegate: Frame {
                            id: card
                            required property string display
                            required property string summary
                            width: ListView.view.width
                            height: 84
                            ColumnLayout {
                                anchors.fill: parent
                                Label {
                                    text: card.display
                                    font.bold: true
                                }
                                Label {
                                    text: card.summary
                                    font.pixelSize: 13
                                }
                            }
                        }
                    }
                }
            }
            ColumnLayout {
                RowLayout {
                    Label {
                        text: "Scenario / Rule / Condition / Detector"
                        Layout.fillWidth: true
                    }
                    Label {
                        text: "Score / state"
                        Layout.preferredWidth: 180
                    }
                }
                TreeView {
                    id: tree
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: root.backend.diagnostics
                    columnWidthProvider: function (column) {
                        return column === 0 ? Math.max(300, width - 200) : 200;
                    }
                    delegate: TreeViewDelegate {
                        id: nodeDelegate
                        implicitHeight: 28
                        implicitWidth: 300
                        contentItem: Label {
                            // Deleted/recycled rows can briefly have no display role.
                            text: nodeDelegate.model?.display ?? ""
                            elide: Text.ElideRight
                        }
                    }
                    ScrollBar.vertical: ScrollBar {}
                    onExpanded: Qt.callLater(root.backend.expansionChanged)
                    onCollapsed: Qt.callLater(root.backend.expansionChanged)
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 124
                    clip: true
                    Row {
                        spacing: 8
                        Repeater {
                            id: referenceImages
                            model: root.backend.referenceSources
                            Image {
                                required property string modelData
                                source: modelData
                                cache: false
                                width: 160
                                height: 100
                                fillMode: Image.PreserveAspectFit
                            }
                        }
                    }
                }
            }
            ColumnLayout {
                RowLayout {
                    ComboBox {
                        model: ["Synthetic camera", "Synthetic file"]
                        currentIndex: root.backend.source
                        onActivated: root.backend.editSource(currentIndex)
                    }
                    TextField {
                        id: file
                        Layout.fillWidth: true
                        text: root.backend.file
                        placeholderText: "Mock source file path / 日本語入力"
                        onTextEdited: root.backend.editFile(text)
                    }
                    Button {
                        id: browse
                        text: "Browse..."
                        onClicked: fileDialog.open()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: "Scenario name"
                        Layout.fillWidth: true
                    }
                    Label {
                        text: "Port"
                        Layout.preferredWidth: 110
                    }
                    Label {
                        text: "Enabled"
                        Layout.preferredWidth: 64
                    }
                    Item {
                        Layout.preferredWidth: 100
                    }
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ListView {
                        id: profileList
                        model: root.backend.profiles
                        spacing: 4
                        delegate: ScenarioRow {}
                    }
                }
                RowLayout {
                    Button {
                        id: add
                        text: "Add Scenario"
                        onClicked: root.backend.addScenario()
                    }
                    Button {
                        id: remove
                        text: "Remove Scenario"
                        onClicked: root.backend.removeScenario(profileList.currentIndex)
                    }
                    Button {
                        id: apply
                        text: "Apply"
                        onClicked: root.backend.apply()
                    }
                    Button {
                        id: discard
                        text: "Discard"
                        onClicked: root.backend.discard()
                    }
                    Button {
                        id: fresh
                        text: "New Profile"
                        onClicked: {
                            if (root.backend.dirty) {
                                root.pending = "fresh";
                                unsaved.open();
                            } else
                                root.backend.fresh();
                        }
                    }
                    Label {
                        text: root.backend.dirty ? "Unapplied changes" : "Applied"
                    }
                }
                Label {
                    text: root.backend.errors
                    color: root.dark ? "#ffaaaa" : "#a00000"
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }
    }
    FileDialog {
        id: fileDialog
        title: "Select mock input source"
        nameFilters: ["Video files (*.avi *.mp4)", "All files (*)"]
        onAccepted: root.backend.selectFile(selectedFile)
        onRejected: root.backend.fileCancelled()
    }
    MessageDialog {
        id: unsaved
        title: "Unsaved Profile"
        text: "Discard unapplied changes?"
        buttons: MessageDialog.Discard | MessageDialog.Cancel
        onButtonClicked: function (button, role) {
            if (button === MessageDialog.Discard) {
                root.backend.discard();
                if (root.pending === "close")
                    root.close();
                else
                    root.backend.fresh();
            } else
                root.backend.discardCancelled();
        }
        onRejected: root.backend.discardCancelled()
    }
    Timer {
        id: cancelDialog
        interval: 250
        property string kind
        onTriggered: {
            if (kind === "file" && fileDialog.visible)
                fileDialog.reject();
            else if (kind === "unsaved" && unsaved.visible)
                unsaved.reject();
            else
                throw new Error("Test did not open the requested dialog");
        }
    }
    Timer {
        id: openUnsaved
        interval: 600
        onTriggered: {
            fresh.clicked();
            cancelDialog.kind = "unsaved";
            cancelDialog.restart();
        }
    }

    // Contract driver uses the same controls, model indexes and pointer delivery as the UI.
    function showPage(page) {
        tabs.currentIndex = page;
    }
    function expandedNodes() {
        let ids = [];
        for (let row = 0; row < tree.rows; ++row)
            if (tree.isExpanded(row))
                ids.push(root.backend.diagnostics.data(tree.index(row, 0), 256));
        return ids;
    }
    function visibleNodes() {
        let ids = [];
        for (let row = Math.max(0, tree.topRow); row <= tree.bottomRow; ++row)
            ids.push(root.backend.diagnostics.data(tree.index(row, 0), 256));
        return ids;
    }
    function topologyChanged() {
        Qt.callLater(function () {
            tree.forceLayout();
            root.backend.expansionChanged();
        });
    }
    function expandNode(index) {
        tree.expandToIndex(index);
        tree.forceLayout();
        tree.expand(tree.rowAtIndex(index));
        tree.forceLayout();
        root.backend.expansionChanged();
    }
    function collapseNode(index) {
        tree.collapse(tree.rowAtIndex(index));
        tree.forceLayout();
        root.backend.expansionChanged();
    }
    function viewProbe() {
        let ready = true;
        for (let i = 0; i < referenceImages.count; ++i)
            ready = ready && (referenceImages.itemAt(i) as Image)?.status === Image.Ready;
        return {
            scroll: tree.contentY,
            busy: fileDialog.visible || unsaved.visible || openUnsaved.running || cancelDialog.running,
            referenceCount: referenceImages.count,
            referencesReady: ready,
            previewReady: previewImage.status === Image.Ready && previewImage.paintedWidth > 0
        };
    }
    function editFirstForTest(value, enabled) {
        const row = profileList.itemAtIndex(0) as ScenarioRow;
        if (!row)
            throw new Error("First Profile delegate not visible");
        row.editForTest(value, enabled);
    }
    function testAction(action) {
        switch (action) {
        case "mutate":
            mutate.clicked();
            break;
        case "invalid_draft":
            editFirstForTest("", true);
            break;
        case "valid_draft":
            editFirstForTest("Edited scenario", false);
            break;
        case "apply":
            apply.clicked();
            break;
        case "add_scenario":
            add.clicked();
            break;
        case "remove_scenario":
            profileList.currentIndex = profileList.count - 1;
            remove.clicked();
            break;
        case "unsaved_cancel":
            editFirstForTest("Edited scenario", true);
            openUnsaved.restart();
            break;
        case "file_cancel":
            browse.clicked();
            cancelDialog.kind = "file";
            cancelDialog.restart();
            break;
        case "discard":
            discard.clicked();
            break;
        case "theme":
            theme.clicked();
            break;
        case "resize":
            root.width = 800;
            root.height = 600;
            break;
        case "start":
            start.clicked();
            break;
        case "stop":
            stop.clicked();
            break;
        case "scroll":
            for (let row = 0; row < tree.rows; ++row)
                if (tree.depth(row) === 0)
                    tree.expand(row);
            tree.forceLayout();
            tree.contentY = 2;
            root.backend.expansionChanged();
            break;
        default:
            throw new Error("Unhandled Qt Quick driver action: " + action);
        }
    }
}
