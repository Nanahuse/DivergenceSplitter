#pragma once

#include <chrono>
#include <compare>
#include <cstdint>

namespace divergencesplitter {

struct MonotonicTime {
    std::int64_t nanoseconds{};

    friend constexpr auto operator<=>(const MonotonicTime&, const MonotonicTime&) = default;
    friend constexpr MonotonicTime operator+(MonotonicTime lhs, std::chrono::nanoseconds rhs) {
        return {lhs.nanoseconds + rhs.count()};
    }
    friend constexpr MonotonicTime operator-(MonotonicTime lhs, std::chrono::nanoseconds rhs) {
        return {lhs.nanoseconds - rhs.count()};
    }
    friend constexpr std::chrono::nanoseconds operator-(MonotonicTime lhs, MonotonicTime rhs) {
        return std::chrono::nanoseconds{lhs.nanoseconds - rhs.nanoseconds};
    }
};

class TimeProvider {
public:
    virtual ~TimeProvider() = default;
    [[nodiscard]] virtual MonotonicTime now() const = 0;
};

class SteadyTimeProvider final : public TimeProvider {
public:
    [[nodiscard]] MonotonicTime now() const override {
        const auto value = std::chrono::steady_clock::now().time_since_epoch();
        return MonotonicTime{std::chrono::duration_cast<std::chrono::nanoseconds>(value).count()};
    }
};

[[nodiscard]] inline MonotonicTime monotonic_now() {
    static const SteadyTimeProvider provider;
    return provider.now();
}

}  // namespace divergencesplitter
