#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QLabel>
#include <QLineEdit>
#include <QFile>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QSignalSpy>
#include <QStackedWidget>
#include <QStringList>
#include <QTabWidget>
#include <QToolButton>
#include <QTemporaryDir>
#include <QTest>
#include <QTimer>
#include <QSpinBox>
#include <QTableWidget>
#include <QDir>
#include <QFontDatabase>
#include <QFrame>

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include <fstream>
#include <atomic>
#include <thread>

#include "app_controller.hpp"
#include "image_view.hpp"
#include "main_window.hpp"
#include "navigation_bar.hpp"
#include "profile_header.hpp"
#include "profile_page.hpp"
#include "reset_all_button.hpp"
#include "monitor_page.hpp"
#include "theme.hpp"
#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"
#include "divergencesplitter/capture/ndi.hpp"

#if DIVERGENCESPLITTER_ENABLE_NDI
#include <windows.h>
#include <Processing.NDI.Lib.h>
#include <Processing.NDI.DynamicLoad.h>
#endif

using namespace divergencesplitter::ui;
using namespace divergencesplitter;

namespace {
struct PreviewProbe {
    std::atomic_int opens{}, closes{};
    std::atomic_bool active{}, wrong_thread{}, paused{};
    std::thread::id gui_thread{std::this_thread::get_id()};
};
class PreviewSource final : public FrameSource {
public:
    explicit PreviewSource(std::shared_ptr<PreviewProbe> probe) : probe_(std::move(probe)) {}
    void open() override { check_thread(); ++probe_->opens; probe_->active = true; }
    cv::Mat read(MonotonicTime& at) override {
        check_thread();
        std::this_thread::sleep_for(std::chrono::milliseconds{5});
        at = monotonic_now();
        if (probe_->paused.load()) return {};
        cv::Mat image(4, 8, CV_8UC3, cv::Scalar::all(10));
        image.colRange(4, 8).setTo(cv::Scalar::all(240));
        return image;
    }
    void close() noexcept override {
        check_thread();
        if (probe_->active.exchange(false)) ++probe_->closes;
    }
    std::string describe() const override { return "preview fixture"; }
    Format opened_format() const override { return {8, 4, 60.0}; }
private:
    void check_thread() const { if (std::this_thread::get_id() == probe_->gui_thread) probe_->wrong_thread = true; }
    std::shared_ptr<PreviewProbe> probe_;
};
}

class UiTests final : public QObject {
    Q_OBJECT

    QTemporaryDir settings_directory_;
    QByteArray previous_appdata_;
    QByteArray previous_xdg_config_;

    static QPushButton* button(ProfilePage& page, const QString& text) {
        for (auto* candidate : page.findChildren<QPushButton*>()) {
            if (candidate->text() == text) {
                return candidate;
            }
        }
        return nullptr;
    }

    static Profile make_profile(const QTemporaryDir& directory, bool enabled, bool alpha = false) {
        const std::filesystem::path root{directory.path().toStdString()};
        cv::Mat image(2, 2, alpha ? CV_8UC4 : CV_8UC3, cv::Scalar{20, 40, 80, 255});
        if (alpha) {
            image.at<cv::Vec4b>(0, 0)[3] = 0;
        }
        cv::imwrite((root / "reference.png").string(), image);
        cv::imwrite((root / "frame01.png").string(), cv::Mat(8, 8, CV_8UC3, cv::Scalar{20, 40, 80}));
        std::ofstream stream{root / "scenario.yaml"};
        stream << "start_condition:\n"
                  "  type: detected\n"
                  "  minimum_score: 0.99\n"
                  "  detector: {type: mean_absolute_similarity, reference: reference.png}\n"
                  "splits: []\n";
        Profile profile;
        profile.source = VideoSourceConfiguration{
            (root / "frame%02d.png").string(),
            {std::nullopt, ResizeConfiguration{3, 3, ResizeInterpolation::linear, enabled}},
        };
        profile.instances.push_back({{54000}, (root / "scenario.yaml").string()});
        return profile;
    }

private slots:
    void invalidYamlIsReportedAndControllerCanLoadAValidScenarioAfterwards() {
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        const auto profile = make_profile(directory, false);
        AppController controller;
        const std::filesystem::path path{profile.instances[0].scenario};
        for (const auto* yaml : {"start_condition: [broken\n",
                                 "start_condition: *missing\nsplits: []\n",
                                 "a: &a {condition: *a}\nstart_condition: *a\nsplits: []\n"}) {
            {
                std::ofstream stream{path};
                stream << yaml;
            }
            QString error;
            QVERIFY(!controller.apply_profile(profile, &error));
            QVERIFY2(error.contains("could not parse scenario YAML"), qPrintable(error));
            const auto valid = make_profile(directory, false);
            QVERIFY2(controller.apply_profile(valid, &error), qPrintable(error));
            controller.stop();
        }
    }

