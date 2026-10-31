#include "divergencesplitter/ui/profile_preview.hpp"

#include <chrono>
#include "divergencesplitter/ui/image_view.hpp"

namespace divergencesplitter::ui {
namespace {
SourceConfiguration input_identity(SourceConfiguration source) {
    std::visit([](auto& value) { value.transform = {}; }, source);
    return source;
}
}

ProfilePreview::ProfilePreview(SourceFactory factory) : factory_(std::move(factory)) {}
ProfilePreview::~ProfilePreview() { stop(); }

void ProfilePreview::configure(const SourceConfiguration& source) {
    std::scoped_lock lock{mutex_};
    if (requested_ == source) return;
    requested_ = source;
    ++revision_;
    snapshot_ = {};
    snapshot_.revision = revision_;
    stopping_ = false;
    if (!thread_.joinable()) thread_ = std::thread(&ProfilePreview::run, this);
    cv_.notify_all();
}

void ProfilePreview::stop() {
    {
        std::scoped_lock lock{mutex_};
        stopping_ = true;
    }
    cv_.notify_all();
    if (thread_.joinable()) thread_.join();
    std::scoped_lock lock{mutex_};
    requested_.reset();
    snapshot_ = {};
}

ProfilePreviewSnapshot ProfilePreview::snapshot() const {
    std::scoped_lock lock{mutex_};
    return snapshot_;
}

void ProfilePreview::run() {
    using namespace std::chrono;
    std::unique_ptr<FrameSource> source;
    cv::Mat latest_frame;
    std::optional<SourceConfiguration> identity;
    auto next_preview = steady_clock::now();
    auto sample_started = next_preview;
    std::uint64_t frames{};
    double fps{};
    std::uint64_t previous_revision{};
    while (true) {
        SourceConfiguration requested;
        std::uint64_t revision;
        {
            std::scoped_lock lock{mutex_};
            if (stopping_) break;
            requested = *requested_;
            revision = revision_;
        }
        try {
            const auto next_identity = input_identity(requested);
            if (!source || identity != next_identity) {
                if (source) source->close();
                source.reset();
                latest_frame.release();
                source = factory_(requested);
                if (!source) throw std::runtime_error("preview source is unavailable");
                source->open();
                identity = next_identity;
                frames = 0;
                fps = 0;
                sample_started = steady_clock::now();
            }
            MonotonicTime captured_at;
            const cv::Mat received = source->read(captured_at);
            const auto now = steady_clock::now();
            if (!received.empty()) {
                latest_frame = received;
                ++frames;
            } else if (latest_frame.empty() || previous_revision == revision) {
                std::unique_lock lock{mutex_};
                cv_.wait_for(lock, milliseconds{10}, [&] { return stopping_ || revision_ != revision; });
                continue;
            }
            const auto elapsed = duration<double>(now - sample_started).count();
            if (elapsed >= 1.0) {
                fps = static_cast<double>(frames) / elapsed;
                frames = 0;
                sample_started = now;
            }
            if (now < next_preview && previous_revision == revision) continue;
            previous_revision = revision;
            next_preview = now + milliseconds{100};
            ProfilePreviewSnapshot result;
            result.revision = revision;
            result.input = source->opened_format();
            if (result.input.width <= 0) result.input.width = latest_frame.cols;
            if (result.input.height <= 0) result.input.height = latest_frame.rows;
            result.measured_fps = fps;
            try {
                auto normalizer = std::visit([](const auto& value) {
                    return create_frame_normalizer(value.transform);
                }, requested);
                result.image = mat_to_qimage(normalizer.normalize(latest_frame));
            } catch (const std::exception& error) {
                result.error = error.what();
            }
            std::scoped_lock lock{mutex_};
            if (!stopping_ && revision_ == revision) snapshot_ = std::move(result);
        } catch (const std::exception& error) {
            if (source) source->close();
            source.reset();
            latest_frame.release();
            identity.reset();
            std::unique_lock lock{mutex_};
            if (revision_ == revision) {
                snapshot_ = {};
                snapshot_.revision = revision;
                snapshot_.error = error.what();
            }
            cv_.wait(lock, [&] { return stopping_ || revision_ != revision; });
        }
    }
    if (source) source->close();
}

}  // namespace divergencesplitter::ui
