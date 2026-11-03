#pragma once

#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "divergencesplitter/detector/detector.hpp"
#include "divergencesplitter/frame.hpp"

namespace divergencesplitter {

enum class ConditionStatus {
    not_evaluated,
    true_value,
    false_value,
    skipped,
    error,
};

[[nodiscard]] std::string_view to_string(ConditionStatus status) noexcept;

class Condition {
public:
    virtual ~Condition() = default;

    [[nodiscard]] std::optional<bool> evaluate(FrameContext& context, bool short_circuited = false);
    void reset();

    [[nodiscard]] ConditionStatus status() const noexcept { return status_; }
    [[nodiscard]] virtual std::string_view type_name() const noexcept = 0;
    [[nodiscard]] virtual std::vector<const Condition*> children() const { return {}; }
    [[nodiscard]] virtual std::string describe() const { return std::string{type_name()}; }
    [[nodiscard]] virtual const Detector* detector() const noexcept { return nullptr; }
    [[nodiscard]] virtual std::optional<double> latest_score() const { return std::nullopt; }
    [[nodiscard]] virtual std::optional<double> max_score() const { return std::nullopt; }

    void mark_skipped() const;

protected:
    [[nodiscard]] virtual std::optional<bool> evaluate_impl(
        FrameContext& context,
        bool short_circuited
    ) = 0;
    virtual void reset_state() = 0;

private:
    mutable ConditionStatus status_{ConditionStatus::not_evaluated};
};

using ConditionPtr = std::shared_ptr<Condition>;

[[nodiscard]] bool evaluate_normal(const ConditionPtr& condition, FrameContext context);
void evaluate_short(const ConditionPtr& condition, FrameContext context);
void reset_all(const std::vector<ConditionPtr>& conditions);

}  // namespace divergencesplitter