    void previewTransformsRunOnWorkerWithoutReopeningInput() {
        auto probe = std::make_shared<PreviewProbe>();
        ProfilePreview preview([probe](const auto&) { return std::make_unique<PreviewSource>(probe); });
        SourceConfiguration source = NdiSourceConfiguration{"sender", {}};
        preview.configure(source);
        QTRY_VERIFY(!preview.snapshot().image.isNull());
        QCOMPARE(preview.snapshot().image.size(), QSize(8, 4));
        probe->paused = true;  // Draft transforms also update a paused input.
        auto& transform = std::get<NdiSourceConfiguration>(source).transform;
        transform.crop = CropConfiguration{0, 4, 0, 0};
        transform.resize = ResizeConfiguration{3, 2};
        preview.configure(source);
        QTRY_COMPARE(preview.snapshot().image.size(), QSize(3, 2));
        QCOMPARE(preview.snapshot().image.pixelColor(1, 1), QColor(10, 10, 10));
        QCOMPARE(probe->opens.load(), 1);
        probe->paused = false;
        QCOMPARE(preview.snapshot().input.width, 8);
        QCOMPARE(preview.snapshot().input.fps, 60.0);
        transform.crop->right = 8;
        preview.configure(source);
        QTRY_VERIFY(!preview.snapshot().error.empty());
        QVERIFY(preview.snapshot().image.isNull());
        transform.crop->right = 4;
        preview.configure(source);
        QTRY_COMPARE(preview.snapshot().image.size(), QSize(3, 2));
        QCOMPARE(probe->opens.load(), 1);
        std::get<NdiSourceConfiguration>(source).name = "different sender";
        preview.configure(source);
        QTRY_COMPARE(probe->opens.load(), 2);
        preview.stop();
        QCOMPARE(probe->closes.load(), 2);
        QVERIFY(!probe->wrong_thread.load());
    }

    void profilePreviewTracksDraftVisibilityAndSessionOwnership() {
        AppController controller;
        auto probe = std::make_shared<PreviewProbe>();
        ProfilePage page(&controller, nullptr, {}, [probe](const auto&) {
            if (std::this_thread::get_id() == probe->gui_thread) probe->wrong_thread = true;
            return std::make_unique<PreviewSource>(probe);
        });
        page.resize(1100, 1100);
        page.show();
        auto* status = page.findChild<QLabel*>("draftPreviewStatus");
        QTRY_VERIFY(status->text().contains("8 × 4"));
        page.findChild<QCheckBox*>("cropEnabled")->setChecked(true);
        page.findChild<QSpinBox*>("cropRight")->setValue(4);
        page.findChild<QCheckBox*>("resizeEnabled")->setChecked(true);
        page.findChild<QSpinBox*>("resizeWidth")->setValue(3);
        page.findChild<QSpinBox*>("resizeHeight")->setValue(2);
        QTRY_VERIFY(status->text().contains("Output: 3 × 2"));
        QVERIFY(status->text().contains("60.00 fps reported"));
        QCOMPARE(probe->opens.load(), 1);
        QVERIFY(!controller.session().running());  // The draft was never applied.
        const auto captures = qEnvironmentVariable("DIVERGENCESPLITTER_UI_CAPTURE_DIR");
        if (!captures.isEmpty()) {
            QDir().mkpath(captures);
            QVERIFY(page.grab().save(captures + "/profile-preview.png"));
        }
        page.hide();
        QVERIFY(!probe->active.load());
        page.show();
        QTRY_COMPARE(probe->opens.load(), 2);
        QTemporaryDir directory;
        bool released_before_session = false;
        connect(&controller, &AppController::sessionStarting, &page, [&] {
            released_before_session = !probe->active.load();
        });
        QString error;
        QVERIFY2(controller.apply_profile(make_profile(directory, true), &error), qPrintable(error));
        QVERIFY(released_before_session);
        QTRY_VERIFY(status->text().contains("Session is active"));
        QCOMPARE(probe->opens.load(), 2);
        page.findChild<QPushButton*>("previewStopSession")->click();
        QTRY_COMPARE(probe->opens.load(), 3);
        page.findChild<QCheckBox*>("previewEnabled")->setChecked(false);
        QVERIFY(!probe->active.load());
        QVERIFY(!probe->wrong_thread.load());
    }

    void previewFailureCanBeRetriedWithoutApplying() {
        AppController controller;
        std::atomic_int attempts{};
        auto probe = std::make_shared<PreviewProbe>();
        ProfilePage page(&controller, nullptr, {}, [&](const auto&) -> std::unique_ptr<FrameSource> {
            if (++attempts == 1) throw FrameSourceError("offline sender", true);
            return std::make_unique<PreviewSource>(probe);
        });
        page.show();
        auto* status = page.findChild<QLabel*>("draftPreviewStatus");
        QTRY_VERIFY(status->text().contains("offline sender"));
        auto* enabled = page.findChild<QCheckBox*>("previewEnabled");
        enabled->setChecked(false);
        enabled->setChecked(true);
        QTRY_VERIFY(status->text().contains("Opened input"));
        QVERIFY(!controller.session().running());
    }

