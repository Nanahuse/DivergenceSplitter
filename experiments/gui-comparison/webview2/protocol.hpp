#pragma once
#include "mock.hpp"
#include <nlohmann/json.hpp>
namespace comparison::web {
using Json = nlohmann::json;
Json profile_json(const Profile& profile);
Profile parse_profile(const Json& json);
Json topology_json(const Topology& topology);
// Strict envelope validation precedes every native action. IDs cross JS as strings.
void validate_envelope(const Json& json, unsigned epoch);
}
