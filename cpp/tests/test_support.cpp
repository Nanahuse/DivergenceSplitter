#include "test_support.hpp"

#include <string>

namespace divergencesplitter::test {

cv::Mat solid(int width, int height, int gray) {
    return cv::Mat(height, width, CV_8UC1, cv::Scalar(static_cast<double>(gray), 0.0, 0.0, 0.0)).clone();
}

BridgeSnapshot make_snapshot(
    TimerPhase phase,
    std::int32_t split_index,
    std::int32_t split_count,
    std::uint64_t revision,
    std::uint32_t session_id
) {
    (void)revision;
    BridgeSnapshot snapshot;
    snapshot.session_id = session_id;
    snapshot.phase = phase;
    snapshot.split_index = split_index;
    snapshot.split_count = split_count;
    snapshot.game_name = "Test Game";
    snapshot.category_name = "Any%";
    snapshot.segment_names.reserve(static_cast<std::size_t>(split_count));
    for (int index = 0; index < split_count; ++index) {
        snapshot.segment_names.push_back("Segment " + std::to_string(index));
    }
    return snapshot;
}

FrameContext make_context(const cv::Mat& image, ManualTimeProvider& time) {
    auto shared = std::make_shared<SharedFrameEvaluation>(
        SharedFrameEvaluation{Frame{image.clone(), time.now()}, time.now(), {}}
    );
    return FrameContext{std::move(shared)};
}

}  // namespace divergencesplitter::test