    void openingPreviewDoesNotBlockGuiEvents() {
        AppController controller;
        auto probe = std::make_shared<PreviewProbe>();
        std::atomic_bool release{};
        ProfilePage page(&controller, nullptr, {}, [&](const auto&) {
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds{1};
            while (!release.load() && std::chrono::steady_clock::now() < deadline)
                std::this_thread::sleep_for(std::chrono::milliseconds{5});
            return std::make_unique<PreviewSource>(probe);
        });
        page.show();
        bool gui_event_processed = false;
        QTimer::singleShot(0, &page, [&] { gui_event_processed = true; release = true; });
        QTRY_VERIFY(gui_event_processed);
        QTRY_VERIFY(probe->active.load());
        QVERIFY(!probe->wrong_thread.load());
    }

    void monitorSummarizesActiveConditionScoresAndThresholds() {
        Scenario scenario;
        scenario.start_condition = std::make_shared<DetectedCondition>(
            std::make_shared<MeanBrightnessDetector>(), 0.9);
        ScenarioRuntime runtime{std::move(scenario)};
        runtime.apply_update({UpdateKind::initial, {1, 1, 1, TimerPhase::not_running, -1, 2}, {}});
        (void)runtime.evaluate(FrameContext{Frame{cv::Mat(2, 2, CV_8UC1, cv::Scalar{128}), {}}, {}});
        const auto overview = scenario_overview(runtime.diagnostics());
        QVERIFY(overview.contains("mean_brightness"));
        QVERIFY(overview.contains("0.5020 / 0.9000"));
        QVERIFY(overview.contains("Max:"));
        auto diagnostics = runtime.diagnostics();
        diagnostics.reset_pending = ActionOperation::reset;
        QVERIFY(scenario_overview(diagnostics).contains("Reset confirmation"));
        AppController controller;
        MonitorPage monitor(&controller);
        auto* cards = monitor.findChild<QScrollArea*>();
        QVERIFY(cards != nullptr);
        QVERIFY(monitor.findChild<ResetAllButton*>() != nullptr);
    }

#if DIVERGENCESPLITTER_ENABLE_NDI
    void ndiRealSenderSelectionAndRenderedPreview() {
        auto runtime = acquire_ndi_runtime();
        auto load = reinterpret_cast<const NDIlib_v5* (*)()>(GetProcAddress(
            GetModuleHandleW(L"Processing.NDI.Lib.x64.dll"), "NDIlib_v5_load"));
        QVERIFY(load);
        const auto* api = load();
        NDIlib_send_create_t settings;
        settings.p_ndi_name = "DivergenceSplitter UI integration test";
        auto sender = api->send_create(&settings);
        QVERIFY(sender);
        const auto cleanup = std::shared_ptr<void>{sender, [api](void* value) {
            api->send_destroy(static_cast<NDIlib_send_instance_t>(value));
        }};
        const std::string name = api->send_get_source_name(sender)->p_ndi_name;
        std::jthread sending([&](std::stop_token stop) {
            cv::Mat image(48, 64, CV_8UC4, cv::Scalar{230, 230, 230, 255});
            NDIlib_video_frame_v2_t frame;
            frame.xres = image.cols;
            frame.yres = image.rows;
            frame.FourCC = NDIlib_FourCC_video_type_BGRX;
            frame.frame_rate_N = 30;
            frame.frame_rate_D = 1;
            frame.p_data = image.data;
            frame.line_stride_in_bytes = static_cast<int>(image.step);
            while (!stop.stop_requested()) api->send_send_video_v2(sender, &frame);
        });
        QTemporaryDir directory;
        auto profile = make_profile(directory, true);
        profile.source = NdiSourceConfiguration{name, std::get<VideoSourceConfiguration>(profile.source).transform};
        const auto path = std::filesystem::path{directory.filePath("ndi-live.json").toStdString()};
        save_profile(path, profile);
        AppController controller;
        QString error;
        QVERIFY2(controller.open_profile(path, &error), qPrintable(error));
        ProfilePage page(&controller);
        auto* names = page.findChild<QComboBox*>("ndiSourceName");
        QTRY_VERIFY_WITH_TIMEOUT(names->findText(QString::fromStdString(name)) >= 0, 20000);
        names->setCurrentIndex(names->findText(QString::fromStdString(name)));
        QCOMPARE(std::get<NdiSourceConfiguration>(page.draft_profile().source).name, name);
        QTRY_VERIFY_WITH_TIMEOUT(controller.session().capture_stats().frames_published > 3, 20000);
        MonitorPage monitor(&controller);
        monitor.resize(640, 480);
        monitor.show();
        monitor.refresh();
        auto* preview = monitor.findChild<ImageView*>();
        QVERIFY(preview);
        const auto rendered = preview->grab().toImage();
        const auto color = rendered.pixelColor(rendered.width() / 2, rendered.height() / 2);
        QVERIFY(color.red() > 200 && color.green() > 200 && color.blue() > 200);
        const auto image = controller.session().latest_preview();
        QCOMPARE(image->cols, 3);
        QCOMPARE(image->rows, 3);
        controller.stop();
        page.show();
        auto* draft_status = page.findChild<QLabel*>("draftPreviewStatus");
        QTRY_VERIFY_WITH_TIMEOUT(draft_status->text().contains("Output: 3 × 3"), 20000);
        const auto draft_rendered = page.findChild<ImageView*>("draftPreview")->grab().toImage();
        QVERIFY(draft_rendered.pixelColor(draft_rendered.width() / 2, draft_rendered.height() / 2).red() > 200);
        QVERIFY2(controller.open_profile(path, &error), qPrintable(error));
        page.reload_from_controller();
        QCOMPARE(std::get<NdiSourceConfiguration>(page.draft_profile().source).name, name);
        QTRY_VERIFY_WITH_TIMEOUT(controller.session().capture_stats().frames_published > 3, 20000);
        page.hide();
        controller.stop();
    }
#endif
    void ndiDiscoveryKeepsDraftAndDoesNotBlockGui() {
        AppController controller;
        std::atomic_bool release{};
        ProfilePage page(&controller, nullptr, [&] {
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds{1};
            while (!release.load() && std::chrono::steady_clock::now() < deadline)
                std::this_thread::sleep_for(std::chrono::milliseconds{5});
            return std::vector<std::string>{"sender A", "sender B"};
        });
        auto* names = page.findChild<QComboBox*>("ndiSourceName");
        auto* refresh = page.findChild<QPushButton*>("ndiRefresh");
        auto* status = page.findChild<QLabel*>("ndiDiscoveryStatus");
        QVERIFY(names && refresh && status);
        names->setEditText("offline saved source");
        refresh->click();
        QVERIFY(!refresh->isEnabled());
        // The GUI can edit a draft while the finder waits on another thread.
        names->setEditText("edited during discovery");
        bool event_processed = false;
        QTimer::singleShot(0, &page, [&] { event_processed = true; release = true; });
        QTRY_VERIFY(event_processed);
        QTRY_VERIFY(refresh->isEnabled());
        QCOMPARE(names->count(), 2);
        QCOMPARE(names->currentText(), QStringLiteral("edited during discovery"));
        QVERIFY(status->text().contains("offline"));
        names->setCurrentIndex(1);
        QCOMPARE(names->currentText(), QStringLiteral("sender B"));
    }

