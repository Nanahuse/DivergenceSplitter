#include <QApplication>
#include <QCheckBox>
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

#include "divergencesplitter/ui/app_controller.hpp"
#include "divergencesplitter/ui/image_view.hpp"
#include "divergencesplitter/ui/main_window.hpp"
#include "divergencesplitter/ui/profile_page.hpp"
#include "divergencesplitter/ui/reset_all_button.hpp"

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
