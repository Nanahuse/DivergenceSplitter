#include "app.hpp"
#include "runtime_check.hpp"
#include <QGuiApplication>
#include <QJSValue>
#include <QMouseEvent>
#include <QQmlApplicationEngine>
#include <QQmlError>
#include <QQuickImageProvider>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QSGRendererInterface>
#include <QStandardItemModel>
#include <QTimer>
#include <QUrl>
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

// Synchronous image requests run on the GUI thread; returned images own their pixels.
class Images final : public QQuickImageProvider {
public:
    Images() : QQuickImageProvider(QQuickImageProvider::Image) {}
    QImage preview;
    std::unordered_map<NodeId, QImage> references;
    QImage requestImage(const QString& id, QSize* size, const QSize&) override {
        QImage result;
        if (id.startsWith("preview/")) result = preview;
        else if (auto it = references.find(id.section('/', 1, 1).toULongLong()); it != references.end()) result = it->second;
        if (size) *size = result.size();
        return result;
    }
};

class ProfileModel final : public QAbstractListModel {
public:
    explicit ProfileModel(ProfileEditor& editor) : editor_(editor) {}
    enum { Name = Qt::UserRole + 1, Port, Enabled };
    QHash<int, QByteArray> roleNames() const override {
        return {{Name, "scenarioName"}, {Port, "scenarioPort"}, {Enabled, "scenarioEnabled"}};
    }
    int rowCount(const QModelIndex& parent = {}) const override {
        return parent.isValid() ? 0 : int(editor_.draft.scenarios.size());
    }
    QVariant data(const QModelIndex& index, int role) const override {
        if (!index.isValid() || index.row() >= rowCount()) return {};
        const auto& row = editor_.draft.scenarios.at(std::size_t(index.row()));
        if (role == Name) return text(row.name);
        if (role == Port) return row.port;
        if (role == Enabled) return row.enabled;
        return {};
    }
    void edit(int row, int role, const QVariant& value) {
        if (row < 0 || row >= rowCount()) return;
        auto& item = editor_.draft.scenarios.at(std::size_t(row));
        if (role == Name) item.name = value.toString().toUtf8().toStdString();
        if (role == Port) item.port = value.toInt();
        if (role == Enabled) item.enabled = value.toBool();
        emit dataChanged(index(row), index(row), {role});
    }
    template<class F> void reset(F action) { beginResetModel(); action(); endResetModel(); }
    void add() {
        const auto row = rowCount(); beginInsertRows({}, row, row);
        editor_.add_scenario(); endInsertRows();
    }
    void remove(int row) {
        if (row < 0 || row >= rowCount()) return;
        beginRemoveRows({}, row, row);
        editor_.remove_scenario(editor_.draft.scenarios.at(std::size_t(row)).id);
        endRemoveRows();
    }
private:
    ProfileEditor& editor_;
};

class Controller final : public QObject, public Driver {
    Q_OBJECT
    Q_PROPERTY(QAbstractItemModel* diagnostics READ diagnostics CONSTANT)
    Q_PROPERTY(QAbstractItemModel* cards READ cards CONSTANT)
    Q_PROPERTY(QAbstractItemModel* profiles READ profiles CONSTANT)
    Q_PROPERTY(QString status READ status NOTIFY frameChanged)
    Q_PROPERTY(QString previewSource READ previewSource NOTIFY frameChanged)
    Q_PROPERTY(QString resetText READ resetText NOTIFY frameChanged)
    Q_PROPERTY(QStringList referenceSources READ referenceSources NOTIFY referencesChanged)
    Q_PROPERTY(bool dirty READ dirty NOTIFY formChanged)
    Q_PROPERTY(QString errors READ errors NOTIFY formChanged)
    Q_PROPERTY(int source READ source NOTIFY formChanged)
    Q_PROPERTY(QString file READ file NOTIFY formChanged)
    Q_PROPERTY(bool initialDark READ initialDark CONSTANT)
    Q_PROPERTY(bool finishing READ finishing NOTIFY finishingChanged)
public:
    explicit Controller(Session& session, Images& images)
        : session_(session), script_(session), images_(images), profiles_(session.profile) {
        cards_.setItemRoleNames({{Qt::DisplayRole, "display"}, {Qt::UserRole + 1, "summary"}});
        tree_.setColumnCount(2);
        timer_.setTimerType(Qt::PreciseTimer); timer_.setInterval(67);
        connect(&timer_, &QTimer::timeout, this, [this] { tick(); });
    }
    void attach(QQuickWindow* window) {
        window_ = window;
        connect(window, &QWindow::activeChanged, this, [this] { if (!window_->isActive()) hold_.cancel(); });
        timer_.start();
    }
    int result() const { return session_.error.empty() ? 0 : 1; }
    QAbstractItemModel* diagnostics() { return &tree_; }
    QAbstractItemModel* cards() { return &cards_; }
    QAbstractItemModel* profiles() { return &profiles_; }
    QString status() const { return status_; }
    QString previewSource() const { return preview_; }
    QString resetText() const { return reset_text_; }
    QStringList referenceSources() const { return reference_sources_; }
    bool dirty() const { return session_.profile.dirty(); }
    QString errors() const { return errors_; }
    int source() const { return int(session_.profile.draft.source); }
    QString file() const { return text(session_.profile.draft.file); }
    bool initialDark() const { return session_.options.dark; }
    bool finishing() const { return finishing_; }

