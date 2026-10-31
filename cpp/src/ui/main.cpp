#include <QApplication>
#include <QTimer>

#include "divergencesplitter/capture/ndi.hpp"

#include "divergencesplitter/ui/app_controller.hpp"
#include "divergencesplitter/ui/main_window.hpp"

int main(int argc, char* argv[]) {
    QApplication application(argc, argv);
    QApplication::setApplicationName(QStringLiteral("DivergenceSplitter"));
    QApplication::setOrganizationName(QStringLiteral("Nanahuse"));
    QApplication::setApplicationVersion(QStringLiteral(DIVERGENCESPLITTER_VERSION));

    divergencesplitter::ui::AppController controller;
    divergencesplitter::ui::MainWindow window(&controller);
    window.show();
    // Distribution smoke test: run the real GUI event loop, verify a native
    // window and the application-local SDK, then shut down normally. This works
    // with hidden CI windows where Process.MainWindowTitle is unavailable.
    if (application.arguments().contains(QStringLiteral("--smoke-test"))) {
        QTimer::singleShot(100, &application, [&] {
            try {
                if (divergencesplitter::ndi_enabled())
                    (void)divergencesplitter::acquire_ndi_runtime();
                application.exit(window.winId() != 0 && window.isVisible() ? 0 : 3);
            } catch (const std::exception&) {
                application.exit(3);
            }
        });
    }
    return application.exec();
}