    void ndiDiscoveryReportsSdkFailure() {
        AppController controller;
        ProfilePage page(&controller, nullptr, []() -> std::vector<std::string> {
            throw std::runtime_error("cannot load NDI test runtime");
        });
        auto* refresh = page.findChild<QPushButton*>("ndiRefresh");
        auto* status = page.findChild<QLabel*>("ndiDiscoveryStatus");
        refresh->click();
        QTRY_VERIFY(refresh->isEnabled());
        QVERIFY(status->text().contains("cannot load NDI test runtime"));
    }

    void ndiProfileRestoresOfflineNameAndTransform() {
        QTemporaryDir directory;
        auto profile = make_profile(directory, true);
        const auto transform = std::get<VideoSourceConfiguration>(profile.source).transform;
        profile.source = NdiSourceConfiguration{"offline sender", transform};
        const auto path = std::filesystem::path{directory.filePath("ndi.json").toStdString()};
        save_profile(path, profile);
        AppController controller;
        QString error;
        QVERIFY2(controller.open_profile(path, &error), qPrintable(error));
        ProfilePage page(&controller);
        const auto draft = page.draft_profile();
        QVERIFY(std::holds_alternative<NdiSourceConfiguration>(draft.source));
        const auto& source = std::get<NdiSourceConfiguration>(draft.source);
        QCOMPARE(source.name, std::string{"offline sender"});
        QVERIFY(source.transform.resize->resize_references);
        QCOMPARE(source.transform.resize->width, 3);
        controller.stop();
    }

    void initTestCase() {
        QVERIFY(settings_directory_.isValid());
        previous_appdata_ = qgetenv("APPDATA");
        previous_xdg_config_ = qgetenv("XDG_CONFIG_HOME");
        qputenv("APPDATA", settings_directory_.path().toUtf8());
        qputenv("XDG_CONFIG_HOME", settings_directory_.path().toUtf8());
#ifdef _WIN32
        QFontDatabase::addApplicationFont(QDir(qEnvironmentVariable("WINDIR")).filePath("Fonts/segoeui.ttf"));
        QApplication::setFont(QFont(QStringLiteral("Segoe UI"), 9));
#endif
    }

    void init() {
        QFile::remove(QString::fromStdString(default_settings_path().string()));
    }

