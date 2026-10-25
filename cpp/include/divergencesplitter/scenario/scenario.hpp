#pragma once

#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "divergencesplitter/condition/condition.hpp"
#include "divergencesplitter/rule/rule.hpp"

namespace divergencesplitter {

struct Scenario {
    ConditionPtr start_condition;
    ConditionPtr reset_condition;
    ConditionPtr incomplete_condition;
    std::vector<std::optional<std::vector<ScenarioRulePtr>>> splits;
};

enum class ScenarioErrorKind {
    unsupported_python,
    io,
    yaml,
    schema,
};

class ScenarioLoadError : public std::runtime_error {
public:
    ScenarioLoadError(ScenarioErrorKind kind, std::string message)
        : std::runtime_error(std::move(message)), kind_(kind) {}

    [[nodiscard]] ScenarioErrorKind kind() const noexcept { return kind_; }

private:
    ScenarioErrorKind kind_;
};

struct LoadedScenario {
    Scenario scenario;
    std::filesystem::path path;
};

[[nodiscard]] LoadedScenario load_scenario(const std::filesystem::path& path);

}  // namespace divergencesplitter
