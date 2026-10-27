#include "protocol.hpp"
#include <iostream>
using namespace comparison;
using namespace comparison::web;
int main() {
    try {
        auto require = [](bool condition) { if (!condition) throw std::runtime_error("Protocol contract failed"); };
        Profile p; p.scenarios.front().id = 9'007'199'254'740'993ULL; p.scenarios.front().name = "日本語 Scenario";
        require(parse_profile(profile_json(p)) == p);
        auto reject = [&](auto function) { bool rejected = false; try { function(); } catch (const std::exception&) { rejected = true; } require(rejected); };
        auto j = profile_json(p); j["scenarios"][1]["id"] = j["scenarios"][0]["id"]; reject([&] { parse_profile(j); });
        j = profile_json(p); j["scenarios"][0]["id"] = "-1"; reject([&] { parse_profile(j); });
        j = profile_json(p); j["source"] = 2; reject([&] { parse_profile(j); });
        Json request = {{"version", 1}, {"epoch", 4}, {"id", 1u}, {"command", "apply"}, {"args", Json::object()}};
        validate_envelope(request, 4); reject([&] { validate_envelope(request, 5); });
        request["version"] = 2; reject([&] { validate_envelope(request, 4); });
        Simulation simulation(Shape::large()); require(topology_json(*simulation.topology()).size() == 10220);
        std::cout << "WebView2 JSON boundary passed\n";
    } catch (const std::exception& e) { std::cerr << e.what(); return 1; }
}