    void cleanupTestCase() {
        qputenv("APPDATA", previous_appdata_);
        qputenv("XDG_CONFIG_HOME", previous_xdg_config_);
    }

    void referenceResizeDraftLifecycle_data() {
        QTest::addColumn<bool>("enabled");
        QTest::newRow("enabled") << true;
        QTest::newRow("disabled") << false;
    }

    void referenceResizeDraftLifecycle() {
        QFETCH(bool, enabled);
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        const auto profile = make_profile(directory, enabled);
        const std::filesystem::path path{directory.filePath("profile.json").toStdString()};
        save_profile(path, profile);
        AppController controller;
        QString error;
        QVERIFY2(controller.open_profile(path, &error), qPrintable(error));
        ProfilePage page(&controller);
        auto* references = page.findChild<QCheckBox*>("resizeReferences");
        auto* resize = page.findChild<QCheckBox*>("resizeEnabled");
        auto* revert = button(page, "Revert draft");
        auto* apply = button(page, "Apply");
        QVERIFY(references && resize && revert && apply);
        QVERIFY(references->isEnabled());
        QCOMPARE(references->isChecked(), enabled);
        const auto draft_value = [&page]() {
            return std::get<VideoSourceConfiguration>(page.draft_profile().source)
                .transform.resize->resize_references;
        };
        QCOMPARE(draft_value(), enabled);
        references->setChecked(!enabled);
        QCOMPARE(draft_value(), !enabled);
        revert->click();
        QCOMPARE(references->isChecked(), enabled);
        QCOMPARE(draft_value(), enabled);
        references->setChecked(!enabled);
        QSignalSpy applied(&page, &ProfilePage::profileApplied);
        apply->click();
        QCOMPARE(applied.count(), 1);
        QCOMPARE(std::get<VideoSourceConfiguration>(controller.profile().source)
                     .transform.resize->resize_references, !enabled);
        page.reload_from_controller();
        QCOMPARE(references->isChecked(), !enabled);
        resize->setChecked(false);
        QVERIFY(!references->isEnabled());
        QVERIFY(!std::get<VideoSourceConfiguration>(page.draft_profile().source).transform.resize);
        resize->setChecked(true);
        QVERIFY(references->isEnabled());
        QCOMPARE(draft_value(), !enabled);
        controller.stop();
    }

    void referenceResizeFailureIsRejectedDuringApplyValidation() {
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        AppController controller;
        QString error;
        QVERIFY2(controller.apply_profile(make_profile(directory, false, true), &error), qPrintable(error));
        ProfilePage page(&controller);
        auto* references = page.findChild<QCheckBox*>("resizeReferences");
        auto* apply = button(page, "Apply");
        QVERIFY(references && apply);
        references->setChecked(true);
        QSignalSpy applied(&page, &ProfilePage::profileApplied);
        QString validation_error;
        QTimer::singleShot(0, &page, [&validation_error]() {
            if (auto* message = qobject_cast<QMessageBox*>(QApplication::activeModalWidget())) {
                validation_error = message->text();
                message->accept();
            }
        });
        apply->click();
        QCOMPARE(applied.count(), 0);
        QVERIFY2(validation_error.startsWith("Scenario validation failed:"), qPrintable(validation_error));
        QVERIFY(validation_error.contains("alpha"));
        QVERIFY(!std::get<VideoSourceConfiguration>(controller.profile().source)
                     .transform.resize->resize_references);
        controller.stop();
    }

    void resetAllRequiresHold() {
        ResetAllButton button;
        button.set_hold_duration_ms(100);
        QSignalSpy spy(&button, &ResetAllButton::holdCompleted);
        QTest::mousePress(&button, Qt::LeftButton);
        QTest::qWait(150);
        QTest::mouseRelease(&button, Qt::LeftButton);
        QCOMPARE(spy.count(), 1);
    }

    void resetAllCancelsEarlyRelease() {
        ResetAllButton button;
        button.set_hold_duration_ms(200);
        QSignalSpy spy(&button, &ResetAllButton::holdCompleted);
        QTest::mousePress(&button, Qt::LeftButton);
        QTest::qWait(50);
        QTest::mouseRelease(&button, Qt::LeftButton);
        QTest::qWait(200);
        QCOMPARE(spy.count(), 0);
    }

    void convertsBgrImage() {
        cv::Mat image(2, 2, CV_8UC3, cv::Scalar{0, 0, 255});
        const QImage converted = mat_to_qimage(image);
        QCOMPARE(converted.width(), 2);
        QCOMPARE(converted.height(), 2);
        QCOMPARE(converted.pixelColor(0, 0), QColor(255, 0, 0));
    }

    void convertsGrayImage() {
        const cv::Mat image(2, 2, CV_8UC1, cv::Scalar{128});
        const QImage converted = mat_to_qimage(image);
        QCOMPARE(converted.format(), QImage::Format_Grayscale8);
        QCOMPARE(converted.pixelColor(0, 0), QColor(128, 128, 128));
    }

