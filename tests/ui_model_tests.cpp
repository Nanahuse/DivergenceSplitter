#include <gtest/gtest.h>

#include <imgui.h>
#include <opencv2/core.hpp>

#include <atomic>
#include <chrono>
#include <filesystem>
#include <future>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"
#include "divergencesplitter/text.hpp"

#include "monitor_model.hpp"
#include "ndi_discovery.hpp"
#include "profile_document.hpp"
#include "profile_preview.hpp"
#include "profile_source_ui.hpp"

namespace divergencesplitter::ui {
namespace {

Profile make_profile(int port = 54000) {
    Profile profile;
    profile.source = VideoSourceConfiguration{
        "C:/videos/frame%02d.png",
        {std::nullopt, ResizeConfiguration{3, 3, ResizeInterpolation::linear, false}},
    };
    profile.instances.push_back({{port}, "C:/scenarios/example.yaml"});
    return profile;
}

template <typename Predicate>
bool wait_until(Predicate predicate, std::chrono::milliseconds timeout = std::chrono::seconds{5}) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (predicate()) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds{5});
    }
    return predicate();
}

struct PreviewProbe {
    std::atomic_int opens{};
    std::atomic_int closes{};
    std::atomic_bool active{};
    std::atomic_bool wrong_thread{};
    std::atomic_bool paused{};
    std::thread::id gui_thread{std::this_thread::get_id()};
};

class PreviewSource final : public FrameSource {
public:
    explicit PreviewSource(std::shared_ptr<PreviewProbe> probe) : probe_(std::move(probe)) {}

    void open() override {
        check_thread();
        ++probe_->opens;
        probe_->active = true;
    }

    cv::Mat read(MonotonicTime& captured_at) override {
        check_thread();
        std::this_thread::sleep_for(std::chrono::milliseconds{5});
        captured_at = monotonic_now();
        if (probe_->paused.load()) {
            return {};
        }
        cv::Mat image(4, 8, CV_8UC3, cv::Scalar::all(10));
        image.colRange(4, 8).setTo(cv::Scalar::all(240));
        return image;
    }

    void close() noexcept override {
        check_thread();
        if (probe_->active.exchange(false)) {
            ++probe_->closes;
        }
    }

    std::string describe() const override { return "preview fixture"; }
    Format opened_format() const override { return {8, 4, 60.0}; }

private:
    void check_thread() const {
        if (std::this_thread::get_id() == probe_->gui_thread) {
            probe_->wrong_thread = true;
        }
    }

    std::shared_ptr<PreviewProbe> probe_;
};

}  // namespace

TEST(ProfileDocument, TracksDraftSavedAndNewStates) {
    const auto profile = make_profile();
    const std::filesystem::path path{L"C:/profiles/profile.json"};
    ProfileDocument document;
    document.adopt_saved(profile, path);

    EXPECT_FALSE(document.dirty());
    ASSERT_TRUE(document.path.has_value());
    EXPECT_EQ(*document.path, path);

    document.draft.instances[0].connection.port = 54001;
    EXPECT_TRUE(document.dirty());

    document.mark_saved(document.draft, std::filesystem::path{L"C:/profiles/saved.json"});
    EXPECT_FALSE(document.dirty());
    EXPECT_EQ(document.saved->instances[0].connection.port, 54001);

    document.draft.instances[0].connection.port = 54002;
    EXPECT_TRUE(document.dirty());
    document.revert_draft(profile);
    EXPECT_TRUE(document.dirty());
    EXPECT_EQ(document.draft.instances[0].connection.port, 54000);
    EXPECT_EQ(document.saved->instances[0].connection.port, 54001);

    document.start_new(std::filesystem::path{L"C:/profiles/new.json"});
    EXPECT_TRUE(document.dirty());
    EXPECT_FALSE(document.saved.has_value());
    EXPECT_TRUE(document.path.has_value());
    EXPECT_TRUE(document.draft.instances.empty());
}

