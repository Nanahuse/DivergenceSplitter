#include "divergencesplitter/ui/about_page.hpp"

#include <QCoreApplication>
#include <QTextBrowser>
#include <QVBoxLayout>

namespace divergencesplitter::ui {

AboutPage::AboutPage(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    auto* browser = new QTextBrowser(this);
    browser->setOpenExternalLinks(true);
    browser->setHtml(tr(
        "<h2>DivergenceSplitter %1</h2>"
        "<p>Automatic splitter for LiveSplit.Bridge.</p>"
        "<p>This application is the C++23 rewrite. Scenarios are declarative YAML; "
        "Python scenario modules are intentionally not executed.</p>"
        "<h3>Components</h3>"
        "<ul>"
        "<li>Qt Widgets interface</li>"
        "<li>OpenCV image processing</li>"
        "<li>livesplit-bridge-client-cpp (LiveSplit.Bridge JSON protocol)</li>"
        "<li>yaml-cpp scenario loading</li>"
        "</ul>"
        "<h3>NDI</h3>"
        "<p>NDI input is kept as a planned source. Builds without the NDI SDK report a clear "
        "configuration error instead of silently falling back to another input.</p>"
        "<h3>License</h3>"
        "<p>DivergenceSplitter is distributed under the MIT License. Third-party license "
        "notices are included in the distribution under <code>licenses/</code> and "
        "<code>DISTRIBUTION-NOTICE.txt</code>.</p>"
    ).arg(QCoreApplication::applicationVersion()));
    layout->addWidget(browser);
}

}  // namespace divergencesplitter::ui
