#include "mock.hpp"

#include <algorithm>
#include <set>
#include <stdexcept>
#include <utility>

namespace comparison {
namespace {
Image make_image(std::uint32_t width, std::uint32_t height, std::uint64_t phase) {
    Image result{width, height, std::vector<std::uint8_t>(std::size_t(width) * height * 4)};
    for (std::uint32_t y = 0; y < height; ++y) {
        for (std::uint32_t x = 0; x < width; ++x) {
            auto at = (std::size_t(y) * width + x) * 4;
            result.rgba[at] = static_cast<std::uint8_t>((x + phase) % 256);
            result.rgba[at + 1] = static_cast<std::uint8_t>((y + phase * 3) % 256);
            result.rgba[at + 2] = static_cast<std::uint8_t>((x / 16 + y / 16 + phase) % 256);
            result.rgba[at + 3] = 255;
        }
    }
    return result;
}
}

Simulation::Simulation(Shape shape) : shape_(shape) {
    if (!shape.scenarios || shape.scenarios > 64 || !shape.rules || shape.rules > 1000 ||
        !shape.conditions || shape.conditions > 1000) {
        throw std::invalid_argument("Invalid fixture dimensions");
    }
    const auto count = std::uint64_t(shape.scenarios) *
        (1 + std::uint64_t(shape.rules) * (1 + std::uint64_t(shape.conditions) * 2));
    if (count > 100'000) {
        throw std::invalid_argument("Shape requires 1..100000 nodes and nonempty levels");
    }
    auto topology = std::make_shared<Topology>();
    auto profile = std::make_shared<Profile>();
    profile->scenarios.clear();
    auto append = [&](NodeId parent, NodeKind kind, std::string label) {
        topology->nodes.push_back({next_id_++, parent, kind, std::move(label)});
    };
    for (std::uint32_t s = 0; s < shape.scenarios; ++s) {
        const auto scenario = next_id_;
        scenario_roots_[s + 1] = scenario;
        profile->scenarios.push_back({s + 1, "Scenario " + std::to_string(s + 1), 16834 + int(s)});
        append(0, NodeKind::scenario, "Scenario " + std::to_string(s + 1));
        for (std::uint32_t r = 0; r < shape.rules; ++r) {
            const auto rule = next_id_;
            append(scenario, NodeKind::rule, "Rule " + std::to_string(r + 1));
            for (std::uint32_t c = 0; c < shape.conditions; ++c) {
                const auto condition = next_id_;
                append(rule, NodeKind::condition, "Condition " + std::to_string(c + 1));
                append(condition, NodeKind::detector, "Detector " + std::to_string(c + 1));
            }
        }
    }
    topology_ = std::move(topology);
    profile_ = std::move(profile);
}
std::shared_ptr<const State> Simulation::advance(Time now) {
    auto state = std::make_shared<State>();
    state->sequence = ++sequence_;
    state->resets = resets_;
    state->produced_at = now;
    state->running = running_;
    state->topology = topology_;
    state->applied_profile = profile_;
    state->metrics.reserve(topology_->nodes.size());
    for (const auto& node : topology_->nodes) {
        auto score = double((sequence_ + node.id * 7) % 1000) / 1000.0;
        state->metrics.push_back({node.id, score, running_ && score >= 0.7,
            running_ && (sequence_ / 120 + node.id) % 7 != 0});
    }
    return state;
}
void Simulation::mutate_topology() {
    auto next = std::make_shared<Topology>(*topology_);
    ++next->revision;
    if (dynamic_condition_) {
        auto condition = dynamic_condition_;
        std::erase_if(next->nodes, [condition](const Node& node) {
            return node.id == condition || node.parent == condition;
        });
        dynamic_condition_ = 0;
    } else {
        const auto rule = std::ranges::find_if(next->nodes, [](const Node& node) {
            return node.kind == NodeKind::rule;
        })->id;
        dynamic_condition_ = next_id_++;
        next->nodes.push_back({dynamic_condition_, rule, NodeKind::condition, "Dynamic condition"});
        next->nodes.push_back({next_id_++, dynamic_condition_, NodeKind::detector, "Dynamic detector"});
    }
    topology_ = std::move(next);
}
void Simulation::apply_profile(const Profile& profile) {
    if (!validate(profile).empty()) throw std::invalid_argument("Invalid Profile");
    std::unordered_map<NodeId, NodeId> roots;
    std::unordered_map<NodeId, std::vector<Node>> groups;
    for (const auto& node : topology_->nodes) {
        const auto root = node.parent ? roots.at(node.parent) : node.id;
        roots[node.id] = root;
        groups[root].push_back(node);
    }
    auto next = std::make_shared<Topology>();
    next->revision = topology_->revision + 1;
    std::unordered_map<std::uint64_t, NodeId> next_roots;
    for (const auto& scenario : profile.scenarios) {
        if (auto found = scenario_roots_.find(scenario.id); found != scenario_roots_.end()) {
            auto nodes = groups.at(found->second);
            nodes.front().label = scenario.name;
            next->nodes.insert(next->nodes.end(), nodes.begin(), nodes.end());
            next_roots[scenario.id] = found->second;
        } else {
            const auto root = next_id_++;
            next_roots[scenario.id] = root;
            next->nodes.push_back({root, 0, NodeKind::scenario, scenario.name});
            for (std::uint32_t r = 0; r < shape_.rules; ++r) {
                const auto rule = next_id_++;
                next->nodes.push_back({rule, root, NodeKind::rule, "Rule " + std::to_string(r + 1)});
                for (std::uint32_t c = 0; c < shape_.conditions; ++c) {
                    const auto condition = next_id_++;
                    next->nodes.push_back({condition, rule, NodeKind::condition, "Condition " + std::to_string(c + 1)});
                    next->nodes.push_back({next_id_++, condition, NodeKind::detector, "Detector " + std::to_string(c + 1)});
                }
            }
        }
    }
    if (std::ranges::none_of(next->nodes, [this](const Node& n) { return n.id == dynamic_condition_; })) {
        dynamic_condition_ = 0;
    }
    topology_ = std::move(next);
    scenario_roots_ = std::move(next_roots);
    profile_ = std::make_shared<Profile>(profile);
}

MockEngine::MockEngine(EngineOptions options) : options_(options), simulation_(options.shape) {
    if (!options.frame_width || !options.frame_height ||
        options.frame_width > 3840 || options.frame_height > 2160) {
        throw std::invalid_argument("Frame dimensions must be within 3840x2160");
    }
    state_.publish(simulation_.advance(std::chrono::steady_clock::now()));
}
MockEngine::~MockEngine() { stop(); }
void MockEngine::start() {
    if (worker_.joinable()) return;
    worker_ = std::jthread([this](std::stop_token stop) { run(stop); });
}
void MockEngine::stop() {
    if (!worker_.joinable()) return;
    worker_.request_stop();
    worker_.join();
    frame_.publish(nullptr);
}
void MockEngine::set_running(bool running) {
    std::lock_guard lock(control_mutex_);
    pending_running_ = running;
}
void MockEngine::reset_all() {
    std::lock_guard lock(control_mutex_);
    ++pending_resets_;
}
bool MockEngine::mutate_topology() {
    std::lock_guard lock(control_mutex_);
    if (pending_mutations_ >= 32) return false;
    ++pending_mutations_;
    return true;
}
std::vector<std::string> MockEngine::apply_profile(const Profile& profile) {
    auto errors = validate(profile);
    if (errors.empty()) {
        auto next = std::make_shared<Profile>(profile);
        std::lock_guard lock(control_mutex_);
        pending_profile_ = std::move(next);
    }
    return errors;
}
void MockEngine::run(std::stop_token stop) {
    const auto period = std::chrono::nanoseconds(1'000'000'000 / 60);
    auto deadline = std::chrono::steady_clock::now();
    while (!stop.stop_requested()) {
        std::optional<bool> running;
        std::uint64_t resets;
        std::uint64_t mutations;
        std::shared_ptr<const Profile> profile;
        {
            std::lock_guard lock(control_mutex_);
            running = std::exchange(pending_running_, std::nullopt);
            resets = std::exchange(pending_resets_, 0);
            mutations = std::exchange(pending_mutations_, 0);
            profile = std::exchange(pending_profile_, nullptr);
        }
        if (profile) simulation_.apply_profile(*profile);
        if (running) simulation_.set_running(*running);
        simulation_.reset_all(resets);
        for (std::uint64_t i = 0; i < mutations; ++i) simulation_.mutate_topology();
        const auto captured = std::chrono::steady_clock::now();
        auto state = simulation_.advance(captured);
        if (state->running) {
            const auto sequence = ++generated_frames_;
            auto frame = std::make_shared<Frame>(Frame{sequence, captured,
                make_image(options_.frame_width, options_.frame_height, state->sequence)});
            frame_.publish(std::move(frame));
        } else {
            frame_.publish(nullptr);
        }
        state_.publish(std::move(state));
        deadline += period;
        // Skip missed periods instead of producing a catch-up burst.
        const auto now = std::chrono::steady_clock::now();
        if (deadline < now) deadline = now + period;
        std::this_thread::sleep_until(deadline);
    }
}
Image MockEngine::reference(NodeId detector) {
    auto current = state();
    const auto found = std::ranges::find_if(current->topology->nodes, [detector](const Node& n) {
        return n.id == detector && n.kind == NodeKind::detector;
    });
    if (found == current->topology->nodes.end()) throw std::invalid_argument("Unknown detector");
    ++reference_requests_;
    return make_image(160, 90, detector);
}

std::vector<std::string> validate(const Profile& profile) {
    std::vector<std::string> errors;
    if (profile.source == Source::synthetic_file && profile.file.empty()) {
        errors.push_back("Select a source file");
    }
    if (profile.scenarios.empty() || profile.scenarios.size() > 64) {
        errors.push_back("A profile requires 1..64 scenarios");
    }
    std::set<std::string> names;
    std::set<std::uint64_t> ids;
    for (const auto& scenario : profile.scenarios) {
        if (scenario.name.find_first_not_of(" \t\r\n") == std::string::npos) {
            errors.push_back("Scenario name is empty");
        }
        if (!names.insert(scenario.name).second) errors.push_back("Scenario names must be unique");
        if (!scenario.id || !ids.insert(scenario.id).second) errors.push_back("Scenario IDs must be unique");
        if (scenario.port < 1 || scenario.port > 65535) errors.push_back("Port must be 1..65535");
    }
    return errors;
}
ProfileEditor::ProfileEditor(Profile initial) : draft(initial), applied_(std::move(initial)) {
    for (const auto& scenario : draft.scenarios) next_id_ = std::max(next_id_, scenario.id + 1);
}
std::vector<std::string> ProfileEditor::apply() {
    auto errors = validate(draft);
    if (errors.empty()) applied_ = draft;
    return errors;
}
void ProfileEditor::add_scenario() {
    // The public draft can be populated by a file dialog; do not reuse its IDs.
    for (const auto& scenario : draft.scenarios) next_id_ = std::max(next_id_, scenario.id + 1);
    const auto id = next_id_++;
    draft.scenarios.push_back({id, "Scenario " + std::to_string(id), 16834});
}
void ProfileEditor::remove_scenario(std::uint64_t id) {
    std::erase_if(draft.scenarios, [id](const ScenarioSettings& s) { return s.id == id; });
}
void ResetHold::press(Time now) {
    if (pressed_at_) return;
    pressed_at_ = now;
    fired_ = false;
}
void ResetHold::cancel() { pressed_at_.reset(); fired_ = false; }
bool ResetHold::poll(Time now) {
    if (!pressed_at_ || fired_ || now - *pressed_at_ < std::chrono::seconds(2)) return false;
    fired_ = true;
    return true;
}
double ResetHold::progress(Time now) const {
    if (!pressed_at_) return 0;
    return std::clamp(std::chrono::duration<double>(now - *pressed_at_).count() / 2.0, 0.0, 1.0);
}
bool PreviewCadence::due(Time now) {
    if (last_ && now - *last_ < std::chrono::nanoseconds(66'666'666)) return false;
    last_ = now;
    return true;
}
} // namespace comparison
