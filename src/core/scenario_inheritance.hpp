#pragma once

#include <map>
#include <string>

#include <ryml/ryml.hpp>

namespace divergencesplitter::scenario_yaml {

void mark_extends_alias(ryml::Tree& tree, ryml::ConstNodeRef node);
bool uses_inheritance(ryml::ConstNodeRef condition);

class ResolvedCondition {
public:
    ResolvedCondition(ryml::ConstNodeRef source, const std::string& path);

    ryml::ConstNodeRef root() const { return tree_.crootref(); }
    std::string setting_path(ryml::ConstNodeRef node, const std::string& path) const;

private:
    void resolve(ryml::ConstNodeRef condition, const std::string& path);
    void apply_overrides(ryml::ConstNodeRef base, ryml::ConstNodeRef overrides, const std::string& condition_path);
    void merge_settings(ryml::ConstNodeRef target, ryml::ConstNodeRef patch, const std::string& path);
    void remember_setting(ryml::ConstNodeRef node, const std::string& path);
    void remove_setting(ryml::ConstNodeRef node);

    ryml::Tree tree_;
    std::map<ryml::id_type, std::string> setting_paths_;
};

}  // namespace divergencesplitter::scenario_yaml
