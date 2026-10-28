#include <QApplication>

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
    return application.exec();
}
