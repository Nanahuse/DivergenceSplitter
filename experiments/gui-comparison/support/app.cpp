#include "app.hpp"
#include <windows.h>
#include <psapi.h>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace comparison {
namespace {
std::string quoted(std::string_view value) {
    std::string out = "\"";
    for (char ch : value) {
        if (ch == '\\' || ch == '"') { out += '\\'; out += ch; }
        else if (ch == '\n') out += "\\n";
        else if (ch == '\r') out += "\\r";
        else if (ch == '\t') out += "\\t";
        else if (static_cast<unsigned char>(ch) >= 32) out += ch;
    }
    return out + '"';
}
double percentile(std::vector<double> values, double fraction) {
    if (values.empty()) return 0;
    std::ranges::sort(values);
    return values[std::min(values.size() - 1, std::size_t(fraction * double(values.size() - 1)))];
}
double cpu_seconds() {
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) throw std::runtime_error("Process CPU query failed");
    auto ticks = [](FILETIME time) { return (std::uint64_t(time.dwHighDateTime) << 32) | time.dwLowDateTime; };
    return double(ticks(kernel) + ticks(user)) / 10'000'000.0;
}
}
Options Options::parse(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto value = [&]() -> std::string {
            if (++i >= argc) throw std::invalid_argument("Missing CLI value");
            return argv[i];
        };
        if (arg == "--self-test") options.self_test = true;
        else if (arg == "--large") options.large = true;
        else if (arg == "--dark") options.dark = true;
        else if (arg == "--hold-on-exit") options.hold_on_exit = true;
        else if (arg == "--seconds") options.seconds = std::stod(value());
        else if (arg == "--warmup") options.warmup = std::stod(value());
        else if (arg == "--exercise") options.exercise = true;
        else if (arg == "--page") {
            const auto page = value();
            if (page == "monitor") options.page = Page::monitor;
            else if (page == "diagnostics") options.page = Page::diagnostics;
            else if (page == "profile") options.page = Page::profile;
            else throw std::invalid_argument("Unknown page");
        }
        else if (arg == "--report") options.report = value();
        else if (arg == "--capture") options.capture = value();
        else throw std::invalid_argument("Unknown argument: " + arg);
    }
    if (!std::isfinite(options.seconds) || !std::isfinite(options.warmup) || options.seconds < 0 || options.warmup < 0)
        throw std::invalid_argument("Run duration must be finite and nonnegative");
    if (options.self_test && (options.warmup || options.exercise || options.page != Page::monitor || options.hold_on_exit))
        throw std::invalid_argument("Self-test cannot be mixed with benchmark options");
    if (options.hold_on_exit && (options.warmup || options.seconds <= 0 || options.seconds >= 2 || options.exercise || options.page != Page::monitor))
        throw std::invalid_argument("Exit-hold test requires Monitor, no warmup/exercise, and a duration below two seconds");
    return options;
}
Session::Session(Options value, std::string candidate)
    : options(std::move(value)), engine({options.large ? Shape::large() : Shape{}}),
      profile(*engine.state()->applied_profile), candidate_(std::move(candidate)) {
    if (options.capture.has_parent_path()) std::filesystem::create_directories(options.capture.parent_path());
    verify_opencv_stack();
    engine.start();
}
Session::~Session() { engine.stop(); }
void Session::observe_frame(const Frame& frame) {
    if (frame.sequence <= counters.last_frame) return;
    const auto now = std::chrono::steady_clock::now();
    if (counters.first_frame_ms < 0) {
        counters.first_frame_ms = std::chrono::duration<double, std::milli>(now - started_).count();
        FILETIME created{}, exited{}, kernel{}, user{}, wall{};
        if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) throw std::runtime_error("Process creation time unavailable");
        GetSystemTimePreciseAsFileTime(&wall);
        auto ticks = [](FILETIME time) { return (std::uint64_t(time.dwHighDateTime) << 32) | time.dwLowDateTime; };
        counters.first_process_frame_ms = double(ticks(wall) - ticks(created)) / 10'000.0;
    } else counters.skipped_frames += frame.sequence - counters.last_frame - 1;
    counters.last_frame = frame.sequence;
    ++counters.presented;
    // Bound telemetry memory on long runs. External process sampling records RSS/private bytes.
    if (counters.frame_age_ms.size() < 100'000) {
        counters.frame_age_ms.push_back(std::chrono::duration<double, std::milli>(now - frame.captured_at).count());
    }
}
void Session::sample_process() {
    const auto now = std::chrono::steady_clock::now();
    if (elapsed() < options.warmup) return;
    if (!warmed_) {
        warmed_ = true;
        if (options.warmup > 0) {
            const auto first_frame = counters.first_frame_ms;
            const auto first_process_frame = counters.first_process_frame_ms;
            const auto last_frame = counters.last_frame;
            counters = {}; counters.first_frame_ms = first_frame; counters.last_frame = last_frame;
            counters.first_process_frame_ms = first_process_frame;
            measured_ = now; cpu_baseline_ = cpu_seconds(); frame_baseline_ = engine.generated_frames();
        }
    }
    if (now - sampled_ < std::chrono::milliseconds(500)) return;
    sampled_ = now;
    PROCESS_MEMORY_COUNTERS_EX memory{};
    if (GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory), sizeof memory)) {
        counters.peak_private_bytes = std::max(counters.peak_private_bytes, std::uint64_t(memory.PrivateUsage));
        counters.peak_working_set = std::max(counters.peak_working_set, std::uint64_t(memory.WorkingSetSize));
        if (memory_samples_.size() < 100'000) memory_samples_.push_back({std::chrono::duration<double>(now - measured_).count(),
            std::uint64_t(memory.PrivateUsage), std::uint64_t(memory.WorkingSetSize)});
    }
}
void Session::exercise(Driver& driver) {
    if (options.self_test) return;
    const auto now = std::chrono::steady_clock::now();
    if (!page_initialized_) {
        page_initialized_ = true;
        driver.perform(options.page == Page::monitor ? Action::monitor : options.page == Page::diagnostics ? Action::diagnostics : Action::profile);
        if (options.hold_on_exit) driver.perform(Action::reset_press);
        exercise_at_ = now; return;
    }
    if (!options.exercise) {
        if (options.page == Page::diagnostics && exercise_step_ == 0 && now - exercise_at_ > std::chrono::milliseconds(250)) {
            driver.perform(Action::expand); ++exercise_step_;
        }
        return;
    }
    if (now - exercise_at_ < std::chrono::milliseconds(250)) return;
    exercise_at_ = now;
    constexpr Action actions[]{Action::diagnostics, Action::expand, Action::mutate, Action::collapse,
        Action::monitor, Action::stop, Action::profile, Action::start};
    driver.perform(actions[exercise_step_++ % 8]);
    const auto p = driver.probe();
    if (p.page != Page::diagnostics && p.references) error = "Hidden Diagnostics retained reference images during exercise";
}
double Session::elapsed() const {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
}
bool Session::expired() const { return !error.empty() || (options.seconds > 0 && elapsed() >= options.warmup + options.seconds); }
void Session::write_report() const {
    if (options.hold_on_exit && engine.state()->resets != 0) throw std::runtime_error("Exit during hold fired Reset");
    if (options.report.empty()) return;
    if (options.report.has_parent_path()) std::filesystem::create_directories(options.report.parent_path());
    std::ofstream out(options.report);
    if (!out) throw std::runtime_error("Cannot create report");
    out << std::setprecision(12)
        << "{\n  \"candidate\": " << quoted(candidate_)
        << ",\n  \"large\": " << (options.large ? "true" : "false")
        << ",\n  \"self_test\": " << (options.self_test ? "true" : "false")
        << ",\n  \"startup_dark_requested\": " << (options.dark ? "true" : "false")
        << ",\n  \"exit_during_hold_test\": " << (options.hold_on_exit ? "true" : "false")
        << ",\n  \"reset_requests_count\": " << engine.state()->resets
        << ",\n  \"error\": " << quoted(error)
        << ",\n  \"renderer\": " << quoted(renderer)
        << ",\n  \"elapsed_seconds\": " << elapsed()
        << ",\n  \"cpu_seconds\": " << cpu_seconds() - cpu_baseline_
        << ",\n  \"measurement_seconds\": " << std::chrono::duration<double>(std::chrono::steady_clock::now() - measured_).count()
        << ",\n  \"warmup_seconds\": " << options.warmup
        << ",\n  \"requested_page\": " << int(options.page)
        << ",\n  \"exercise_steps\": " << exercise_step_
        << ",\n  \"generated_frames\": " << engine.generated_frames() - frame_baseline_
        << ",\n  \"peak_private_bytes\": " << counters.peak_private_bytes
        << ",\n  \"peak_working_set_bytes\": " << counters.peak_working_set
        << ",\n  \"first_frame_ms\": " << counters.first_frame_ms
        << ",\n  \"process_creation_to_first_intake_ms\": " << counters.first_process_frame_ms
        << ",\n  \"gui_frame_intakes\": " << counters.presented
        << ",\n  \"skipped_input_frames\": " << counters.skipped_frames
        << ",\n  \"frame_age_p50_ms\": " << percentile(counters.frame_age_ms, .50)
        << ",\n  \"frame_age_p95_ms\": " << percentile(counters.frame_age_ms, .95)
        << ",\n  \"topology_builds\": " << counters.topology_builds
        << ",\n  \"value_update_cycles\": " << counters.value_updates
        << ",\n  \"reference_requests\": " << engine.reference_requests()
        << ",\n  \"generated_state_sequence\": " << engine.state()->sequence
        << ",\n  \"checks\": [";
    for (std::size_t i = 0; i < checks.size(); ++i) out << (i ? ", " : "") << quoted(checks[i]);
    out << "],\n  \"memory_samples\": [";
    for (std::size_t i = 0; i < memory_samples_.size(); ++i) {
        const auto& sample = memory_samples_[i];
        out << (i ? "," : "") << "[" << sample.seconds << "," << sample.private_bytes << "," << sample.working_set << "]";
    }
    out << "],\n  \"not_verified\": [\"physical mouse/keyboard and IME\", \"real display present latency\", \"per-monitor DPI transition\", \"positive file selection\", \"NDI\"";
    if (candidate_ == "wx") out << ", \"native runtime theme switching requires process restart\"";
    out << "]\n}\n";
}
std::string score_text(double score) {
    std::ostringstream out;
    out << std::fixed << std::setprecision(3) << score;
    return out.str();
}
void ContractScript::require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void ContractScript::next() { ++step_; since_ = std::chrono::steady_clock::now(); }
bool ContractScript::tick(Driver& driver) {
    if (active_) return false;
    active_ = true;
    struct Guard { bool& flag; ~Guard() { flag = false; } } guard{active_};
    try {
        const auto now = std::chrono::steady_clock::now();
        if (now - started_ > std::chrono::seconds(40)) throw std::runtime_error("GUI contract timed out at step " + std::to_string(step_));
        const auto p = driver.probe();
        const auto state = session_.engine.state();
        const auto waited = std::chrono::duration<double>(now - since_).count();
        switch (step_) {
        case 0:
            if (session_.counters.presented < 2) break;
            session_.checks.push_back("M01_monitor_and_latest_preview");
            driver.perform(Action::diagnostics); driver.perform(Action::expand); next(); break;
        case 1:
            if (!p.expanded || p.references != 1) break;
            builds_ = session_.counters.topology_builds; requests_ = session_.engine.reference_requests();
            updates_ = session_.counters.value_updates;
            scroll_ = p.scroll; scroll_ready_ = !session_.options.large;
            if (session_.options.large) driver.perform(Action::scroll);
            next(); break;
        case 2:
            if (!scroll_ready_) {
                if (p.scroll > 0) { scroll_ = p.scroll; scroll_ready_ = true; since_ = now; }
                else {
                    require(waited < 2, "Large Diagnostics did not actually scroll");
                    driver.perform(Action::scroll);
                }
                break;
            }
            if (waited < .4) break;
            require(session_.counters.value_updates > updates_, "No value updates during preservation test");
            require(!session_.options.large || scroll_ > 0, "Large Diagnostics did not actually scroll");
            require(p.expanded && p.references == 1 && p.scroll == scroll_, "Value update lost expansion/scroll");
            require(session_.counters.topology_builds == builds_ && session_.engine.reference_requests() == requests_, "Value update rebuilt tree/reference");
            session_.checks.push_back("D02_value_updates_preserve_tree_expansion_scroll");
            driver.perform(Action::collapse); next(); break;
        case 3:
            if (p.references) break;
            session_.checks.push_back("D05_collapse_releases_reference");
            driver.perform(Action::monitor); builds_ = session_.counters.topology_builds; next(); break;
        case 4:
            if (waited < .4) break;
            require(p.references == 0 && session_.counters.topology_builds == builds_, "Hidden Diagnostics performed work");
            session_.checks.push_back("D04_hidden_diagnostics_stops_materialization");
            driver.perform(Action::diagnostics); driver.perform(Action::expand); next(); break;
        case 5:
            if (!p.expanded || p.references != 1) break;
            revision_ = state->topology->revision; driver.perform(Action::mutate); next(); break;
        case 6:
            if (waited < .15) break;
            if (mutation_phase_ == 0) {
                if (state->topology->revision == revision_) break;
                require(p.expanded && p.references == 1, "Topology change lost surviving detector expansion");
                driver.perform(Action::expand_dynamic); mutation_phase_ = 1; since_ = now; break;
            }
            if (mutation_phase_ == 1) {
                if (p.references != 2) break;
                revision_ = state->topology->revision; driver.perform(Action::mutate);
                mutation_phase_ = 2; since_ = now; break;
            }
            if (state->topology->revision == revision_ || p.references != 1) break;
            require(p.expanded, "Deleting another expanded detector lost surviving expansion");
            session_.checks.push_back("D03_dynamic_topology_retains_surviving_expansion");
            session_.checks.push_back("D05_deleted_expanded_detector_releases_reference");
            driver.perform(Action::profile); driver.perform(Action::invalid_draft); driver.perform(Action::apply); next(); break;
        case 7:
            if (!p.errors || !p.dirty) break;
            require(state->applied_profile->scenarios.front().name != "Edited scenario", "Invalid Apply changed backend");
            session_.checks.push_back("C02_invalid_apply_keeps_applied_profile");
            driver.perform(Action::valid_draft); driver.perform(Action::apply); next(); break;
        case 8:
            if (p.dirty || p.errors || state->applied_profile->scenarios.front().name != "Edited scenario" || state->applied_profile->scenarios.front().enabled) break;
            require(!state->topology->nodes.front().enabled && !state->metrics.front().enabled && !state->metrics.front().active, "Disabled scenario still evaluates as enabled");
            session_.checks.push_back("C01_valid_apply_reaches_worker");
            session_.checks.push_back("MC01_enabled_draft_apply_and_backend");
            if (session_.scenario_notes) {
                require(state->applied_profile->scenarios.front().note == "Maintenance note"
                    && state->topology->nodes.front().note == "Maintenance note", "Scenario note did not reach Core/topology");
                session_.checks.push_back("MC02_note_draft_apply_and_backend");
            }
            scenarios_ = p.draft_count; driver.perform(Action::add_scenario); next(); break;
        case 9:
            if (p.draft_count != scenarios_ + 1) break;
            driver.perform(Action::remove_scenario); next(); break;
        case 10:
            if (p.draft_count != scenarios_) break;
            driver.perform(Action::file_cancel);
            driver.perform(Action::unsaved_cancel); next(); break;
        case 11:
            if (p.busy || !p.file_cancels || !p.discard_cancels) break;
            require(p.dirty, "Unsaved confirmation Cancel discarded draft");
            require(session_.profile.draft.scenarios.front().enabled && !session_.profile.applied().scenarios.front().enabled,
                "Enabled-only draft/Apply state was lost during confirmation");
            session_.checks.push_back("C03_actual_file_dialog_cancel");
            session_.checks.push_back("C03_actual_unsaved_confirmation_cancel");
            driver.perform(Action::discard); driver.perform(Action::monitor);
            resets_ = state->resets; driver.perform(Action::reset_press); next(); break;
        case 12:
            if (waited < .6) break;
            driver.perform(Action::reset_cancel); next(); break;
        case 13:
            if (waited < .2) break;
            require(state->resets == resets_, "Cancelled hold fired Reset");
            driver.perform(Action::reset_press); next(); break;
        case 14:
            if (waited < 2.3) break;
            require(state->resets == resets_ + 1, "Two-second hold did not fire exactly once");
            driver.perform(Action::reset_release); driver.perform(Action::theme); driver.perform(Action::resize);
            session_.checks.push_back("R01_hold_cancel_and_single_trigger"); next(); break;
        case 15:
            if (waited < .3) break;
            require(state->resets == resets_ + 1, "Reset repeated after release");
            session_.checks.push_back("U01_theme_resize_handlers");
            return true;
        }
    } catch (const std::exception& error) { session_.error = error.what(); return true; }
    return false;
}
}