    void themeSwitchesLightAndDarkPalettes() {
        theme::apply(*qApp, theme::Mode::light);
        const QColor light = QApplication::palette().color(QPalette::Window);
        const QString light_style = qApp->styleSheet();
        theme::apply(*qApp, theme::Mode::dark);
        const QColor dark = QApplication::palette().color(QPalette::Window);
        const QString dark_style = qApp->styleSheet();
        QVERIFY(light != dark);
        QVERIFY(dark.lightness() < light.lightness());
        QVERIFY(!light_style.isEmpty());
        QVERIFY(light_style != dark_style);
        QVERIFY(dark_style.contains(QStringLiteral("#111512")));
        theme::apply(*qApp, theme::Mode::light);
    }

    void profileHeaderSavesDraftToCurrentPath() {
        QTemporaryDir directory;
        const auto profile = make_profile(directory, false);
        const auto path = std::filesystem::path{directory.filePath("profile.json").toStdString()};
        save_profile(path, profile);
        AppController controller;
        QString error;
        QVERIFY2(controller.open_profile(path, &error), qPrintable(error));
        controller.stop();
        MainWindow window(&controller);
        auto* header = window.findChild<ProfileHeader*>();
        QVERIFY(header != nullptr);
        auto* dirty = header->findChild<QLabel*>(QStringLiteral("dirtyMarker"));
        auto* save = header->findChild<QPushButton*>(QStringLiteral("profileSave"));
        auto* crop_enabled = window.findChild<QCheckBox*>(QStringLiteral("cropEnabled"));
        auto* crop_left = window.findChild<QSpinBox*>(QStringLiteral("cropLeft"));
        auto* profile_page = window.findChild<ProfilePage*>();
        QVERIFY(dirty != nullptr);
        QVERIFY(save != nullptr);
        QVERIFY(crop_enabled != nullptr);
        QVERIFY(crop_left != nullptr);
        QVERIFY(profile_page != nullptr);
        crop_enabled->setChecked(true);
        crop_left->setValue(1);
        QTRY_VERIFY(!dirty->isHidden());
        auto* apply = button(*profile_page, QStringLiteral("Apply"));
        QVERIFY(apply != nullptr);
        QSignalSpy applied(profile_page, &ProfilePage::profileApplied);
        apply->click();
        QTRY_COMPARE(applied.count(), 1);
        QVERIFY(!dirty->isHidden());
        save->click();
        QTRY_VERIFY(dirty->isHidden());
        QFile saved(QString::fromStdWString(path.wstring()));
        QVERIFY(saved.open(QIODevice::ReadOnly));
        const auto contents = saved.readAll();
        QVERIFY(contents.contains("\"type\": \"video\""));
        QVERIFY(contents.contains("\"left\": 1"));
    }

    void profileNewIsDirtyUntilSaved() {
        QTemporaryDir directory;
        const auto fixture = make_profile(directory, false);
        AppController controller;
        const QString new_path = directory.filePath("new-profile.json");
        MainWindow::FileDialogHooks dialogs;
        dialogs.save_file = [&new_path](const QString&, const QString&, const QString&) {
            return new_path;
        };
        dialogs.confirm_discard = [](const QString&, const QString&) { return true; };
        MainWindow window(&controller, nullptr, dialogs);
        auto* header = window.findChild<ProfileHeader*>();
        auto* profile_page = window.findChild<ProfilePage*>();
        QVERIFY(header != nullptr && profile_page != nullptr);
        auto* dirty = header->findChild<QLabel*>(QStringLiteral("dirtyMarker"));
        auto* path = header->findChild<QLineEdit*>(QStringLiteral("profilePath"));
        auto* create = header->findChild<QPushButton*>(QStringLiteral("profileNew"));
        auto* save = header->findChild<QPushButton*>(QStringLiteral("profileSave"));
        QVERIFY(dirty != nullptr && path != nullptr && create != nullptr && save != nullptr);
        QVERIFY(dirty->isHidden());
        create->click();
        QVERIFY(!dirty->isHidden());
        QCOMPARE(path->text(), new_path);
        QVERIFY(!QFile::exists(new_path));

        auto* source_type = window.findChild<QComboBox*>(QStringLiteral("sourceType"));
        auto* video_path = window.findChild<QLineEdit*>(QStringLiteral("videoPath"));
        auto* instances = window.findChild<QTableWidget*>(QStringLiteral("instanceTable"));
        QVERIFY(source_type != nullptr && video_path != nullptr && instances != nullptr);
        source_type->setCurrentIndex(1);
        video_path->setText(directory.filePath("frame%02d.png"));
        auto* add = button(*profile_page, QStringLiteral("Add instance"));
        QVERIFY(add != nullptr);
        add->click();
        QCOMPARE(instances->rowCount(), 1);
        instances->item(0, 0)->setText(QStringLiteral("54000"));
        instances->item(0, 1)->setText(
            QString::fromStdString(fixture.instances.front().scenario)
        );

        auto* apply = button(*profile_page, QStringLiteral("Apply"));
        QVERIFY(apply != nullptr);
        QSignalSpy applied(profile_page, &ProfilePage::profileApplied);
        apply->click();
        QTRY_COMPARE(applied.count(), 1);
        QVERIFY(!dirty->isHidden());
        save->click();
        QTRY_VERIFY(dirty->isHidden());
        QVERIFY(QFile::exists(new_path));
        QVERIFY(controller.profile_path().has_value());
        QCOMPARE(
            controller.profile_path()->wstring(),
            std::filesystem::path{new_path.toStdWString()}.wstring()
        );
    }

