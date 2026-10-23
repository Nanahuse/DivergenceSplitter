#pragma once
#include "images.hpp"
#include "mock.hpp"
#include <filesystem>
#include <string_view>

namespace comparison {
enum class Page { monitor, diagnostics, profile };
enum class Action {
    monitor, diagnostics, profile, expand, collapse, mutate,
    invalid_draft, valid_draft, apply, add_scenario, remove_scenario,
    unsaved_cancel, file_cancel, discard, reset_press, reset_release,
    reset_cancel, theme, resize, start, stop, scroll, expand_dynamic
};
struct Options {
    bool self_test = false;
    bool large = false;
    bool dark = false;
    bool hold_on_exit = false;
    double seconds = 0;
    double warmup = 0;
    Page page = Page::monitor;
    bool exercise = false;
    std::filesystem::path report;
    std::filesystem::path capture;
    static Options parse(int argc, char** argv);
};
struct Probe {
    Page page = Page::monitor;
    bool expanded = false;
    bool dirty = false;
    bool errors = false;
    std::size_t references = 0;
    std::size_t draft_count = 0;
    int scroll = 0;
    bool busy = false;
    unsigned file_cancels = 0;
    unsigned discard_cancels = 0;
};
struct Counters {
    std::uint64_t topology_builds = 0;
    std::uint64_t value_updates = 0;
    std::uint64_t presented = 0; // GUI intake, not proof of display scanout.
    std::uint64_t last_frame = 0;
    std::uint64_t skipped_frames = 0;
    std::uint64_t peak_private_bytes = 0;
    std::uint64_t peak_working_set = 0;
    std::vector<double> frame_age_ms;
    double first_frame_ms = -1;
    double first_process_frame_ms = -1;
};
class Driver;
struct MemorySample { double seconds; std::uint64_t private_bytes, working_set; };
class Session {
public:
    explicit Session(Options options, std::string candidate);
    ~Session();
    Options options;
    MockEngine engine;
    ProfileEditor profile;
    Counters counters;
    std::vector<std::string> checks;
    std::string error;
    std::string renderer;
    void observe_frame(const Frame& frame);
    void sample_process();
    void exercise(Driver& driver);
    bool expired() const;
    double elapsed() const;
    void write_report() const;
private:
    std::string candidate_;
    Time started_ = std::chrono::steady_clock::now();
    Time measured_ = started_, sampled_{};
    double cpu_baseline_ = 0;
    std::uint64_t frame_baseline_ = 0;
    bool warmed_ = false, page_initialized_ = false;
    unsigned exercise_step_ = 0;
    Time exercise_at_{};
    std::vector<MemorySample> memory_samples_;
};
class Driver {
public:
    virtual ~Driver() = default;
    virtual void perform(Action action) = 0;
    virtual Probe probe() const = 0;
};
// Runs on each library's own event loop; adapters provide actual control actions.
// Modal cancellation remains an adapter test, not a backend mock result.
class ContractScript {
public:
    explicit ContractScript(Session& session) : session_(session) {}
    bool tick(Driver& driver); // true once complete or failed.
private:
    void next();
    void require(bool condition, const char* message);
    Session& session_;
    int step_ = 0;
    int mutation_phase_ = 0;
    Time since_ = std::chrono::steady_clock::now();
    Time started_ = since_;
    std::uint64_t builds_ = 0, requests_ = 0, revision_ = 0, resets_ = 0, updates_ = 0;
    std::size_t scenarios_ = 0;
    int scroll_ = 0;
    bool active_ = false;
    bool scroll_ready_ = false;
};
std::string score_text(double score);
}
