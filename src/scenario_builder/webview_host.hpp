#pragma once

#include <filesystem>

namespace divergencesplitter::scenario_builder {

int run_scenario_builder(const std::filesystem::path& initial_document, bool smoke_test = false);

}  // namespace divergencesplitter::scenario_builder
