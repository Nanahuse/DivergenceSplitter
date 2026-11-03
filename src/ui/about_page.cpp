#include "about_page.hpp"

#include <QCoreApplication>
#include <QFrame>
#include <QLabel>
#include <QTextBrowser>
#include <QVBoxLayout>
#include <QUrl>

#include "divergencesplitter/capture/ndi.hpp"

namespace divergencesplitter::ui {

AboutPage::AboutPage(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("page"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 20, 24, 20);
    layout->setSpacing(8);

    auto* title = new QLabel(tr("DivergenceSplitter"), this);
    title->setObjectName(QStringLiteral("pageTitle"));
    layout->addWidget(title);

    const QString version_text = QCoreApplication::applicationVersion().isEmpty()
        ? QStringLiteral(DIVERGENCESPLITTER_VERSION)
        : QCoreApplication::applicationVersion();
    auto* version = new QLabel(tr("Version %1").arg(version_text), this);
    version->setProperty("role", QStringLiteral("muted"));
    layout->addWidget(version);

    auto* links = new QLabel(
        tr("<a href=\"https://github.com/Nanahuse/DivergenceSplitter\">GitHub</a>"
           " &nbsp;&nbsp; "
           "<a href=\"https://ndi.video/\">NDI website</a>"),
        this
    );
    links->setOpenExternalLinks(true);
    layout->addWidget(links);

    auto* trademark = new QLabel(
        tr("NDI® is a registered trademark of Vizrt NDI AB."), this
    );
    trademark->setProperty("role", QStringLiteral("muted"));
    trademark->setWordWrap(true);
    layout->addWidget(trademark);

    auto* divider = new QFrame(this);
    divider->setObjectName(QStringLiteral("dividerLine"));
    divider->setFrameShape(QFrame::HLine);
    divider->setFixedHeight(1);
    layout->addWidget(divider);

    auto* browser = new QTextBrowser(this);
    browser->setOpenExternalLinks(true);
    browser->setFrameShape(QFrame::NoFrame);
    browser->setHtml(tr(
        "<h3>Components</h3>"
        "<ul>"
        "<li>Qt Widgets interface</li>"
        "<li>OpenCV image processing</li>"
        "<li>livesplit-bridge-client-cpp (LiveSplit.Bridge JSON protocol)</li>"
        "<li>rapidyaml (ryml) scenario loading</li>"
        "</ul>"
        "<h3>NDI®</h3>"
        "<p>%1</p>"
        "<p>NDI® is a registered trademark of Vizrt NDI AB. The bundled NDI runtime is "
        "separately licensed by NDI, Inc. / Vizrt NDI AB. "
        "Its <a href=\"%2\">use terms</a> form part of this distribution's terms of use. "
        "See also Processing.NDI.Lib.Licenses.txt and the "
        "<a href=\"https://ndi.link/ndisdk_license\">official NDI SDK License Agreement</a>. "
        "The SDK agreement PDF is not bundled.</p>"
        "<h3>License</h3>"
        "<p>DivergenceSplitter is distributed under the MIT License. Third-party license "
        "notices are included in the distribution under <code>licenses/</code> and "
        "<code>DISTRIBUTION-NOTICE.txt</code>.</p>"
    ).arg(
        ndi_enabled() ? tr("NDI input is enabled; the Windows ZIP includes its runtime.")
                      : tr("NDI input is disabled in this development build."),
        QUrl::fromLocalFile(
            QCoreApplication::applicationDirPath() + "/licenses/NDI-TERMS.txt"
        ).toString()
    ));
    layout->addWidget(browser, 1);
}

}  // namespace divergencesplitter::ui