    void profileSaveFailureKeepsDirtyState() {
        QTemporaryDir directory;
        const auto profile = make_profile(directory, false);
        const auto path = std::filesystem::path{directory.filePath("profile.json").toStdString()};
        save_profile(path, profile);
        AppController controller;
        QString error;
        QVERIFY2(controller.open_profile(path, &error), qPrintable(error));
        controller.stop();
        QString error_message;
        MainWindow::FileDialogHooks dialogs;
        dialogs.show_error = [&error_message](const QString&, const QString& message) {
            error_message = message;
        };
        MainWindow window(&controller, nullptr, dialogs);
        auto* header = window.findChild<ProfileHeader*>();
        auto* dirty = header->findChild<QLabel*>(QStringLiteral("dirtyMarker"));
        auto* save = header->findChild<QPushButton*>(QStringLiteral("profileSave"));
        auto* crop_enabled = window.findChild<QCheckBox*>(QStringLiteral("cropEnabled"));
        auto* crop_left = window.findChild<QSpinBox*>(QStringLiteral("cropLeft"));
        QVERIFY(dirty != nullptr && save != nullptr);
        QVERIFY(crop_enabled != nullptr && crop_left != nullptr);
        crop_enabled->setChecked(true);
        crop_left->setValue(1);
        QTRY_VERIFY(!dirty->isHidden());
        QVERIFY(QDir(directory.path()).removeRecursively());
        save->click();
        QTRY_VERIFY(!error_message.isEmpty());
        QVERIFY(!dirty->isHidden());
    }

    void monitorBuildsScenarioCardsAndKeepsThemAcrossRefresh() {
        QTemporaryDir directory;
        const auto profile = make_profile(directory, false);
        AppController controller;
        QString error;
        QVERIFY2(controller.apply_profile(profile, &error), qPrintable(error));
        MonitorPage monitor(&controller);
        monitor.resize(1000, 700);
        monitor.show();
        monitor.refresh();
        QTRY_VERIFY(!monitor.findChildren<QFrame*>(QStringLiteral("scenarioCard")).isEmpty());
        const auto cards = monitor.findChildren<QFrame*>(QStringLiteral("scenarioCard"));
        QCOMPARE(cards.size(), 1);
        const auto texts = [&cards] {
            QStringList values;
            for (auto* label : cards.front()->findChildren<QLabel*>()) {
                values.append(label->text());
            }
            return values;
        };
        QVERIFY(texts().contains(QStringLiteral("Scenario 0")));
        QVERIFY(texts().contains(QStringLiteral("Evaluating")));
        QVERIFY(texts().contains(QStringLiteral("Evaluation")));
        QVERIFY(texts().contains(QStringLiteral("Avg")));
        QVERIFY(texts().contains(QStringLiteral("Max")));
        monitor.refresh();
        QCOMPARE(monitor.findChildren<QFrame*>(QStringLiteral("scenarioCard")).size(), 1);
        QCOMPARE(monitor.findChildren<QFrame*>(QStringLiteral("scenarioCard")).front(), cards.front());
        const auto captures = qEnvironmentVariable("DIVERGENCESPLITTER_UI_CAPTURE_DIR");
        if (!captures.isEmpty()) {
            QDir().mkpath(captures);
            QTest::qWait(200);
            monitor.refresh();
            QVERIFY(monitor.grab().save(captures + "/monitor-scenario-card.png"));
        }
        controller.stop();
    }

