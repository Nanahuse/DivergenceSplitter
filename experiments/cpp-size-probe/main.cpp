#include <QApplication>
#include <QCheckBox>
#include <QEventLoop>
#include <QFileDialog>
#include <QHostAddress>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QPixmap>
#include <QPushButton>
#include <QTemporaryDir>
#include <QTimer>
#include <QVBoxLayout>
#include <QWebSocket>
#include <QWebSocketServer>
#include <opencv2/img_hash.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>

#if PROBE_WITH_NDI
#include <windows.h>
#include <Processing.NDI.Lib.h>
#endif

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::string checkNdi(bool required) {
#if PROBE_WITH_NDI
    (void)required;
    // Use only the bundled DLL, never an SDK/runtime elsewhere on PATH.
    const auto path = (QCoreApplication::applicationDirPath() + "/Processing.NDI.Lib.x64.dll").toStdWString();
    HMODULE module = LoadLibraryExW(path.c_str(), nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    require(module != nullptr, "Bundled NDI runtime could not be loaded");
    auto release = [](HMODULE handle) { FreeLibrary(handle); };
    std::unique_ptr<std::remove_pointer_t<HMODULE>, decltype(release)> library(module, release);
    // Types come from official headers; no handwritten ABI and no import library.
    auto initialize = reinterpret_cast<decltype(&NDIlib_initialize)>(GetProcAddress(module, "NDIlib_initialize"));
    auto destroy = reinterpret_cast<decltype(&NDIlib_destroy)>(GetProcAddress(module, "NDIlib_destroy"));
    auto version = reinterpret_cast<decltype(&NDIlib_version)>(GetProcAddress(module, "NDIlib_version"));
    require(initialize && destroy && version, "NDI exports missing");
    require(initialize(), "NDI initialization failed");
    const std::string result = version();
    destroy();
    return result;
#else
    require(!required, "NDI UNVERIFIED: official SDK/runtime not supplied");
    return "UNVERIFIED: official SDK/runtime not supplied";
#endif
}

void checkWebSocket() {
    QWebSocketServer server("Size probe", QWebSocketServer::NonSecureMode);
    require(server.listen(QHostAddress::LocalHost, 0), "WebSocket listen failed");
    QObject::connect(&server, &QWebSocketServer::newConnection, &server, [&] {
        auto* peer = server.nextPendingConnection();
        QObject::connect(peer, &QWebSocket::textMessageReceived, peer, [peer](const QString& text) {
            peer->sendTextMessage(text);
        });
        QObject::connect(peer, &QWebSocket::disconnected, peer, &QObject::deleteLater);
    });
    QEventLoop loop;
    QWebSocket client;
    bool passed = false;
    const QJsonObject payload{{"operation", "probe"}, {"value", 23}};
    QObject::connect(&client, &QWebSocket::connected, &loop, [&] {
        client.sendTextMessage(QString::fromUtf8(QJsonDocument(payload).toJson(QJsonDocument::Compact)));
    });
    QObject::connect(&client, &QWebSocket::textMessageReceived, &loop, [&](const QString& message) {
        passed = QJsonDocument::fromJson(message.toUtf8()).object() == payload;
        loop.quit();
    });
    QTimer timer;
    timer.setSingleShot(true);
    QObject::connect(&timer, &QTimer::timeout, &loop, &QEventLoop::quit);
    timer.start(5000);
    client.open(QUrl(QString("ws://127.0.0.1:%1").arg(server.serverPort())));
    loop.exec();
    client.close();
    require(passed, "WebSocket/JSON roundtrip failed or timed out");
}

cv::Mat testImage() {
    cv::Mat image(128, 192, CV_8UC3, cv::Scalar(30, 70, 180));
    cv::rectangle(image, cv::Rect(20, 30, 70, 60), cv::Scalar(230, 180, 40), -1);
    return image;
}

void checkOpenCv() {
    QTemporaryDir directory;
    require(directory.isValid(), "Temporary directory creation failed");
    // OpenCV's narrow Windows filename APIs need ASCII paths. CI TEMP is ASCII.
    const auto imagePath = (directory.path() + "/probe.png").toStdString();
    const auto videoPath = (directory.path() + "/probe.avi").toStdString();
    const cv::Mat original = testImage();
    require(cv::imwrite(imagePath, original), "PNG write failed");
    cv::Mat loaded = cv::imread(imagePath);
    require(!loaded.empty() && cv::norm(original, loaded, cv::NORM_INF) == 0, "PNG roundtrip failed");
    cv::Mat gray, small, blurred;
    cv::cvtColor(loaded, gray, cv::COLOR_BGR2GRAY);
    cv::resize(gray, small, cv::Size(64, 64));
    cv::GaussianBlur(small, blurred, cv::Size(3, 3), 0);
    require(blurred.rows == 64 && blurred.channels() == 1, "Image processing failed");
    const auto hasher = cv::img_hash::PHash::create();
    cv::Mat hash1, hash2;
    hasher->compute(original, hash1);
    hasher->compute(loaded, hash2);
    require(hash1.total() == 8 && hasher->compare(hash1, hash2) == 0, "PerceptualHash failed");
    cv::VideoWriter writer(videoPath, cv::CAP_OPENCV_MJPEG,
        cv::VideoWriter::fourcc('M', 'J', 'P', 'G'), 10.0, original.size());
    require(writer.isOpened(), "MJPEG AVI writer unavailable");
    for (int i = 0; i < 3; ++i) writer.write(original);
    writer.release();
    cv::VideoCapture capture(videoPath, cv::CAP_OPENCV_MJPEG);
    cv::Mat frame;
    int count = 0;
    while (capture.read(frame)) {
        require(frame.size() == original.size(), "Video frame dimensions differ");
        ++count;
    }
    require(count == 3, "MJPEG AVI video input failed");
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    try {
        const auto args = app.arguments();
        const bool selfTest = args.contains("--self-test");
        const bool required = args.contains("--require-ndi");
        const auto ndi = checkNdi(required);
        QWidget window;
        window.setWindowTitle("DivergenceSplitter C++23 size probe");
        auto* layout = new QVBoxLayout(&window);
        auto* preview = new QLabel;
        preview->setMinimumSize(384, 256);
        layout->addWidget(preview);
        auto showImage = [preview](const cv::Mat& image) {
            cv::Mat rgb;
            cv::cvtColor(image, rgb, cv::COLOR_BGR2RGB);
            QImage qimage(rgb.data, rgb.cols, rgb.rows, static_cast<qsizetype>(rgb.step), QImage::Format_RGB888);
            preview->setPixmap(QPixmap::fromImage(qimage.copy()).scaled(384, 256, Qt::KeepAspectRatio));
        };
        showImage(testImage());
        auto* open = new QPushButton("Open image / video (first frame)");
        auto* status = new QLabel(QString::fromStdString("NDI® runtime: " + ndi));
        status->setWordWrap(true);
        layout->addWidget(open);
        auto* enabled = new QCheckBox("Preview enabled");
        enabled->setChecked(true);
        QObject::connect(enabled, &QCheckBox::toggled, preview, &QWidget::setVisible);
        layout->addWidget(enabled);
        layout->addWidget(status);
        auto* info = new QLabel("<a href=\"https://ndi.video/\">NDI®</a> is a registered trademark of Vizrt NDI AB.");
        info->setOpenExternalLinks(true);
        layout->addWidget(info);
        QObject::connect(open, &QPushButton::clicked, &window, [&] {
            const auto path = QFileDialog::getOpenFileName(&window, "Open image or video");
            if (path.isEmpty()) return;
            try {
                auto frame = cv::imread(path.toStdString());
                if (frame.empty()) {
                    cv::VideoCapture capture(path.toStdString());
                    capture.read(frame);
                }
                require(!frame.empty(), "Unable to decode file with configured OpenCV backends");
                showImage(frame);
                status->setText("File decoded successfully");
            } catch (const std::exception& error) { status->setText(error.what()); }
        });
        window.show();
        if (selfTest) {
            // Execute after a real Windows Widgets window has entered the event loop.
            QTimer::singleShot(250, &window, [&] {
                try {
                    require(window.isVisible() && window.windowHandle(), "Widgets window failed to open");
                    checkOpenCv();
                    checkWebSocket();
                    std::cout << "PASS: Widgets, PNG, processing, PHash, AVI, WebSocket, JSON\nNDI: " << ndi << '\n';
                    app.exit(0);
                } catch (const std::exception& error) {
                    std::cerr << error.what() << '\n';
                    app.exit(1);
                }
            });
        }
        return app.exec();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
