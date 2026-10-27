#include "protocol.hpp"
#include <charconv>
#include <unordered_set>
#include <stdexcept>
namespace comparison::web {
namespace {
std::uint64_t id(const Json& value) {
    const auto text = value.get<std::string>();
    std::uint64_t result{};
    const auto parsed = std::from_chars(text.data(), text.data() + text.size(), result);
    if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() || !result)
        throw std::invalid_argument("Invalid stable ID");
    return result;
}
}
Json profile_json(const Profile& profile) {
    Json rows = Json::array();
    for (const auto& s : profile.scenarios)
        rows.push_back({{"id", std::to_string(s.id)}, {"name", s.name}, {"port", s.port}, {"enabled", s.enabled}, {"note", s.note}});
    return {{"source", int(profile.source)}, {"file", profile.file}, {"scenarios", rows}};
}
Profile parse_profile(const Json& json) {
    Profile result;
    const auto source = json.at("source").get<int>();
    if (source < 0 || source > 1) throw std::invalid_argument("Invalid source");
    result.source = Source(source); result.file = json.at("file").get<std::string>();
    if (result.file.size() > 131072) throw std::invalid_argument("File path too long");
    const auto& rows = json.at("scenarios");
    if (!rows.is_array() || rows.size() > 100) throw std::invalid_argument("Expected at most 100 draft scenarios");
    result.scenarios.clear(); std::unordered_set<std::uint64_t> ids;
    for (const auto& s : rows) {
        auto key = id(s.at("id"));
        if (!ids.insert(key).second) throw std::invalid_argument("Duplicate scenario ID");
        auto name = s.at("name").get<std::string>();
        if (name.size() > 1024) throw std::invalid_argument("Name too long");
        result.scenarios.push_back({key, name, s.at("port").get<int>(), s.at("enabled").get<bool>(), s.at("note").get<std::string>()});
    }
    return result;
}
Json topology_json(const Topology& topology) {
    Json nodes = Json::array();
    for (const auto& n : topology.nodes) nodes.push_back({{"id", std::to_string(n.id)}, {"parent", std::to_string(n.parent)},
        {"kind", int(n.kind)}, {"label", n.label}, {"enabled", n.enabled}, {"note", n.note}});
    return nodes;
}
void validate_envelope(const Json& json, unsigned epoch) {
    if (!json.is_object() || json.at("version") != 1 || !json.at("id").is_number_unsigned()
        || json.at("id").get<std::uint64_t>() > 9'007'199'254'740'991ULL
        || !json.at("command").is_string() || !json.at("args").is_object())
        throw std::invalid_argument("Invalid v1 command envelope");
    if (json.at("command") == "ready") {
        if (json.at("epoch") != 0) throw std::invalid_argument("Invalid handshake");
    } else if (json.at("epoch") != epoch) throw std::invalid_argument("Stale document epoch");
}
}
