#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace comparison {
using NodeId = std::uint64_t;
using Time = std::chrono::steady_clock::time_point;

enum class NodeKind { scenario, rule, condition, detector };
struct Node {
    NodeId id;
    NodeId parent; // 0 denotes a root.
    NodeKind kind;
    std::string label;
    bool enabled = true;
    std::string note;
};
struct Topology {
    std::uint64_t revision = 0;
    std::vector<Node> nodes;
};
struct Shape {
    std::uint32_t scenarios = 3;
    std::uint32_t rules = 3;
    std::uint32_t conditions = 4;
    static Shape large() { return {20, 10, 25}; }
};
struct Metric {
    NodeId id;
    double score;
    bool active;
    bool connected;
    bool enabled = true;
};
struct Profile;
struct State {
    std::uint64_t sequence = 0;
    std::uint64_t resets = 0;
    Time produced_at;
    bool running = true;
    std::shared_ptr<const Topology> topology;
    std::shared_ptr<const Profile> applied_profile;
    std::vector<Metric> metrics;
};
struct Image {
    std::uint32_t width;
    std::uint32_t height;
    std::vector<std::uint8_t> rgba;
};
struct Frame {
    std::uint64_t sequence;
    Time captured_at;
    Image image;
};

// No event queue, toolkit objects, borrowed mutable pixel buffers or callbacks.
// Readers retain immutable ownership; publish replaces the single latest slot.
template<class T> class Latest {
public:
    void publish(std::shared_ptr<const T> value) {
        value_.store(std::move(value), std::memory_order_release);
    }
    [[nodiscard]] std::shared_ptr<const T> read() const {
        return value_.load(std::memory_order_acquire);
    }
private:
    std::atomic<std::shared_ptr<const T>> value_;
};

// Pure simulation with an injected timestamp; no sleep or GUI is needed to test it.
class Simulation {
public:
    explicit Simulation(Shape shape = {});
    std::shared_ptr<const State> advance(Time now);
    void set_running(bool running) { running_ = running; }
    void reset_all(std::uint64_t count = 1) { resets_ += count; }
    void mutate_topology(); // Add/remove a Condition+Detector under the first Rule.
    void apply_profile(const Profile& profile);
    [[nodiscard]] std::shared_ptr<const Topology> topology() const { return topology_; }
private:
    std::shared_ptr<const Topology> topology_;
    std::uint64_t sequence_ = 0;
    std::uint64_t resets_ = 0;
    NodeId next_id_ = 1;
    NodeId dynamic_condition_ = 0;
    bool running_ = true;
    Shape shape_;
    std::shared_ptr<const Profile> profile_;
    std::unordered_map<std::uint64_t, NodeId> scenario_roots_;
};

struct EngineOptions {
    Shape shape;
    std::uint32_t frame_width = 1280;
    std::uint32_t frame_height = 720;
};

class MockEngine {
public:
    explicit MockEngine(EngineOptions options = {});
    ~MockEngine();
    MockEngine(const MockEngine&) = delete;
    MockEngine& operator=(const MockEngine&) = delete;
    // start/stop belong to the UI owner thread; stop joins before returning.
    void start();
    void stop();
    void set_running(bool running);
    void reset_all();
    [[nodiscard]] bool mutate_topology(); // Bounded command intake; false means busy.
    [[nodiscard]] std::vector<std::string> apply_profile(const Profile& profile);
    [[nodiscard]] std::shared_ptr<const State> state() const { return state_.read(); }
    [[nodiscard]] std::shared_ptr<const Frame> frame() const { return frame_.read(); }
    // Invoked by an adapter only when its reference section becomes visible.
    [[nodiscard]] Image reference(NodeId detector, std::shared_ptr<const Topology> snapshot = {});
    [[nodiscard]] std::uint64_t reference_requests() const { return reference_requests_.load(); }
    [[nodiscard]] std::uint64_t generated_frames() const { return generated_frames_.load(); }
private:
    void run(std::stop_token stop);
    EngineOptions options_;
    Simulation simulation_;
    Latest<State> state_;
    Latest<Frame> frame_;
    std::mutex control_mutex_;
    std::optional<bool> pending_running_;
    std::uint64_t pending_resets_ = 0;
    std::uint64_t pending_mutations_ = 0;
    std::shared_ptr<const Profile> pending_profile_;
    std::atomic<std::uint64_t> reference_requests_ = 0;
    std::atomic<std::uint64_t> generated_frames_ = 0;
    std::jthread worker_; // Declared last, so all resources outlive its destructor.
};

enum class Source { synthetic_camera, synthetic_file };
struct ScenarioSettings {
    std::uint64_t id;
    std::string name;
    int port;
    bool enabled = true;
    std::string note;
    bool operator==(const ScenarioSettings&) const = default;
};
struct Profile {
    Source source = Source::synthetic_camera;
    std::string file;
    std::vector<ScenarioSettings> scenarios = {
        {1, "Scenario 1", 16834}, {2, "Scenario 2", 16835}, {3, "Scenario 3", 16836}};
    bool operator==(const Profile&) const = default;
};
std::vector<std::string> validate(const Profile& profile);
class ProfileEditor {
public:
    explicit ProfileEditor(Profile initial = {});
    Profile draft;
    [[nodiscard]] const Profile& applied() const { return applied_; }
    [[nodiscard]] bool dirty() const { return draft != applied_; }
    [[nodiscard]] std::vector<std::string> apply();
    void discard() { draft = applied_; }
    void add_scenario();
    void remove_scenario(std::uint64_t id);
private:
    Profile applied_;
    std::uint64_t next_id_ = 4;
};

// The frontend maps pointer up/cancel, focus loss, navigation and disposal to cancel.
class ResetHold {
public:
    void press(Time now);
    void cancel();
    [[nodiscard]] bool poll(Time now); // true exactly once per completed press.
    [[nodiscard]] double progress(Time now) const;
private:
    std::optional<Time> pressed_at_;
    bool fired_ = false;
};

// Each frontend owns its timer/event loop. This only enforces a common intake cap.
class PreviewCadence {
public:
    bool due(Time now);
private:
    std::optional<Time> next_;
};
} // namespace comparison
