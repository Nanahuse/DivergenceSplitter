// Focused deployment checks, separate from the unchanged comparison application.
#include <QApplication>
#include <QBuffer>
#include <QDir>
#include <QFile>
#include <QFontInfo>
#include <QGlyphRun>
#include <QHostInfo>
#include <QImage>
#include <QImageReader>
#include <QInputMethod>
#include <QInputMethodEvent>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QPalette>
#include <QRawFont>
#include <QSslSocket>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTextLayout>
#include <QVBoxLayout>
#include <windows.h>
#include <memory>
#include <stdexcept>

int main(int argc, char** argv) {
    if (argc != 4) return 2; // distribution root, JSON report, PNG capture
    const auto root = QString::fromLocal8Bit(argv[1]);
    const auto report_path = QString::fromLocal8Bit(argv[2]);
    const auto capture_path = QString::fromLocal8Bit(argv[3]);
    QCoreApplication::setLibraryPaths({QDir(root).absoluteFilePath("Qt6/plugins")});
    QApplication app(argc, argv);
    QApplication::setStyle("Fusion");
    QJsonArray checks;
    QJsonObject result{{"native_ime_conversion", "not tested; synthetic QInputMethodEvent only"}};
    auto require = [&](bool condition, const char* name) {
        if (!condition) throw std::runtime_error(name);
        checks.append(name);
    };
    try {
        require(QGuiApplication::platformName() == "windows", "windows_platform_plugin");
        QJsonObject modules;
        for (const wchar_t* name : {L"Qt6Core.dll", L"Qt6Gui.dll", L"Qt6Widgets.dll", L"Qt6Network.dll", L"qwindows.dll"}) {
            wchar_t path[32768]{};
            const auto module = GetModuleHandleW(name);
            require(module && GetModuleFileNameW(module, path, 32768), "loaded_module_path_available");
            const auto actual = QDir::fromNativeSeparators(QString::fromWCharArray(path));
            require(actual.startsWith(QDir(root).absolutePath() + '/', Qt::CaseInsensitive), "module_loaded_from_distribution");
            modules.insert(QString::fromWCharArray(name), actual);
        }
        result.insert("loaded_modules", modules);
        result.insert("plugin_paths", QJsonArray::fromStringList(QCoreApplication::libraryPaths()));

        const auto japanese = QString::fromUtf8("日本語入力テスト");
        QWidget window;
        window.setWindowTitle("Qt deployment: 日本語・IME event check");
        auto layout = new QVBoxLayout(&window);
        layout->addWidget(new QLabel(japanese));
        QLineEdit edit;
        layout->addWidget(&edit);
        window.resize(620, 220);
        window.show();
        edit.setFocus();
        app.processEvents();
        QTextLayout text(japanese, edit.font());
        text.beginLayout();
        auto line = text.createLine();
        line.setLineWidth(600);
        text.endLayout();
        QJsonArray fonts;
        qsizetype glyphs = 0;
        bool missing = false;
        for (const auto& run : text.glyphRuns()) {
            fonts.append(run.rawFont().familyName());
            for (auto glyph : run.glyphIndexes()) { ++glyphs; missing |= glyph == 0; }
        }
        result.insert("japanese_font_families", fonts);
        result.insert("japanese_glyph_count", glyphs);
        require(glyphs >= japanese.size() && !missing, "japanese_font_fallback_has_glyphs");
        require(edit.testAttribute(Qt::WA_InputMethodEnabled) && QGuiApplication::inputMethod(), "input_method_enabled");
        QInputMethodEvent preedit(QString::fromUtf8("にほんご"), {});
        QCoreApplication::sendEvent(&edit, &preedit);
        require(edit.text().isEmpty(), "synthetic_ime_preedit_not_committed");
        QInputMethodEvent commit;
        commit.setCommitString(japanese);
        QCoreApplication::sendEvent(&edit, &commit);
        require(edit.text() == japanese, "synthetic_ime_commit_roundtrip");
        const auto json = QJsonDocument(QJsonObject{{"name", edit.text()}}).toJson();
        require(QJsonDocument::fromJson(json).object()["name"].toString() == japanese, "unicode_json_roundtrip");

        QJsonArray formats;
        for (const auto& format : QImageReader::supportedImageFormats()) formats.append(QString::fromLatin1(format));
        result.insert("image_formats", formats);
        QImage source(80, 50, QImage::Format_RGB32);
        source.fill(Qt::blue);
        for (const char* format : {"PNG", "JPEG"}) {
            QByteArray bytes;
            QBuffer buffer(&bytes);
            buffer.open(QIODevice::WriteOnly);
            require(source.save(&buffer, format), "image_encode");
            QImage decoded;
            require(decoded.loadFromData(bytes, format) && decoded.size() == source.size(), "image_decode");
        }
        QTcpServer server;
        require(server.listen(QHostAddress::LocalHost, 0), "tcp_loopback_listen");
        QTcpSocket client;
        client.connectToHost(QHostAddress::LocalHost, server.serverPort());
        require(client.waitForConnected(3000) && server.waitForNewConnection(3000), "tcp_loopback_connect");
        std::unique_ptr<QTcpSocket> peer(server.nextPendingConnection());
        const auto payload = japanese.toUtf8();
        require(peer && peer->write(payload) == payload.size() && peer->waitForBytesWritten(3000), "tcp_loopback_write");
        require(client.waitForReadyRead(3000) && client.readAll() == payload, "tcp_unicode_roundtrip");
        require(QHostInfo::fromName("localhost").error() == QHostInfo::NoError, "localhost_lookup");
        result.insert("tls_backends", QJsonArray::fromStringList(QSslSocket::availableBackends()));
        result.insert("active_tls_backend", QSslSocket::activeBackend());
        require(QSslSocket::supportsSsl() && QSslSocket::availableBackends().contains("schannel"), "schannel_tls_backend_available");

        const auto original = app.palette();
        auto dark = original;
        dark.setColor(QPalette::Window, QColor(35, 35, 35));
        dark.setColor(QPalette::WindowText, Qt::white);
        dark.setColor(QPalette::Base, QColor(48, 48, 48));
        dark.setColor(QPalette::Text, Qt::white);
        QApplication::setPalette(dark);
        app.processEvents();
        require(window.palette().color(QPalette::Window) == QColor(35, 35, 35), "fusion_dark_palette");
        QApplication::setPalette(original);
        app.processEvents();
        require(window.palette().color(QPalette::Window) == original.color(QPalette::Window), "fusion_palette_restored");
        require(window.grab().save(capture_path), "japanese_widget_capture");
        result.insert("error", "");
    } catch (const std::exception& error) {
        result.insert("error", error.what());
    }
    result.insert("checks", checks);
    QFile report(report_path);
    if (!report.open(QIODevice::WriteOnly)) return 3;
    report.write(QJsonDocument(result).toJson());
    return result["error"].toString().isEmpty() ? 0 : 1;
}
