#include "divergencesplitter/ui/about_page.hpp"

#include <QCoreApplication>
#include <QTextBrowser>
#include <QVBoxLayout>
#include <QUrl>

#include "divergencesplitter/capture/ndi.hpp"

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
        "<h3>NDI®</h3>"
        "<p><a href=\"https://ndi.video/\">NDI — ndi.video</a>. %2</p>"
        "<p>NDI® is a registered trademark of Vizrt NDI AB. The bundled NDI runtime is "
        "separately licensed by NDI, Inc. / Vizrt NDI AB. "
        "Its <a href=\"%3\">use terms</a> form part of this distribution's terms of use. "
        "See also Processing.NDI.Lib.Licenses.txt and the "
        "<a href=\"https://ndi.link/ndisdk_license\">official NDI SDK License Agreement</a>. "
        "The SDK agreement PDF is not bundled.</p>"
        "<h3>License</h3>"
        "<p>DivergenceSplitter is distributed under the MIT License. Third-party license "
        "notices are included in the distribution under <code>licenses/</code> and "
        "<code>DISTRIBUTION-NOTICE.txt</code>.</p>"
    ).arg(QCoreApplication::applicationVersion(),
        ndi_enabled() ? tr("NDI input is enabled; the Windows ZIP includes its runtime.") :
                        tr("NDI input is disabled in this development build."),
        QUrl::fromLocalFile(QCoreApplication::applicationDirPath() + "/licenses/NDI-TERMS.txt").toString()));
    layout->addWidget(browser);
}

}  // namespace divergencesplitter::ui