    void mainWindowNavigationAndProfileHeader() {
        AppController controller;
        MainWindow window(&controller);
        auto* navigation = window.findChild<NavigationBar*>();
        auto* header = window.findChild<ProfileHeader*>();
        auto* stack = window.findChild<QStackedWidget*>();
        QVERIFY(navigation != nullptr);
        QVERIFY(header != nullptr);
        QVERIFY(stack != nullptr);
        QCOMPARE(stack->count(), 5);
        QVERIFY(header->findChild<QPushButton*>(QStringLiteral("profileNew")) != nullptr);
        QVERIFY(header->findChild<QPushButton*>(QStringLiteral("profileOpen")) != nullptr);
        QVERIFY(header->findChild<QPushButton*>(QStringLiteral("profileSave")) != nullptr);
        QVERIFY(header->findChild<QPushButton*>(QStringLiteral("profileSaveAs")) != nullptr);
        auto* dirty = header->findChild<QLabel*>(QStringLiteral("dirtyMarker"));
        QVERIFY(dirty != nullptr);
        QVERIFY(dirty->isHidden());
        auto* source_type = window.findChild<QComboBox*>(QStringLiteral("sourceType"));
        QVERIFY(source_type != nullptr);
        source_type->setCurrentIndex(1);
        QTRY_VERIFY(!dirty->isHidden());
        source_type->setCurrentIndex(0);
        QTRY_VERIFY(dirty->isHidden());
        QCOMPARE(navigation->width(), 60);
        auto* toggle = navigation->findChild<QToolButton*>(QStringLiteral("navToggle"));
        QVERIFY(toggle != nullptr);
        toggle->click();
        QCOMPARE(navigation->width(), 180);
        window.resize(1200, 900);
        window.show();
        QTest::qWait(50);
        auto* vertical_divider = window.findChild<QFrame*>(QStringLiteral("dividerVertical"));
        auto* horizontal_divider =
            window.findChild<QFrame*>(QStringLiteral("dividerHorizontal"));
        QVERIFY(vertical_divider != nullptr && horizontal_divider != nullptr);
        QCOMPARE(vertical_divider->width(), 1);
        QVERIFY(vertical_divider->height() > 1);
        QCOMPARE(horizontal_divider->height(), 1);
        const auto captures = qEnvironmentVariable("DIVERGENCESPLITTER_UI_CAPTURE_DIR");
        if (!captures.isEmpty()) {
            QDir().mkpath(captures);
            QTest::qWait(150);
            QVERIFY(window.grab().save(captures + "/main-window-monitor.png"));
        }
        QToolButton* diagnostics = nullptr;
        for (auto* button : navigation->findChildren<QToolButton*>()) {
            if (button->text() == QStringLiteral("Diagnostics")) {
                diagnostics = button;
            }
        }
        QVERIFY(diagnostics != nullptr);
        diagnostics->click();
        QCOMPARE(navigation->current_page(), AppPage::diagnostics);
        QCOMPARE(stack->currentIndex(), 1);
        auto* tabs = window.findChild<QTabWidget*>(QStringLiteral("profileTabs"));
        QVERIFY(tabs != nullptr);
        QCOMPARE(tabs->count(), 2);
        QCOMPARE(tabs->tabText(0), QStringLiteral("Input"));
        QCOMPARE(tabs->tabText(1), QStringLiteral("Scenarios && Connections"));
        const auto diagnostics_captures =
            qEnvironmentVariable("DIVERGENCESPLITTER_UI_CAPTURE_DIR");
        if (!diagnostics_captures.isEmpty()) {
            QDir().mkpath(diagnostics_captures);
            QTest::qWait(200);
            QVERIFY(window.grab().save(diagnostics_captures + "/main-window-diagnostics.png"));
        }
        QToolButton* profile = nullptr;
        for (auto* button : navigation->findChildren<QToolButton*>()) {
            if (button->text() == QStringLiteral("Profile")) {
                profile = button;
            }
        }
        QVERIFY(profile != nullptr);
        profile->click();
        QCOMPARE(navigation->current_page(), AppPage::profile);
        QCOMPARE(stack->currentIndex(), 2);
        if (!diagnostics_captures.isEmpty()) {
            QTest::qWait(200);
            QVERIFY(window.grab().save(diagnostics_captures + "/main-window-profile.png"));
            tabs->setCurrentIndex(1);
            QTest::qWait(100);
            QVERIFY(window.grab().save(
                diagnostics_captures + "/main-window-profile-scenarios.png"
            ));
            QToolButton* settings = nullptr;
            QToolButton* about = nullptr;
            for (auto* button : navigation->findChildren<QToolButton*>()) {
                if (button->text() == QStringLiteral("Settings")) {
                    settings = button;
                } else if (button->text() == QStringLiteral("About")) {
                    about = button;
                }
            }
            QVERIFY(settings != nullptr && about != nullptr);
            settings->click();
            QTest::qWait(100);
            QVERIFY(window.grab().save(diagnostics_captures + "/main-window-settings.png"));
            about->click();
            QTest::qWait(100);
            QVERIFY(window.grab().save(diagnostics_captures + "/main-window-about.png"));
            theme::apply(*qApp, theme::Mode::dark);
            QToolButton* monitor_button = nullptr;
            for (auto* button : navigation->findChildren<QToolButton*>()) {
                if (button->text() == QStringLiteral("Monitor")) {
                    monitor_button = button;
                }
            }
            QVERIFY(monitor_button != nullptr);
            monitor_button->click();
            QTest::qWait(300);
            QVERIFY(window.grab().save(diagnostics_captures + "/main-window-dark.png"));
        }
    }
};

QTEST_MAIN(UiTests)

#include "ui_tests.moc"
