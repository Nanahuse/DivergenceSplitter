#include <QSignalSpy>
#include <QTabWidget>
#include <QTest>

#include <opencv2/core.hpp>

#include "divergencesplitter/ui/app_controller.hpp"
#include "divergencesplitter/ui/image_view.hpp"
#include "divergencesplitter/ui/main_window.hpp"
#include "divergencesplitter/ui/reset_all_button.hpp"

using namespace divergencesplitter::ui;

class UiTests final : public QObject {
    Q_OBJECT

private slots:
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
