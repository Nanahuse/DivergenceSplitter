#include "app.hpp"
#include "dialog_test.hpp"
#include <QApplication>
#include <QCloseEvent>
#include <QComboBox>
#include <QFileDialog>
#include <QFocusEvent>
#include <QHeaderView>
#include <QImage>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPushButton>
#include <QScrollArea>
#include <QScrollBar>
#include <QStandardItemModel>
#include <QStyle>
#include <QTabWidget>
#include <QTableWidget>
#include <QTimer>
#include <QTreeView>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <algorithm>
#include <iostream>
#include <unordered_map>
#include <unordered_set>

using namespace comparison;
namespace {
QString text(const std::string& value) { return QString::fromUtf8(value); }
QImage image(const Image& value) {
    return QImage(value.rgba.data(), int(value.width), int(value.height),
        int(value.width * 4), QImage::Format_RGBA8888).copy();
}
class Window final : public QWidget, public Driver {
public:
    explicit Window(Session& session) : session_(session), script_(session) {
        setWindowTitle("DivergenceSplitter comparison - Qt Widgets");
        resize(1100, 760);
        auto layout = new QVBoxLayout(this);
        auto toolbar = new QHBoxLayout;
        auto start = button("Start", toolbar, [this] { session_.engine.set_running(true); });
        (void)start;
        button("Stop", toolbar, [this] { hold_.cancel(); session_.engine.set_running(false); });
        reset_ = new QPushButton("Hold 2s: Reset All"); toolbar->addWidget(reset_);
        connect(reset_, &QPushButton::pressed, this, [this] { hold_.press(std::chrono::steady_clock::now()); });
        connect(reset_, &QPushButton::released, this, [this] { hold_.cancel(); });
        reset_->installEventFilter(this);
        mutate_ = button("Add/remove diagnostic branch", toolbar, [this] {
            if (!session_.engine.mutate_topology()) status_->setText("Topology input busy");
        });
        theme_ = button("Light / dark", toolbar, [this] { toggle_theme(); });
        layout->addLayout(toolbar);
        status_ = new QLabel; layout->addWidget(status_);
        tabs_ = new QTabWidget; layout->addWidget(tabs_, 1);
        build_monitor(); build_diagnostics(); build_profile();
        connect(tabs_, &QTabWidget::currentChanged, this, [this](int page) {
            hold_.cancel();
            if (page != 1) release_diagnostics();
            else sync_tree();
        });
        timer_.setTimerType(Qt::PreciseTimer); timer_.setInterval(67);
        connect(&timer_, &QTimer::timeout, this, [this] { tick(); });
        timer_.start();
        session_.renderer = "Qt Widgets / raster / QStandardItemModel";
    }
    int result() const { return session_.error.empty() ? 0 : 1; }
    Probe probe() const override {
        Probe p;
        p.page = Page(tabs_->currentIndex()); p.dirty = session_.profile.dirty();
        p.errors = !error_->text().isEmpty(); p.references = references_.size();
        p.draft_count = session_.profile.draft.scenarios.size();
        p.scroll = tree_->verticalScrollBar()->value();
        p.file_cancels = file_cancels_; p.discard_cancels = discard_cancels_;
        if (auto found = items_.find(first_detector()); found != items_.end()) p.expanded = tree_->isExpanded(found->second->index());
        return p;
    }
    void perform(Action action) override {
        switch (action) {
        case Action::monitor: tabs_->setCurrentIndex(0); break;
        case Action::diagnostics: tabs_->setCurrentIndex(1); break;
        case Action::profile: tabs_->setCurrentIndex(2); break;
        case Action::expand:
        case Action::expand_dynamic: {
            auto found = items_.find(action == Action::expand ? first_detector() : session_.engine.state()->topology->nodes.back().id);
            if (found == items_.end()) break;
            std::vector<QModelIndex> path;
            for (auto index = found->second->index(); index.isValid(); index = index.parent()) path.push_back(index);
            for (auto it = path.rbegin(); it != path.rend(); ++it) tree_->expand(*it);
            break;
        }
        case Action::collapse:
            if (items_.contains(first_detector())) tree_->collapse(items_.at(first_detector())->index());
            break;
        case Action::mutate: mutate_->click(); break;
        case Action::invalid_draft: table_->item(0, 0)->setText(""); break;
        case Action::valid_draft: table_->item(0, 0)->setText("Edited scenario"); table_->item(0, 2)->setCheckState(Qt::Unchecked); break;
        case Action::apply: apply_->click(); break;
        case Action::add_scenario: add_->click(); break;
        case Action::remove_scenario: table_->selectRow(table_->rowCount() - 1); remove_->click(); break;
        case Action::file_cancel: {
            auto before = session_.profile.draft;
            CancelNativeDialog cancel(true); browse_->click();
            if (before != session_.profile.draft) throw std::runtime_error("File cancel changed draft");
            break;
        }
        case Action::unsaved_cancel:
            table_->item(0, 2)->setCheckState(Qt::Checked);
            QTimer::singleShot(50, this, [] {
                if (auto dialog = qobject_cast<QMessageBox*>(QApplication::activeModalWidget())) dialog->button(QMessageBox::Cancel)->click();
            });
            fresh_->click(); break;
        case Action::discard: discard_->click(); break;
        case Action::reset_press: {
            QMouseEvent event(QEvent::MouseButtonPress, QPointF(10, 10), QPointF(10, 10), QPointF(reset_->mapToGlobal(QPoint(10, 10))),
                Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
            QApplication::sendEvent(reset_, &event); break;
        }
        case Action::reset_release: {
            QMouseEvent event(QEvent::MouseButtonRelease, QPointF(10, 10), QPointF(10, 10), QPointF(reset_->mapToGlobal(QPoint(10, 10))),
                Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
            QApplication::sendEvent(reset_, &event); break;
        }
        case Action::reset_cancel: { QFocusEvent event(QEvent::FocusOut); QApplication::sendEvent(reset_, &event); break; }
        case Action::theme: theme_->click(); break;
        case Action::resize: resize(800, 600); break;
        case Action::start: session_.engine.set_running(true); break;
        case Action::stop: hold_.cancel(); session_.engine.set_running(false); break;
        case Action::scroll:
            for (const auto& node : session_.engine.state()->topology->nodes) if (node.kind == NodeKind::scenario) tree_->expand(items_.at(node.id)->index());
            tree_->doItemsLayout(); tree_->verticalScrollBar()->setValue(2); break;
        }
    }
protected:
    bool eventFilter(QObject* object, QEvent* event) override {
        if (object == reset_ && (event->type() == QEvent::FocusOut || event->type() == QEvent::WindowDeactivate)) hold_.cancel();
        return QWidget::eventFilter(object, event);
    }
    void closeEvent(QCloseEvent* event) override {
        hold_.cancel();
        if (!finishing_ && session_.profile.dirty() && !confirm_discard()) { event->ignore(); return; }
        timer_.stop(); release_diagnostics(); session_.engine.stop();
        QWidget::closeEvent(event);
    }
private:
    template<class F> QPushButton* button(const char* name, QHBoxLayout* layout, F callback) {
        auto widget = new QPushButton(name); layout->addWidget(widget);
        connect(widget, &QPushButton::clicked, this, std::move(callback)); return widget;
    }
    void build_monitor() {
        auto page = new QWidget; auto layout = new QHBoxLayout(page);
        preview_ = new QLabel("Waiting for frames"); preview_->setMinimumSize(320, 180);
        preview_->setAlignment(Qt::AlignCenter); layout->addWidget(preview_, 1);
        auto scroll = new QScrollArea; scroll->setWidgetResizable(true);
        auto cards = new QWidget; cards_ = new QVBoxLayout(cards); scroll->setWidget(cards);
        layout->addWidget(scroll, 1); tabs_->addTab(page, "Monitor");
    }
    void build_diagnostics() {
        auto page = new QWidget; auto layout = new QVBoxLayout(page);
        model_ = new QStandardItemModel(this);
        model_->setHorizontalHeaderLabels({"Scenario / Rule / Condition / Detector", "Score / state"});
        tree_ = new QTreeView; tree_->setModel(model_); tree_->setUniformRowHeights(true);
        tree_->header()->setSectionResizeMode(0, QHeaderView::Stretch); tree_->setColumnWidth(1, 160);
        layout->addWidget(tree_, 1);
        auto scroll = new QScrollArea; scroll->setFixedHeight(125); scroll->setWidgetResizable(true);
        auto content = new QWidget; reference_layout_ = new QHBoxLayout(content); scroll->setWidget(content);
        layout->addWidget(scroll); tabs_->addTab(page, "Diagnostics");
        connect(tree_, &QTreeView::expanded, this, [this] { refresh_references(); });
        connect(tree_, &QTreeView::collapsed, this, [this] { refresh_references(); });
    }
    void build_profile() {
        auto page = new QWidget; auto layout = new QVBoxLayout(page);
        auto source_row = new QHBoxLayout;
        source_ = new QComboBox; source_->addItems({"Synthetic camera", "Synthetic file"}); source_row->addWidget(source_);
        file_ = new QLineEdit; file_->setPlaceholderText("Mock source file path"); source_row->addWidget(file_, 1);
        browse_ = button("Browse...", source_row, [this] {
            auto selected = QFileDialog::getOpenFileName(this, "Select mock input source", {}, "Video files (*.avi *.mp4);;All files (*)");
            if (!selected.isEmpty()) { source_->setCurrentIndex(1); file_->setText(selected); }
            else ++file_cancels_;
        });
        layout->addLayout(source_row);
        table_ = new QTableWidget; table_->setColumnCount(3); table_->setHorizontalHeaderLabels({"Scenario name", "Port", "Enabled"});
        table_->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch); layout->addWidget(table_, 1);
        auto buttons = new QHBoxLayout;
        add_ = button("Add Scenario", buttons, [this] { session_.profile.add_scenario(); sync_form(); table_->selectRow(table_->rowCount() - 1); });
        remove_ = button("Remove Scenario", buttons, [this] {
            auto row = table_->currentRow();
            if (row >= 0 && row < int(session_.profile.draft.scenarios.size())) {
                session_.profile.remove_scenario(session_.profile.draft.scenarios[std::size_t(row)].id); sync_form();
            }
        });
        apply_ = button("Apply", buttons, [this] {
            auto errors = session_.profile.apply();
            if (errors.empty()) errors = session_.engine.apply_profile(session_.profile.applied());
            QStringList messages; for (const auto& message : errors) messages.append(text(message));
            error_->setText(messages.join("; "));
        });
        discard_ = button("Discard", buttons, [this] { session_.profile.discard(); sync_form(); error_->clear(); });
        fresh_ = button("New Profile", buttons, [this] {
            if (!session_.profile.dirty() || confirm_discard()) { session_.profile.draft = Profile{}; sync_form(); }
        });
        layout->addLayout(buttons); error_ = new QLabel; error_->setWordWrap(true); layout->addWidget(error_);
        connect(source_, &QComboBox::currentIndexChanged, this, [this](int index) { if (!syncing_) session_.profile.draft.source = Source(index); });
        connect(file_, &QLineEdit::textChanged, this, [this](const QString& value) { if (!syncing_) session_.profile.draft.file = value.toUtf8().toStdString(); });
        connect(table_, &QTableWidget::itemChanged, this, [this](QTableWidgetItem* item) {
            if (syncing_) return;
            auto& row = session_.profile.draft.scenarios.at(std::size_t(item->row()));
            if (item->column() == 0) row.name = item->text().toUtf8().toStdString();
            else if (item->column() == 1) { bool ok = false; row.port = item->text().toInt(&ok); if (!ok) row.port = 0; }
            else row.enabled = item->checkState() == Qt::Checked;
        });
        tabs_->addTab(page, "Profile"); sync_form();
    }
    void sync_form() {
        syncing_ = true;
        source_->setCurrentIndex(int(session_.profile.draft.source)); file_->setText(text(session_.profile.draft.file));
        table_->setRowCount(int(session_.profile.draft.scenarios.size()));
        for (int i = 0; i < table_->rowCount(); ++i) {
            const auto& row = session_.profile.draft.scenarios[std::size_t(i)];
            table_->setItem(i, 0, new QTableWidgetItem(text(row.name))); table_->setItem(i, 1, new QTableWidgetItem(QString::number(row.port)));
            auto enabled = new QTableWidgetItem; enabled->setFlags(Qt::ItemIsEnabled | Qt::ItemIsUserCheckable | Qt::ItemIsSelectable);
            enabled->setCheckState(row.enabled ? Qt::Checked : Qt::Unchecked); table_->setItem(i, 2, enabled);
        }
        syncing_ = false;
    }
    bool confirm_discard() {
        const auto answer = QMessageBox::question(this, "Unsaved Profile", "Discard unapplied changes?",
            QMessageBox::Discard | QMessageBox::Cancel, QMessageBox::Cancel);
        if (answer == QMessageBox::Cancel) ++discard_cancels_;
        return answer == QMessageBox::Discard;
    }
    NodeId first_detector() const {
        for (const auto& node : session_.engine.state()->topology->nodes) if (node.kind == NodeKind::detector) return node.id;
        return 0;
    }
    bool expanded_and_visible(NodeId id) const {
        auto found = items_.find(id); if (found == items_.end()) return false;
        for (auto index = found->second->index(); index.isValid(); index = index.parent()) if (!tree_->isExpanded(index)) return false;
        return true;
    }
    void refresh_references() {
        if (tabs_->currentIndex() != 1 || !shown_) return;
        std::unordered_set<NodeId> wanted;
        for (const auto& node : shown_->nodes) {
            if (node.kind != NodeKind::detector || !expanded_and_visible(node.id)) continue;
            wanted.insert(node.id);
            if (!references_.contains(node.id)) {
                auto label = new QLabel; label->setPixmap(QPixmap::fromImage(image(reference_image(session_.engine, node.id, shown_))));
                reference_layout_->addWidget(label); references_[node.id] = label;
            }
        }
        std::erase_if(references_, [&](auto& pair) { if (wanted.contains(pair.first)) return false; delete pair.second; return true; });
    }
    void release_diagnostics() {
        for (auto& pair : references_) delete pair.second;
        references_.clear(); items_.clear(); shown_.reset(); model_->removeRows(0, model_->rowCount());
    }
    void erase_items(QStandardItem* item) {
        items_.erase(item->data(Qt::UserRole).toULongLong());
        for (int row = 0; row < item->rowCount(); ++row) erase_items(item->child(row));
    }
    void sync_tree() {
        auto state = session_.engine.state();
        if (state->topology == shown_) return;
        ++session_.counters.topology_builds;
        std::unordered_set<NodeId> wanted;
        for (const auto& node : state->topology->nodes) wanted.insert(node.id);
        if (shown_) {
            for (const auto& node : shown_->nodes) {
                if (wanted.contains(node.id) || (node.parent && !wanted.contains(node.parent))) continue;
                auto item = items_.at(node.id); auto parent = item->parent(); auto row = item->row();
                erase_items(item); (parent ? parent : model_->invisibleRootItem())->removeRow(row);
            }
        }
        for (const auto& node : state->topology->nodes) {
            if (items_.contains(node.id)) { items_.at(node.id)->setText(text(node.label)); continue; }
            auto label = new QStandardItem(text(node.label)); label->setEditable(false);
            label->setData(QVariant::fromValue<qulonglong>(node.id), Qt::UserRole);
            auto value = new QStandardItem; value->setEditable(false);
            auto parent = node.parent ? items_.at(node.parent) : model_->invisibleRootItem();
            parent->appendRow({label, value}); items_[node.id] = label;
            if (node.kind == NodeKind::detector) label->appendRow({new QStandardItem("Reference shown below"), new QStandardItem});
        }
        shown_ = state->topology; refresh_references();
    }
    void update_values(const State& state) {
        std::unordered_map<NodeId, const Metric*> metrics;
        for (const auto& metric : state.metrics) metrics[metric.id] = &metric;
        auto index = tree_->indexAt({3, 3});
        for (; index.isValid(); index = tree_->indexBelow(index)) {
            if (tree_->visualRect(index).top() > tree_->viewport()->height()) break;
            const auto id = index.data(Qt::UserRole).toULongLong();
            if (auto found = metrics.find(id); found != metrics.end()) {
                const auto& metric = *found->second;
                model_->setData(index.siblingAtColumn(1), text(score_text(metric.score) + (!metric.enabled ? " disabled" : metric.active ? " active" : " waiting")));
            }
        }
        ++session_.counters.value_updates;
    }
    void toggle_theme() {
        dark_ = !dark_;
        QPalette palette;
        if (dark_) {
            palette.setColor(QPalette::Window, QColor(35, 37, 42)); palette.setColor(QPalette::WindowText, Qt::white);
            palette.setColor(QPalette::Base, QColor(25, 27, 31)); palette.setColor(QPalette::AlternateBase, QColor(40, 42, 47));
            palette.setColor(QPalette::Text, Qt::white); palette.setColor(QPalette::Button, QColor(50, 53, 60)); palette.setColor(QPalette::ButtonText, Qt::white);
        } else palette = QApplication::style()->standardPalette();
        QApplication::setPalette(palette);
    }
    void tick() {
        try {
            const auto now = std::chrono::steady_clock::now();
            if (hold_.poll(now)) session_.engine.reset_all();
            reset_->setText(text("Reset All " + std::to_string(int(hold_.progress(now) * 100)) + "%"));
            auto state = session_.engine.state();
            status_->setText(text(std::string(state->running ? "Running" : "Stopped") + " | sequence " + std::to_string(state->sequence) + " | reset " + std::to_string(state->resets)));
            if (tabs_->currentIndex() == 0) {
                if (auto frame = session_.engine.frame()) {
                    preview_->setPixmap(QPixmap::fromImage(image(frame->image)).scaled(preview_->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
                    session_.observe_frame(*frame);
                }
                if (cards_topology_ != state->topology) {
                    for (auto label : card_labels_) delete label;
                    card_labels_.clear();
                    for (const auto& scenario : state->applied_profile->scenarios) {
                        auto label = new QLabel; label->setFrameStyle(QFrame::StyledPanel); label->setMinimumHeight(60);
                        cards_->addWidget(label); card_labels_.push_back(label);
                    }
                    cards_topology_ = state->topology;
                }
                std::size_t card = 0;
                for (std::size_t i = 0; i < state->topology->nodes.size(); ++i) if (state->topology->nodes[i].kind == NodeKind::scenario) {
                    const auto& metric = state->metrics[i];
                    card_labels_.at(card++)->setText(text(state->topology->nodes[i].label + "\n" + (!metric.enabled ? "Disabled" : metric.connected ? "Connected" : "Disconnected") + " | " + score_text(metric.score)));
                }
            } else if (tabs_->currentIndex() == 1) { sync_tree(); update_values(*state); }
            session_.sample_process(); session_.exercise(*this);
            if ((session_.options.self_test && script_.tick(*this)) || session_.expired()) finish();
        } catch (const std::exception& error) { session_.error = error.what(); finish(); }
    }
    void finish() {
        if (finishing_) return;
        finishing_ = true; timer_.stop();
        try {
            if (!session_.options.capture.empty() && !grab().save(text(session_.options.capture.string()))) throw std::runtime_error("Window capture failed");
        } catch (const std::exception& error) { session_.error = error.what(); }
        release_diagnostics(); session_.engine.stop();
        try { session_.write_report(); } catch (const std::exception& error) { session_.error = error.what(); std::cerr << error.what() << '\n'; }
        close();
    }
    Session& session_; ContractScript script_; ResetHold hold_; QTimer timer_;
    QTabWidget* tabs_{}; QLabel *status_{}, *preview_{}, *error_{};
    QVBoxLayout* cards_{}; std::vector<QLabel*> card_labels_;
    QTreeView* tree_{}; QStandardItemModel* model_{}; QHBoxLayout* reference_layout_{};
    QTableWidget* table_{}; QComboBox* source_{}; QLineEdit* file_{};
    QPushButton *reset_{}, *mutate_{}, *theme_{}, *apply_{}, *add_{}, *remove_{}, *browse_{}, *discard_{}, *fresh_{};
    std::unordered_map<NodeId, QStandardItem*> items_;
    std::unordered_map<NodeId, QLabel*> references_;
    std::shared_ptr<const Topology> shown_, cards_topology_;
    bool syncing_ = false, finishing_ = false, dark_ = false;
    unsigned file_cancels_ = 0, discard_cancels_ = 0;
};
}
int main(int argc, char** argv) {
    try {
        auto options = Options::parse(argc, argv);
        QApplication app(argc, argv); QApplication::setStyle("Fusion");
        Session session(std::move(options), "qt");
        Window window(session); window.show(); app.exec();
        return window.result();
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