TEST(ProfileDocument, ApplyDoesNotChangeSavedState) {
    const auto profile = make_profile();
    ProfileDocument document;
    document.adopt_saved(profile, std::filesystem::path{L"C:/profiles/profile.json"});
    document.draft.instances[0].connection.port = 55000;

    // The controller stores the applied profile separately. An apply success
    // must not make the edited draft look saved.
    EXPECT_TRUE(document.dirty());
    EXPECT_EQ(document.saved->instances[0].connection.port, 54000);
}

TEST(MonitorModel, SummarizesScoresAndResetConfirmation) {
    Scenario scenario;
    scenario.start_condition = std::make_shared<DetectedCondition>(
        std::make_shared<MeanBrightnessDetector>(),
        0.9
    );
    ScenarioRuntime runtime{std::move(scenario)};
    runtime.apply_update(
        {UpdateKind::initial, {1, 1, 1, TimerPhase::not_running, -1, 2}, {}}
    );
    (void)runtime.evaluate(
        FrameContext{Frame{cv::Mat(2, 2, CV_8UC1, cv::Scalar{128}), {}}, {}}
    );
    const auto overview = scenario_overview(runtime.diagnostics());
    EXPECT_NE(overview.find("mean_brightness"), std::string::npos);
    EXPECT_NE(overview.find("0.5020 / 0.9000"), std::string::npos);
    EXPECT_NE(overview.find("Max:"), std::string::npos);

    auto diagnostics = runtime.diagnostics();
    diagnostics.reset_pending = ActionOperation::reset;
    EXPECT_NE(
        scenario_overview(diagnostics).find("Reset confirmation"),
        std::string::npos
    );
}

TEST(ProfilePreview, TransformsRunOnWorkerWithoutReopeningInput) {
    auto probe = std::make_shared<PreviewProbe>();
    ProfilePreview preview([probe](const auto&) {
        return std::make_unique<PreviewSource>(probe);
    });
    SourceConfiguration source = NdiSourceConfiguration{"sender", {}};
    preview.configure(source);
    ASSERT_TRUE(wait_until([&] { return !preview.snapshot().image.empty(); }));
    EXPECT_EQ(preview.snapshot().image.size(), cv::Size(8, 4));

    probe->paused = true;
    auto& transform = std::get<NdiSourceConfiguration>(source).transform;
    transform.crop = CropConfiguration{0, 4, 0, 0};
    transform.resize = ResizeConfiguration{3, 2};
    preview.configure(source);
    ASSERT_TRUE(wait_until([&] { return preview.snapshot().image.size() == cv::Size(3, 2); }));
    const auto pixel = preview.snapshot().image.at<cv::Vec3b>(1, 1);
    EXPECT_EQ(pixel[0], 10);
    EXPECT_EQ(pixel[1], 10);
    EXPECT_EQ(pixel[2], 10);
    EXPECT_EQ(probe->opens.load(), 1);
    EXPECT_EQ(preview.snapshot().input.width, 8);
    EXPECT_DOUBLE_EQ(preview.snapshot().input.fps, 60.0);

    transform.crop->right = 8;
    preview.configure(source);
    ASSERT_TRUE(wait_until([&] { return !preview.snapshot().error.empty(); }));
    EXPECT_TRUE(preview.snapshot().image.empty());

    transform.crop->right = 4;
    preview.configure(source);
    ASSERT_TRUE(wait_until([&] { return preview.snapshot().image.size() == cv::Size(3, 2); }));
    EXPECT_EQ(probe->opens.load(), 1);

    std::get<NdiSourceConfiguration>(source).name = "different sender";
    preview.configure(source);
    ASSERT_TRUE(wait_until([&] { return probe->opens.load() == 2; }));
    preview.stop();
    EXPECT_EQ(probe->closes.load(), 2);
    EXPECT_FALSE(probe->wrong_thread.load());
}

TEST(ProfilePreview, FailureCanBeRetried) {
    std::atomic_int attempts{};
    auto probe = std::make_shared<PreviewProbe>();
    ProfilePreview preview([&](const auto&) -> std::unique_ptr<FrameSource> {
        if (++attempts == 1) {
            throw FrameSourceError("offline sender", true);
        }
        return std::make_unique<PreviewSource>(probe);
    });
    SourceConfiguration source = NdiSourceConfiguration{"sender", {}};
    preview.configure(source);
    ASSERT_TRUE(wait_until([&] { return preview.snapshot().error == "offline sender"; }));
    preview.stop();
    preview.configure(source);
    ASSERT_TRUE(wait_until([&] { return !preview.snapshot().image.empty(); }));
    EXPECT_TRUE(preview.snapshot().error.empty());
    preview.stop();
}

