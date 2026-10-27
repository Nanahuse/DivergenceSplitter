#include "mock.hpp"

#include <algorithm>
#include <chrono>
#include <iostream>
#include <set>
#include <stdexcept>

using namespace comparison;
using namespace std::chrono_literals;
namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
template<class F> void eventually(F predicate) {
    const auto end = std::chrono::steady_clock::now() + 2s;
    while (!predicate()) {
        if (std::chrono::steady_clock::now() > end) throw std::runtime_error("Worker deadline exceeded");
        std::this_thread::sleep_for(1ms);
    }
}
void topology_contract(Shape shape, std::size_t count) {
    Simulation simulation(shape);
    auto first = simulation.advance(Time{});
    require(first->topology->nodes.size() == count, "Unexpected fixture node count");
    std::set<NodeId> ids{0};
    for (const auto& node : first->topology->nodes) {
        require(ids.contains(node.parent), "Parent must precede child");
        require(ids.insert(node.id).second, "Duplicate node ID");
    }
    auto second = simulation.advance(Time{} + 1s);
    require(first->topology == second->topology, "Value update rebuilt topology");
    require(first->metrics.front().score != second->metrics.front().score, "Score did not update");
    simulation.mutate_topology();
    auto added = simulation.advance(Time{} + 2s);
    require(added->topology->nodes.size() == count + 2, "Dynamic add failed");
    require(first->topology->nodes.size() == count, "Old snapshot was mutated");
    const auto dynamic = added->topology->nodes.back().id;
    for (std::size_t i = 0; i < count; ++i) {
        require(first->topology->nodes[i].id == added->topology->nodes[i].id, "Surviving ID changed");
    }
    simulation.mutate_topology();
    require(simulation.topology()->nodes.size() == count, "Dynamic remove failed");
    simulation.mutate_topology();
    require(simulation.topology()->nodes.back().id > dynamic, "Removed ID reused");
}
void profile_contract() {
    ProfileEditor editor;
    require(!editor.dirty(), "Initial profile is dirty");
    editor.draft.scenarios[0].name = "Edited";
    require(editor.dirty(), "Draft edit not tracked");
    require(editor.applied().scenarios[0].name == "Scenario 1", "Draft changed applied state");
    editor.draft.scenarios[0].port = 65536;
    require(!editor.apply().empty(), "Invalid profile was accepted");
    require(editor.applied().scenarios[0].name == "Scenario 1", "Failed Apply changed applied state");
    editor.draft.scenarios[0].port = 16834;
    require(editor.apply().empty() && !editor.dirty(), "Valid Apply failed");
    editor.add_scenario();
    auto id = editor.draft.scenarios.back().id;
    editor.remove_scenario(id);
    editor.add_scenario();
    require(editor.draft.scenarios.back().id > id, "Profile reused removed ID");
    editor.discard();
    require(!editor.dirty(), "Discard failed");
    editor.draft.source = Source::synthetic_file;
    require(!editor.apply().empty(), "File source accepted without a path");
    editor.draft.file = "chosen-by-dialog.avi";
    require(editor.apply().empty(), "File source Apply failed");
    editor.draft.scenarios[1].name = editor.draft.scenarios[0].name;
    require(!editor.apply().empty(), "Duplicate names accepted");
}
void note_change_contract() {
    ProfileEditor editor;
    editor.draft.scenarios.front().note = "Maintenance note";
    require(editor.dirty() && editor.applied().scenarios.front().note.empty(), "Note draft escaped into applied state");
    require(editor.apply().empty(), "Note Apply failed");
    Simulation simulation;
    const auto id = simulation.topology()->nodes.front().id;
    simulation.apply_profile(editor.applied());
    const auto state = simulation.advance(Time{});
    require(state->topology->nodes.front().id == id && state->topology->nodes.front().note == "Maintenance note", "Note lost stable ID or topology value");
    editor.draft.scenarios.front().note = std::string(121, 'x');
    require(!editor.apply().empty() && editor.applied().scenarios.front().note == "Maintenance note", "Oversized note changed applied state");
    editor.discard(); require(!editor.dirty(), "Note discard failed");
}
void enabled_change_contract() {
    Simulation simulation;
    const auto before = simulation.advance(Time{});
    ProfileEditor editor(*before->applied_profile);
    editor.draft.scenarios.front().enabled = false;
    require(editor.dirty() && editor.applied().scenarios.front().enabled, "Enabled edit leaked into applied settings");
    editor.draft.scenarios.front().name = "";
    require(!editor.apply().empty() && editor.applied().scenarios.front().enabled, "Invalid Apply committed enabled");
    editor.draft.scenarios.front().name = "Disabled scenario";
    require(editor.apply().empty(), "Enabled Apply failed");
    simulation.apply_profile(editor.applied());
    const auto after = simulation.advance(Time{} + 1s);
    require(before->applied_profile->scenarios.front().enabled, "Previous snapshot changed after Apply");
    require(!after->applied_profile->scenarios.front().enabled, "Worker settings lost enabled");
    for (std::size_t i = 0; i < 28; ++i) {
        require(after->topology->nodes[i].id == before->topology->nodes[i].id, "Enabled change replaced stable IDs");
        require(!after->metrics[i].enabled && !after->metrics[i].active && !after->metrics[i].connected, "Disabled descendants remained active");
    }
    require(after->metrics[28].enabled, "Enabled change affected another scenario");
    simulation.mutate_topology();
    const auto dynamic = simulation.advance(Time{} + 1500ms);
    require(!dynamic->metrics.back().enabled, "Dynamic nodes under disabled scenario became enabled");
    editor.draft.scenarios.front().enabled = true;
    require(editor.dirty(), "Enabled-only edit was not dirty");
    editor.discard();
    require(!editor.dirty() && !editor.draft.scenarios.front().enabled, "Discard did not restore enabled");
    editor.remove_scenario(1); editor.add_scenario();
    simulation.apply_profile(editor.draft);
    const auto removed = simulation.advance(Time{} + 2s);
    require(removed->topology->nodes.front().id == before->topology->nodes[28].id, "Removing scenario changed surviving IDs");
    require(removed->applied_profile->scenarios.back().enabled, "New scenario must default to enabled");
}
void hold_contract() {
    ResetHold hold;
    const Time now{};
    hold.press(now);
    hold.press(now + 1s); // Repeated press must not restart the deadline.
    require(!hold.poll(now + 1999ms), "Reset fired early");
    require(hold.poll(now + 2s), "Reset did not fire at 2 seconds");
    require(!hold.poll(now + 3s), "Reset fired twice");
    hold.cancel();
    require(hold.progress(now + 4s) == 0, "Cancel retained progress");
    hold.press(now + 4s);
    hold.cancel(); // All frontend cancel reasons map here.
    require(!hold.poll(now + 10s), "Cancelled hold fired");
}
void latest_contract() {
    Latest<State> slot;
    auto retained = std::make_shared<State>();
    retained->sequence = 1;
    slot.publish(retained);
    for (std::uint64_t sequence = 2; sequence <= 1000; ++sequence) {
        auto state = std::make_shared<State>();
        state->sequence = sequence;
        slot.publish(state);
    }
    require(slot.read()->sequence == 1000, "Latest slot replayed old updates");
    require(retained->sequence == 1, "Retained snapshot changed");
    PreviewCadence preview;
    require(preview.due(Time{}), "First preview suppressed");
    require(!preview.due(Time{} + 16ms), "Preview exceeded intake cap");
    require(preview.due(Time{} + 67ms), "15Hz preview suppressed");
    require(preview.due(Time{} + 2s), "Delayed preview suppressed");
    require(!preview.due(Time{} + 2s), "Preview emitted a catch-up burst");
    PreviewCadence steady;
    int displayed = 0;
    for (int frame = 0; frame < 60; ++frame) {
        if (steady.due(Time{} + std::chrono::nanoseconds(frame * 1'000'000'000LL / 60))) ++displayed;
    }
    require(displayed == 15, "60Hz input did not produce 15 preview opportunities");
    PreviewCadence jittered;
    displayed = 0;
    for (int tick = 0; tick < 60; ++tick) {
        if (jittered.due(Time{} + std::chrono::nanoseconds(tick * 16'900'000LL))) ++displayed;
    }
    require(displayed == 15, "Event-loop jitter accumulated preview cadence drift");
}
void worker_contract() {
    MockEngine engine({{}, 64, 36});
    const auto detector = std::ranges::find_if(engine.state()->topology->nodes,
        [](const Node& node) { return node.kind == NodeKind::detector; })->id;
    require(engine.reference_requests() == 0, "Eager reference generation");
    auto reference = engine.reference(detector);
    require(reference.rgba.size() == 160 * 90 * 4, "Reference dimensions incorrect");
    require(engine.reference_requests() == 1, "Reference request not counted");
    bool rejected = false;
    try { (void)engine.reference(0); } catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "Unknown detector accepted");
    for (int mutation = 0; mutation < 32; ++mutation) {
        require(engine.mutate_topology(), "Mutation intake rejected too early");
    }
    require(!engine.mutate_topology(), "Mutation intake is unbounded");
    for (int repeat = 0; repeat < 3; ++repeat) {
        engine.start();
        engine.start();
        eventually([&] { return engine.frame() != nullptr && engine.state()->topology->revision == 32; });
        require(engine.state()->topology->revision == 32, "Accepted topology commands were lost");
        const auto retained = engine.frame();
        const auto bytes = retained->image.rgba;
        engine.reset_all();
        eventually([&] { return engine.state()->resets == std::uint64_t(repeat + 1); });
        require(retained->image.rgba == bytes, "Producer mutated retained pixels");
        engine.set_running(false);
        eventually([&] { return !engine.state()->running; });
        require(!engine.frame(), "Stopped session retained a latest frame");
        engine.set_running(true);
        eventually([&] { return engine.frame() != nullptr; });
        engine.stop();
        const auto sequence = engine.state()->sequence;
        std::this_thread::sleep_for(25ms);
        require(engine.state()->sequence == sequence, "Worker ran after stop/join");
        require(!engine.frame(), "Stop retained latest frame");
        engine.stop();
    }
}
void reference_snapshot_contract() {
    MockEngine engine({{}, 64, 36});
    const auto snapshot = engine.state()->topology;
    const auto detector = std::ranges::find_if(snapshot->nodes, [](const Node& node) { return node.kind == NodeKind::detector; })->id;
    ProfileEditor editor(*engine.state()->applied_profile);
    editor.remove_scenario(editor.draft.scenarios.front().id);
    require(engine.apply_profile(editor.draft).empty(), "Scenario removal was rejected");
    engine.start();
    eventually([&] { return engine.state()->applied_profile->scenarios.size() == 2; });
    require(engine.reference(detector, snapshot).rgba.size() == 160 * 90 * 4, "Retained UI snapshot could not generate a reference after worker removal");
    bool rejected = false;
    try { (void)engine.reference(detector); } catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "Removed detector accepted without a retained snapshot");
    engine.stop();
    for (int repeat = 0; repeat < 20; ++repeat) {
        const auto sequence = engine.state()->sequence;
        engine.start();
        eventually([&] { return engine.state()->sequence > sequence; });
        engine.stop();
        require(!engine.frame(), "Worker lifecycle retained a latest frame after join");
    }
}
}
int main() {
    try {
        topology_contract({}, 84);
        topology_contract(Shape::large(), 10'220);
        bool invalid_shape = false;
        try { Simulation invalid({0xffffffffU, 0xffffffffU, 0xffffffffU}); }
        catch (const std::invalid_argument&) { invalid_shape = true; }
        require(invalid_shape, "Invalid fixture dimensions accepted");
        profile_contract();
        enabled_change_contract();
        note_change_contract();
        hold_contract();
        latest_contract();
        worker_contract();
        reference_snapshot_contract();
        std::cout << "PASS: fixtures, stable IDs, immutable values/pixels, latest-only, profile, hold, worker lifecycle\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
