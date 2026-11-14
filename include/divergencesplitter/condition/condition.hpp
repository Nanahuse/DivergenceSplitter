#pragma once

#include <memory>
#include <functional>
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
    enum class Observation { evaluated, skipped, reset, error };
    using Observer = std::function<void(const Condition&, Observation, std::optional<bool>,
                                        std::optional<MonotonicTime>, bool)>;
    // Observers belong to an instance's condition tree, never to a shared frame.
    void set_observer(Observer observer) const { observer_ = std::move(observer); }
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
    // Some composites restart internally without resetting their children.
    void record_reset_boundary(MonotonicTime time) const noexcept {
        observe(Observation::reset, {}, time);
    }
    [[nodiscard]] virtual std::optional<bool> evaluate_impl(
        FrameContext& context,
        bool short_circuited
    ) = 0;
    virtual void reset_state() = 0;

private:
    void observe(Observation event, std::optional<bool> result = {},
                 std::optional<MonotonicTime> time = {}, bool short_circuited = false) const noexcept;
    mutable Observer observer_;
    mutable ConditionStatus status_{ConditionStatus::not_evaluated};
};

using ConditionPtr = std::shared_ptr<Condition>;

[[nodiscard]] bool evaluate_normal(const ConditionPtr& condition, FrameContext context);
void evaluate_short(const ConditionPtr& condition, FrameContext context);
void reset_all(const std::vector<ConditionPtr>& conditions);

}  // namespace divergencesplitter