TEST(Text, Utf8PathsRoundTripJapanese) {
    const std::string value = reinterpret_cast<const char*>(
        u8"C:/資料/シナリオ/テスト.yaml"
    );
    const auto path = path_from_utf8(value);
    EXPECT_EQ(path_to_utf8(path), value);
    EXPECT_EQ(to_utf8(to_wide(value)), value);
}

TEST(NdiDiscoveryWorker, RepeatedSearchesPublishResults) {
    std::atomic_int calls{};
    NdiDiscoveryWorker worker([&] {
        ++calls;
        return std::vector<std::string>{"sender A", "sender B"};
    });
    for (int iteration = 0; iteration < 50; ++iteration) {
        worker.start();
        std::optional<NdiDiscoveryResult> result;
        ASSERT_TRUE(wait_until([&] {
            result = worker.take_result();
            return result.has_value();
        }));
        ASSERT_TRUE(result->error.empty());
        ASSERT_EQ(result->sources.size(), 2);
        EXPECT_EQ(result->sources[0], "sender A");
        EXPECT_FALSE(worker.busy());
    }
    EXPECT_EQ(calls.load(), 50);
}

TEST(NdiDiscoveryWorker, BusySearchBlocksRestartAndReportsErrors) {
    std::promise<void> release;
    auto ready = release.get_future();
    NdiDiscoveryWorker worker([&]() -> std::vector<std::string> {
        ready.wait();
        throw std::runtime_error("offline sender");
    });
    worker.start();
    EXPECT_TRUE(worker.busy());
    worker.start();
    release.set_value();

    std::optional<NdiDiscoveryResult> result;
    ASSERT_TRUE(wait_until([&] {
        result = worker.take_result();
        return result.has_value();
    }));
    EXPECT_EQ(result->error, "offline sender");
    EXPECT_TRUE(result->sources.empty());
    EXPECT_FALSE(worker.busy());
}


TEST(ImGuiLabels, ResetButtonKeepsStableIdWhileCountingDown) {
    ImGuiContext* context = ImGui::CreateContext();
    ImGui::SetCurrentContext(context);
    ImGui::GetIO().DisplaySize = ImVec2(800.0f, 600.0f);
    ImGui::GetIO().Fonts->AddFontDefault();
    ImGui::GetIO().Fonts->Build();
    ImGui::NewFrame();
    const ImGuiID idle = ImGui::GetID("Reset All###reset_all");
    const ImGuiID holding = ImGui::GetID("Hold... 1.0 s###reset_all");
    const ImGuiID triggered = ImGui::GetID("Reset requested###reset_all");
    ImGui::EndFrame();
    ImGui::DestroyContext(context);
    EXPECT_EQ(idle, holding);
    EXPECT_EQ(idle, triggered);
}


TEST(ProfileSourceSwitching, SwitchesAllTypesAndPreservesTransform) {
    Profile profile;
    profile.source = VideoSourceConfiguration{
        "video.mp4",
        {CropConfiguration{1, 2, 3, 4},
         ResizeConfiguration{5, 6, ResizeInterpolation::cubic, true}},
    };
    const TransformConfiguration transform =
        std::get<VideoSourceConfiguration>(profile.source).transform;

    switch_profile_source_type(profile, 0);
    EXPECT_EQ(source_type_index(profile.source), 0);
    EXPECT_EQ(std::get<CameraSourceConfiguration>(profile.source).transform, transform);

    switch_profile_source_type(profile, 2);
    EXPECT_EQ(source_type_index(profile.source), 2);
    EXPECT_EQ(std::get<NdiSourceConfiguration>(profile.source).transform, transform);

    switch_profile_source_type(profile, 1);
    EXPECT_EQ(source_type_index(profile.source), 1);
    EXPECT_EQ(std::get<VideoSourceConfiguration>(profile.source).transform, transform);

    std::get<VideoSourceConfiguration>(profile.source).path = "keep.mp4";
    switch_profile_source_type(profile, 1);
    EXPECT_EQ(std::get<VideoSourceConfiguration>(profile.source).path, "keep.mp4");
}

