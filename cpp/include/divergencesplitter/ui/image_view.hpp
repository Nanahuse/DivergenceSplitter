#pragma once

#include <QImage>
#include <QWidget>

#include <opencv2/core.hpp>

namespace divergencesplitter::ui {

[[nodiscard]] QImage mat_to_qimage(const cv::Mat& image);

class ImageView final : public QWidget {
    Q_OBJECT

public:
    explicit ImageView(QWidget* parent = nullptr);

    void set_image(const QImage& image);
    void clear();
    [[nodiscard]] QSize sizeHint() const override;

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    QImage image_;
};

}  // namespace divergencesplitter::ui
