#include "scenario_inheritance.hpp"

#include "scenario_yaml.hpp"

namespace divergencesplitter::scenario_yaml {
namespace {

// The resolver retains key tags when expanding aliases and copying merge keys.
// Pointer identity distinguishes this marker from any tag in the YAML source.
constexpr char alias_marker[] = "!condition-extends-alias";

template <typename Visit>
void visit_children(ryml::ConstNodeRef condition, const std::string& path, Visit&& visit) {
    for (const auto key : {"condition", "reset_condition"}) {
        const auto nested = child(condition, key);
        if (!nested.invalid()) {
            visit(nested, path + "." + key);
        }
    }
    const auto conditions = child(condition, "conditions");
    if (!conditions.invalid() && conditions.is_seq()) {
        std::size_t index = 0;
        for (const auto nested : conditions.children()) {
            visit(nested, path + ".conditions[" + std::to_string(index++) + "]");
        }
    }
}

void validate_roi_override(ryml::ConstNodeRef patch, const std::string& path) {
    StringSet keys;
    for (const auto entry : patch.children()) {
        const auto key = unique_key(entry, path, keys);
        if (!roi_fields.contains(key)) {
            schema_error(path + "." + key + " is an unknown ROI field");
        }
        if (is_null(entry)) {
            schema_error(path + "." + key + " is required");
        }
    }
}

std::string condition_id(ryml::ConstNodeRef node, const std::string& path) {
    if (!node.has_val() || is_null(node) || node.val().empty()) {
        schema_error(path + ".id must be a non-empty string");
    }
    return copy_scalar(node.val());
}

bool can_remove(ryml::ConstNodeRef target, ryml::csubstr key) {
    const auto type = child(target, "type");
    if (type.invalid() || !type.has_val()) {
        return false;
    }
    if (target.has_key() && target.key() == "detector") {
        return key == "roi" || (key == "hash_size" && type.val() == "difference_hash_similarity");
    }
    return key == "within" && type.val() == "then";
}

}  // namespace

void mark_extends_alias(ryml::Tree& tree, ryml::ConstNodeRef node) {
    if (node.is_val_ref() && node.has_key() && (node.key() == "extends" || node.is_key_ref())) {
        tree.set_key_tag(node.id(), alias_marker);
    }
}

bool uses_inheritance(ryml::ConstNodeRef condition) {
    if (!child(condition, "extends").invalid() || !child(condition, "overrides").invalid()
        || !child(condition, "id").invalid()) {
        return true;
    }
    bool needed = false;
    visit_children(condition, "", [&](ryml::ConstNodeRef nested, const std::string&) {
        needed = needed || uses_inheritance(nested);
    });
    return needed;
}

ResolvedCondition::ResolvedCondition(ryml::ConstNodeRef source, const std::string& path)
    : tree_(source.tree()->callbacks()) {
    // Copies keep scalar views into the original YAML, which outlives this tree.
    tree_.rootref().set_map();
    tree_.duplicate_children(source.tree(), source.id(), tree_.root_id(), ryml::NONE);
    resolve(root(), path);
    const auto strip_ids = [&](auto&& self, ryml::ConstNodeRef condition) -> void {
        const auto id = child(condition, "id");
        if (!id.invalid()) {
            tree_.remove(id.id());
        }
        visit_children(condition, "", [&](ryml::ConstNodeRef nested, const std::string&) {
            self(self, nested);
        });
    };
    strip_ids(strip_ids, root());
}

std::string ResolvedCondition::setting_path(ryml::ConstNodeRef node, const std::string& path) const {
    if (node.invalid()) {
        return path;
    }
    const auto found = setting_paths_.find(node.id());
    return found == setting_paths_.end() ? path : found->second;
}

void ResolvedCondition::resolve(ryml::ConstNodeRef condition, const std::string& path) {
    const auto id = child(condition, "id");
    if (!id.invalid()) {
        (void)condition_id(id, path);
    }

    const auto base = child(condition, "extends");
    if (base.invalid()) {
        if (!child(condition, "overrides").invalid()) {
            schema_error(path + ".overrides requires extends");
        }
        visit_children(condition, path, [&](ryml::ConstNodeRef nested, const std::string& nested_path) {
            resolve(nested, nested_path);
        });
        return;
    }

    StringSet keys;
    for (const auto entry : condition.children()) {
        const auto key = unique_key(entry, path, keys);
        if (key != "extends" && key != "overrides" && key != "id") {
            schema_error(path + "." + key + " must be set through overrides");
        }
    }
    if (!base.has_key_tag() || base.key_tag().str != alias_marker || !base.is_map()) {
        schema_error(path + ".extends must be a YAML alias to a Condition mapping");
    }

    resolve(base, path + ".extends");
    if (child(base, "type").invalid()) {
        schema_error(path + ".extends must refer to a Condition mapping with a type");
    }
    const auto overrides = child(condition, "overrides");
    apply_overrides(base, overrides, path);

    // Move fields out of the private copy of the base, preserving descendant
    // node IDs so diagnostics still point to overrides from earlier layers.
    if (!id.invalid()) {
        const auto inherited_id = child(base, "id");
        if (!inherited_id.invalid()) {
            tree_.remove(inherited_id.id());
        }
    }
    while (base.has_children()) {
        tree_.move(base.first_child().id(), condition.id(), condition.last_child().id());
    }
    if (const auto origin = setting_paths_.extract(base.id()); !origin.empty()) {
        setting_paths_[condition.id()] = std::move(origin.mapped());
    }
    tree_.remove(base.id());
    if (!overrides.invalid()) {
        tree_.remove(overrides.id());
    }
}

void ResolvedCondition::apply_overrides(
    ryml::ConstNodeRef base, ryml::ConstNodeRef overrides, const std::string& condition_path
) {
    const auto path = condition_path + ".overrides";
    std::map<std::string, ryml::ConstNodeRef> targets;
    const auto index = [&](auto&& self, ryml::ConstNodeRef node, const std::string& node_path) -> void {
        const auto id = child(node, "id");
        if (!id.invalid()) {
            const auto name = condition_id(id, node_path);
            if (!targets.emplace(name, node).second) {
                schema_error(path + "." + name + " matches multiple Condition IDs (" + node_path + ")");
            }
        }
        visit_children(node, node_path, [&](ryml::ConstNodeRef nested, const std::string& nested_path) {
            self(self, nested, nested_path);
        });
    };
    index(index, base, condition_path + ".extends");
    if (overrides.invalid()) {
        return;
    }
    if (!overrides.is_map()) {
        schema_error(path + " must be a mapping of Condition IDs");
    }
    StringSet keys;
    for (const auto patch : overrides.children()) {
        const auto id = unique_key(patch, path, keys);
        const auto patch_path = path + "." + id;
        const auto target = targets.find(id);
        if (target == targets.end()) {
            schema_error(patch_path + " does not match a Condition ID");
        }
        if (!patch.is_map()) {
            schema_error(patch_path + " must be a mapping");
        }
        merge_settings(target->second, patch, patch_path);
        if (patch.has_children()) {
            setting_paths_[target->second.id()] = patch_path;
        }
    }
}

void ResolvedCondition::merge_settings(
    ryml::ConstNodeRef target, ryml::ConstNodeRef patch, const std::string& path
) {
    StringSet keys;
    for (const auto entry : patch.children()) {
        const auto name = unique_key(entry, path, keys);
        const auto key = entry.key();
        const auto entry_path = path + "." + name;
        if (key == "type" || key == "id" || key == "conditions" || key == "condition"
            || key == "reset_condition" || key == "extends" || key == "overrides") {
            schema_error(entry_path + " cannot be overridden");
        }
        const auto previous = target.find_child(key);
        if (key == "detector" && (!entry.is_map() || previous.invalid() || !previous.is_map())) {
            schema_error(entry_path + " must override fields of an existing Detector mapping");
        }
        if (key == "roi" && entry.is_map() && target.has_key() && target.key() == "detector") {
            validate_roi_override(entry, entry_path);
        }
        if (is_null(entry)) {
            if (!can_remove(target, key)) {
                schema_error(entry_path + " can only be set to null for an optional field");
            }
            remove_setting(previous);
        } else if (entry.is_map() && !previous.invalid() && previous.is_map()) {
            merge_settings(previous, entry, entry_path);
            setting_paths_[previous.id()] = entry_path;
        } else {
            remove_setting(previous);
            const auto replacement = tree_.duplicate(entry.id(), target.id(), tree_.last_child(target.id()));
            remember_setting(tree_.cref(replacement), entry_path);
        }
    }
}

void ResolvedCondition::remember_setting(ryml::ConstNodeRef node, const std::string& path) {
    setting_paths_[node.id()] = path;
    if (node.is_map()) {
        for (const auto child : node.children()) {
            remember_setting(child, path + "." + copy_scalar(child.key()));
        }
    }
}

void ResolvedCondition::remove_setting(ryml::ConstNodeRef node) {
    if (node.invalid()) {
        return;
    }
    while (node.has_children()) {
        remove_setting(node.first_child());
    }
    setting_paths_.erase(node.id());
    tree_.remove(node.id());
}

}  // namespace divergencesplitter::scenario_yaml
