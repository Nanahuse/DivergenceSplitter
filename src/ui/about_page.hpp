#pragma once

#include <optional>
#include <string>
#include <vector>

#include "license_inventory.hpp"

namespace divergencesplitter::ui {

class AboutPage {
public:
    AboutPage();

    void draw();

private:
    std::optional<LicenseInventory> inventory_;
    std::vector<std::string> transitive_;
};

}  // namespace divergencesplitter::ui
