#include "divergencesplitter/ui/image_view.hpp"

#include <QPainter>
#include <QPaintEvent>

#include <opencv2/imgproc.hpp>

namespace divergencesplitter::ui {

QImage mat_to_qimage(const cv::Mat& image) {
    if (image.empty()) {
        return {};
    }
    cv::Mat converted;
    if (image.depth() != CV_8U) {
        double minimum = 0.0;
        double maximum = 0.0;
        cv::minMaxLoc(image.reshape(1), &minimum, &maximum);
        const double scale = maximum > minimum ? 255.0 / (maximum - minimum) : 1.0;
        image.convertTo(converted, CV_8U, scale, -minimum * scale);
    } else {
        converted = image;
    }

    if (converted.channels() == 1) {
        cv::Mat continuous = converted.clone();
        return QImage(
                   continuous.data,
                   continuous.cols,
                   continuous.rows,
                   static_cast<int>(continuous.step),
                   QImage::Format_Grayscale8
        ).copy();
    }
    if (converted.channels() == 3) {
        cv::Mat rgb;
        cv::cvtColor(converted, rgb, cv::COLOR_BGR2RGB);
        return QImage(
                   rgb.data,
                   rgb.cols,
                   rgb.rows,
                   static_cast<int>(rgb.step),
                   QImage::Format_RGB888
        ).copy();
    }
    if (converted.channels() == 4) {
        cv::Mat rgba;
        cv::cvtColor(converted, rgba, cv::COLOR_BGRA2RGBA);
        return QImage(
                   rgba.data,
                   rgba.cols,
                   rgba.rows,
                   static_cast<int>(rgba.step),
                   QImage::Format_RGBA8888
        ).copy();
    }
    return {};
}

ImageView::ImageView(QWidget* parent) : QWidget(parent) {
    setMinimumSize(320, 180);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
}

void ImageView::set_image(const QImage& image) {
    image_ = image;
    update();
}

void ImageView::clear() {
    image_ = {};
    update();
}

QSize ImageView::sizeHint() const {
    return {640, 360};
}

void ImageView::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.fillRect(rect(), palette().color(QPalette::Window));
    if (image_.isNull()) {
        painter.setPen(palette().color(QPalette::Text));
        painter.drawText(rect(), Qt::AlignCenter, tr("No input"));
        return;
    }
    const QSize target = image_.size().scaled(size(), Qt::KeepAspectRatio);
    const QRect destination{
        (width() - target.width()) / 2,
        (height() - target.height()) / 2,
        target.width(),
        target.height(),
    };
    painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
    painter.drawImage(destination, image_);
}

}  // namespace divergencesplitter::ui
