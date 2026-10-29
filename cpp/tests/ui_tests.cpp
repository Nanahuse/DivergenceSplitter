#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QLabel>
#include <QFile>
#include <QMessageBox>
#include <QPushButton>
#include <QSignalSpy>
#include <QTabWidget>
#include <QTemporaryDir>
#include <QTest>
#include <QTimer>

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include <fstream>
#include <atomic>
#include <thread>

#include "divergencesplitter/ui/app_controller.hpp"
#include "divergencesplitter/ui/image_view.hpp"
#include "divergencesplitter/ui/main_window.hpp"
#include "divergencesplitter/ui/profile_page.hpp"
#include "divergencesplitter/ui/reset_all_button.hpp"
#include "divergencesplitter/ui/monitor_page.hpp"
#include "divergencesplitter/capture/ndi.hpp"

#if DIVERGENCESPLITTER_ENABLE_NDI
#include <windows.h>
#include <Processing.NDI.Lib.h>
#include <Processing.NDI.DynamicLoad.h>
#endif

using namespace divergencesplitter::ui;
using namespace divergencesplitter;

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
        QVERIFY2(controller.open_profile(path, &error), qPrintable(error));
        page.reload_from_controller();
        QCOMPARE(std::get<NdiSourceConfiguration>(page.draft_profile().source).name, name);
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

    void mainWindowTabs() {
        AppController controller;
        MainWindow window(&controller);
        auto* tabs = window.findChild<QTabWidget*>();
        QVERIFY(tabs != nullptr);
        QCOMPARE(tabs->count(), 5);
        for (int index = 0; index < tabs->count(); ++index) {
            tabs->setCurrentIndex(index);
            QCOMPARE(tabs->currentIndex(), index);
        }
    }
};

QTEST_MAIN(UiTests)

#include "ui_tests.moc"