    Q_INVOKABLE void pageChanged(int page) {
        hold_.cancel(); page_ = Page(page);
        if (page_ == Page::diagnostics) sync_tree(); else release_diagnostics();
    }
    Q_INVOKABLE void setRunning(bool running) { hold_.cancel(); session_.engine.set_running(running); }
    Q_INVOKABLE void mutate() { (void)session_.engine.mutate_topology(); }
    Q_INVOKABLE void resetPress() { hold_.press(std::chrono::steady_clock::now()); }
    Q_INVOKABLE void resetCancel() { hold_.cancel(); }
    Q_INVOKABLE void editScenario(int row, int field, const QVariant& value) {
        profiles_.edit(row, ProfileModel::Name + field, value); emit formChanged();
    }
    Q_INVOKABLE void editSource(int value) { session_.profile.draft.source = Source(value); emit formChanged(); }
    Q_INVOKABLE void editFile(const QString& value) { session_.profile.draft.file = value.toUtf8().toStdString(); emit formChanged(); }
    Q_INVOKABLE void selectFile(const QUrl& value) { editSource(1); editFile(value.toLocalFile()); }
    Q_INVOKABLE void addScenario() { profiles_.add(); emit formChanged(); }
    Q_INVOKABLE void removeScenario(int row) { profiles_.remove(row); emit formChanged(); }
    Q_INVOKABLE void apply() {
        auto errors = session_.profile.apply();
        if (errors.empty()) errors = session_.engine.apply_profile(session_.profile.applied());
        QStringList messages; for (const auto& message : errors) messages.append(text(message));
        errors_ = messages.join("; "); emit formChanged();
    }
    Q_INVOKABLE void discard() {
        profiles_.reset([this] { session_.profile.discard(); }); errors_.clear(); emit formChanged();
    }
    Q_INVOKABLE void fresh() {
        profiles_.reset([this] { session_.profile.draft = Profile{}; }); errors_.clear(); emit formChanged();
    }
    Q_INVOKABLE void fileCancelled() { ++file_cancels_; }
    Q_INVOKABLE void discardCancelled() { ++discard_cancels_; }
    Q_INVOKABLE void expansionChanged() {
        expanded_.clear();
        for (const auto& id : call("expandedNodes").toList()) expanded_.insert(id.toULongLong());
        refresh_references();
    }
    Q_INVOKABLE void closeAccepted() {
        timer_.stop(); hold_.cancel(); release_diagnostics(); session_.engine.stop();
    }