TEST(ProfileSourceSwitching, RadioClickReturnsNewTypeInTheSameFrame) {
    ImGuiContext* context = ImGui::CreateContext();
    ImGui::SetCurrentContext(context);
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(800.0f, 600.0f);
    io.DeltaTime = 1.0f / 60.0f;
    io.Fonts->AddFontDefault();
    io.Fonts->Build();

    Profile profile;
    profile.source = CameraSourceConfiguration{};
    SourceTypeRadioLayout layout;

    const auto frame = [&](bool mouse_down, bool mouse_up) {
        if (mouse_down) {
            io.AddMouseButtonEvent(0, true);
        }
        if (mouse_up) {
            io.AddMouseButtonEvent(0, false);
        }
        ImGui::NewFrame();
        ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f));
        ImGui::SetNextWindowSize(ImVec2(400.0f, 200.0f));
        ImGui::Begin("source_type_test");
        const int type = draw_source_type_radio(profile, true, &layout);
        ImGui::End();
        ImGui::EndFrame();
        return type;
    };

    (void)frame(false, false);
    const ImVec2 video_center(
        (layout.video_min.x + layout.video_max.x) * 0.5f,
        (layout.video_min.y + layout.video_max.y) * 0.5f
    );
    io.AddMousePosEvent(video_center.x, video_center.y);
    (void)frame(true, false);
    EXPECT_EQ(frame(false, true), 1);
    EXPECT_TRUE(std::holds_alternative<VideoSourceConfiguration>(profile.source));

    const ImVec2 ndi_center(
        (layout.ndi_min.x + layout.ndi_max.x) * 0.5f,
        (layout.ndi_min.y + layout.ndi_max.y) * 0.5f
    );
    io.AddMousePosEvent(ndi_center.x, ndi_center.y);
    (void)frame(true, false);
    EXPECT_EQ(frame(false, true), 2);
    EXPECT_TRUE(std::holds_alternative<NdiSourceConfiguration>(profile.source));

    ImGui::DestroyContext(context);
}

TEST(ProfileSourceSwitching, UnavailableNdiKeepsSavedSourceAndDisablesSwitch) {
    ImGuiContext* context = ImGui::CreateContext();
    ImGui::SetCurrentContext(context);
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(800.0f, 600.0f);
    io.DeltaTime = 1.0f / 60.0f;
    io.Fonts->AddFontDefault();
    io.Fonts->Build();

    Profile profile;
    profile.source = CameraSourceConfiguration{};
    SourceTypeRadioLayout layout;

    const auto frame = [&](bool mouse_down, bool mouse_up) {
        if (mouse_down) {
            io.AddMouseButtonEvent(0, true);
        }
        if (mouse_up) {
            io.AddMouseButtonEvent(0, false);
        }
        ImGui::NewFrame();
        ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f));
        ImGui::SetNextWindowSize(ImVec2(400.0f, 200.0f));
        ImGui::Begin("unavailable_ndi_test");
        const int type = draw_source_type_radio(profile, false, &layout);
        ImGui::End();
        ImGui::EndFrame();
        return type;
    };

    (void)frame(false, false);
    const ImVec2 ndi_center(
        (layout.ndi_min.x + layout.ndi_max.x) * 0.5f,
        (layout.ndi_min.y + layout.ndi_max.y) * 0.5f
    );
    io.AddMousePosEvent(ndi_center.x, ndi_center.y);
    (void)frame(true, false);
    EXPECT_EQ(frame(false, true), 0);
    EXPECT_TRUE(std::holds_alternative<CameraSourceConfiguration>(profile.source));

    profile.source = NdiSourceConfiguration{"offline", {}};
    EXPECT_EQ(frame(false, false), 2);
    EXPECT_EQ(std::get<NdiSourceConfiguration>(profile.source).name, "offline");

    ImGui::DestroyContext(context);
}

}  // namespace divergencesplitter::ui