    Probe probe() const override {
        Probe p;
        p.page = page_; p.dirty = dirty(); p.errors = !errors_.isEmpty();
        p.references = images_.references.size(); p.draft_count = session_.profile.draft.scenarios.size();
        p.expanded = expanded_.contains(first_detector());
        auto values = call("viewProbe").toMap();
        if (values.value("referenceCount").toULongLong() != p.references || !values.value("referencesReady").toBool())
            throw std::runtime_error("Qt Quick reference delegates do not match image ownership");
        p.scroll = qRound(values.value("scroll").toDouble()); p.busy = values.value("busy").toBool();
        p.file_cancels = file_cancels_; p.discard_cancels = discard_cancels_;
        return p;
    }
    void perform(Action action) override {
        switch (action) {
        case Action::monitor: call("showPage", 0); break;
        case Action::diagnostics: call("showPage", 1); break;
        case Action::profile: call("showPage", 2); break;
        case Action::expand:
        case Action::expand_dynamic: {
            auto id = action == Action::expand ? first_detector() : session_.engine.state()->topology->nodes.back().id;
            if (items_.contains(id)) call("expandNode", QVariant::fromValue(items_.at(id)->index()));
            break;
        }
        case Action::collapse:
            if (items_.contains(first_detector())) call("collapseNode", QVariant::fromValue(items_.at(first_detector())->index()));
            break;
        case Action::reset_press: mouse(QEvent::MouseButtonPress); break;
        case Action::reset_release: mouse(QEvent::MouseButtonRelease); break;
        case Action::reset_cancel: {
            if (auto item = window_->findChild<QQuickItem*>("reset")) item->ungrabMouse();
            break;
        }
        default: {
            static constexpr std::pair<Action, const char*> names[] = {
                {Action::mutate, "mutate"}, {Action::invalid_draft, "invalid_draft"},
                {Action::valid_draft, "valid_draft"}, {Action::apply, "apply"},
                {Action::add_scenario, "add_scenario"}, {Action::remove_scenario, "remove_scenario"},
                {Action::unsaved_cancel, "unsaved_cancel"}, {Action::file_cancel, "file_cancel"},
                {Action::discard, "discard"}, {Action::theme, "theme"}, {Action::resize, "resize"},
                {Action::start, "start"}, {Action::stop, "stop"}, {Action::scroll, "scroll"}};
            const auto found = std::find_if(std::begin(names), std::end(names), [&](const auto& pair) { return pair.first == action; });
            if (found == std::end(names)) throw std::runtime_error("Unhandled Qt Quick driver action");
            call("testAction", QString::fromLatin1(found->second)); break;
        }
        }
    }
signals:
    void frameChanged();
    void referencesChanged();
    void formChanged();
    void finishingChanged();
private:
    QVariant call(const char* method) const {
        QVariant result;
        if (window_) QMetaObject::invokeMethod(window_, method, Q_RETURN_ARG(QVariant, result));
        return result.metaType() == QMetaType::fromType<QJSValue>() ? result.value<QJSValue>().toVariant() : result;
    }
    QVariant call(const char* method, const QVariant& argument) const {
        QVariant result;
        if (window_) QMetaObject::invokeMethod(window_, method, Q_RETURN_ARG(QVariant, result), Q_ARG(QVariant, argument));
        return result.metaType() == QMetaType::fromType<QJSValue>() ? result.value<QJSValue>().toVariant() : result;
    }
    void mouse(QEvent::Type type) {
        auto item = window_->findChild<QQuickItem*>("reset");
        if (!item) throw std::runtime_error("Reset control missing");
        const auto position = item->mapToScene({item->width() / 2, item->height() / 2});
        QMouseEvent event(type, position, position, window_->mapToGlobal(position.toPoint()),
            Qt::LeftButton, type == QEvent::MouseButtonPress ? Qt::LeftButton : Qt::NoButton, Qt::NoModifier);
        QCoreApplication::sendEvent(window_, &event);
    }
    NodeId first_detector() const {
        for (const auto& node : session_.engine.state()->topology->nodes) if (node.kind == NodeKind::detector) return node.id;
        return 0;
    }
    void refresh_references() {
        if (!shown_ || page_ != Page::diagnostics) return;
        std::unordered_set<NodeId> wanted;
        for (const auto& node : shown_->nodes) {
            if (node.kind != NodeKind::detector || !expanded_.contains(node.id)) continue;
            wanted.insert(node.id);
            if (!images_.references.contains(node.id)) images_.references[node.id] = image(reference_image(session_.engine, node.id, shown_));
        }
        std::erase_if(images_.references, [&](const auto& pair) { return !wanted.contains(pair.first); });
        QStringList sources;
        for (const auto& node : shown_->nodes) if (wanted.contains(node.id)) sources.append("image://frames/ref/" + QString::number(node.id));
        if (sources != reference_sources_) { reference_sources_ = sources; emit referencesChanged(); }
    }
    void release_diagnostics() {
        images_.references.clear(); expanded_.clear(); reference_sources_.clear(); emit referencesChanged();
        items_.clear(); shown_.reset(); tree_.removeRows(0, tree_.rowCount());
    }
    void erase_items(QStandardItem* item) {
        items_.erase(item->data(Qt::UserRole).toULongLong());
        for (int row = 0; row < item->rowCount(); ++row) erase_items(item->child(row));
    }
    void sync_tree() {
        const auto state = session_.engine.state();
        if (state->topology == shown_) return;
        ++session_.counters.topology_builds;
        std::unordered_set<NodeId> wanted;
        for (const auto& node : state->topology->nodes) wanted.insert(node.id);
        if (shown_) for (const auto& node : shown_->nodes) {
            if (wanted.contains(node.id) || (node.parent && !wanted.contains(node.parent))) continue;
            auto item = items_.at(node.id); auto parent = item->parent(); const auto row = item->row();
            erase_items(item); (parent ? parent : tree_.invisibleRootItem())->removeRow(row);
        }
        for (const auto& node : state->topology->nodes) {
            if (items_.contains(node.id)) { items_.at(node.id)->setText(text(node.label)); continue; }
            auto label = new QStandardItem(text(node.label)); label->setEditable(false);
            // TreeView flattens the hierarchy into one table with a uniform column count.
            // Set child columns before attaching the item, avoiding live column insertion.
            label->setColumnCount(2);
            label->setData(QVariant::fromValue<qulonglong>(node.id), Qt::UserRole);
            if (node.kind == NodeKind::detector) label->appendRow({new QStandardItem("Reference shown below"), new QStandardItem(QStringLiteral(""))});
            auto parent = node.parent ? items_.at(node.parent) : tree_.invisibleRootItem();
            parent->appendRow({label, new QStandardItem(QStringLiteral(""))}); items_[node.id] = label;
        }
        shown_ = state->topology;
        // TreeView keeps surviving model indexes; expansion is sampled after its layout.
        call("topologyChanged"); refresh_references();
    }
    void update_values(const State& state) {
        std::unordered_map<NodeId, const Metric*> metrics;
        for (const auto& metric : state.metrics) metrics[metric.id] = &metric;
        for (const auto& value : call("visibleNodes").toList()) {
            const auto id = value.toULongLong();
            if (!items_.contains(id) || !metrics.contains(id)) continue;
            const auto& metric = *metrics.at(id);
            tree_.setData(items_.at(id)->index().siblingAtColumn(1),
                text(score_text(metric.score) + (!metric.enabled ? " disabled" : metric.active ? " active" : " waiting")));
        }
        ++session_.counters.value_updates;
    }
    void update_cards(const State& state) {
        int row = 0;
        for (const auto& node : state.topology->nodes) {
            if (node.kind != NodeKind::scenario) continue;
            if (row == cards_.rowCount()) {
                auto card = new QStandardItem(text(node.label));
                card->setData(QStringLiteral(""), Qt::UserRole + 1); cards_.appendRow(card);
            }
            auto item = cards_.item(row++); item->setText(text(node.label));
            const auto metric = std::find_if(state.metrics.begin(), state.metrics.end(), [&](const auto& m) { return m.id == node.id; });
            if (metric != state.metrics.end()) item->setData(text(score_text(metric->score) + (!metric->enabled ? " disabled" : metric->active ? " active" : " waiting") +
                (metric->connected ? " | connected" : " | disconnected")), Qt::UserRole + 1);
        }
        if (cards_.rowCount() > row) cards_.removeRows(row, cards_.rowCount() - row);
    }
    void finish() {
        if (finishing_) return;
        finishing_ = true; emit finishingChanged();
        try {
            if (session_.options.self_test && session_.error.empty()) {
                if (!call("viewProbe").toMap().value("previewReady").toBool())
                    throw std::runtime_error("Qt Quick preview did not load through the image provider");
                session_.checks.push_back("Q02_qml_preview_and_reference_delegates");
            }
            auto engine = qmlEngine(window_);
            if (!engine) throw std::runtime_error("Qt Quick engine missing");
            if (verify_quick_distribution(*engine)) session_.checks.push_back("Q01_packaged_qml_imports_and_runtime");
        } catch (const std::exception& error) { session_.error = error.what(); }
        if (!session_.options.capture.empty() && !window_->grabWindow().save(QString::fromStdWString(session_.options.capture.wstring())))
            session_.error = "Could not capture Qt Quick window";
        const auto api = window_->rendererInterface()->graphicsApi();
        const auto renderer = api == QSGRendererInterface::Direct3D11 ? "Direct3D11" :
            api == QSGRendererInterface::Direct3D12 ? "Direct3D12" :
            api == QSGRendererInterface::Software ? "software" : "API " + std::to_string(int(api));
        session_.renderer = "Qt Quick / QML TreeView / " + std::string(renderer);
        closeAccepted(); session_.write_report(); window_->close(); QCoreApplication::quit();
    }
    void tick() {
        try {
            const auto now = std::chrono::steady_clock::now();
            if (hold_.poll(now)) session_.engine.reset_all();
            reset_text_ = "Reset All " + QString::number(int(hold_.progress(now) * 100)) + "%";
            const auto state = session_.engine.state();
            status_ = text(std::string(state->running ? "Running" : "Stopped") + " | sequence " + std::to_string(state->sequence) + " | reset " + std::to_string(state->resets));
            if (page_ == Page::monitor) {
                if (auto frame = session_.engine.frame()) {
                    images_.preview = image(frame->image);
                    preview_ = "image://frames/preview/" + QString::number(frame->sequence);
                    session_.observe_frame(*frame);
                }
                update_cards(*state);
            } else if (page_ == Page::diagnostics) { sync_tree(); update_values(*state); }
            emit frameChanged();
            session_.sample_process(); session_.exercise(*this);
            if (session_.options.self_test ? script_.tick(*this) : session_.expired()) finish();
        } catch (const std::exception& error) { session_.error = error.what(); finish(); }
    }
    Session& session_;
    ContractScript script_;
    Images& images_; // Owned by the QML engine, which is destroyed before this controller.
    ProfileModel profiles_;
    QStandardItemModel tree_, cards_;
    std::unordered_map<NodeId, QStandardItem*> items_;
    std::unordered_set<NodeId> expanded_;
    std::shared_ptr<const Topology> shown_;
    QQuickWindow* window_ = nullptr;
    QTimer timer_;
    ResetHold hold_;
    Page page_ = Page::monitor;
    QString status_, preview_, reset_text_ = "Hold 2s: Reset All", errors_;
    QStringList reference_sources_;
    unsigned file_cancels_ = 0, discard_cancels_ = 0;
    bool finishing_ = false;
};
}

int main(int argc, char** argv) {
    try {
        const auto options = Options::parse(argc, argv);
        qputenv("QT_FORCE_STDERR_LOGGING", "1");
        QGuiApplication app(argc, argv);
        QQuickStyle::setStyle("Fusion");
        Session session(options, "qtquick");
        auto images = new Images;
        Controller controller(session, *images);
        QQmlApplicationEngine engine;
        QObject::connect(&engine, &QQmlEngine::warnings, &controller, [&session](const QList<QQmlError>& errors) {
            if (!errors.empty() && session.error.empty()) session.error = errors.first().toString().toStdString();
        });
        engine.addImageProvider("frames", images);
        engine.setInitialProperties({{"backend", QVariant::fromValue(&controller)}});
        engine.loadFromModule("Comparison", "Main");
        if (engine.rootObjects().isEmpty()) throw std::runtime_error("Qt Quick QML root failed to load");
        auto window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
        if (!window) throw std::runtime_error("QML root must be a window");
        controller.attach(window);
        const auto result = app.exec();
        return result ? result : controller.result();
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
#include "main.moc"
