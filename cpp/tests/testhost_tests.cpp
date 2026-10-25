#include <gtest/gtest.h>

#include <chrono>
#include <cstdlib>
#include <string>

#include "divergencesplitter/livesplit/adapter.hpp"
#include "divergencesplitter/livesplit/client.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {

std::uint16_t testhost_port() {
    const char* value = std::getenv("DIVERGENCESPLITTER_TESTHOST_PORT");
    if (value == nullptr || *value == '\0') {
        return 0;
    }
    return static_cast<std::uint16_t>(std::stoi(value));
}

bool allow_control() {
    const char* value = std::getenv("DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL");
    return value != nullptr && std::string{value} == "1";
}

}  // namespace

TEST(TestHost, QueryAndEvents) {
    const auto port = testhost_port();
    if (port == 0) {
        GTEST_SKIP() << "DIVERGENCESPLITTER_TESTHOST_PORT is not set";
    }
    LiveSplitClientOptions options;
    options.port = port;
    options.ready_timeout = 10s;
    LiveSplitBridgeClient client{options};
    client.wait_until_ready(10s);
    ASSERT_TRUE(client.is_ready());

    const auto snapshot = client.synchronize();
    EXPECT_GT(snapshot.session_id, 0U);
    EXPECT_GE(snapshot.split_count, 0);

    LiveSplitBridgeAdapter adapter{client};
    const auto update = adapter.attach();
    EXPECT_EQ(update.kind, UpdateKind::initial);
    EXPECT_EQ(update.snapshot.session_id, snapshot.session_id);

    const auto event = client.next_event(250ms);
    (void)event;
}

TEST(TestHost, ControlPauseResume) {
    const auto port = testhost_port();
    if (port == 0) {
        GTEST_SKIP() << "DIVERGENCESPLITTER_TESTHOST_PORT is not set";
    }
    if (!allow_control()) {
        GTEST_SKIP() << "set DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1 to run controls";
    }
    LiveSplitClientOptions options;
    options.port = port;
    options.ready_timeout = 10s;
    LiveSplitBridgeClient client{options};
    client.wait_until_ready(10s);
    auto before = client.synchronize();
    if (before.phase == TimerPhase::not_running) {
        const auto start = client.execute(ActionOperation::start);
        ASSERT_EQ(start.status, BridgeControlStatus::ok) << start.message;
        before = client.synchronize();
    }
    if (before.phase != TimerPhase::running && before.phase != TimerPhase::paused) {
        GTEST_SKIP() << "timer must be running or paused to verify pause/resume";
    }

    if (before.phase == TimerPhase::running) {
        const auto result = client.execute(ActionOperation::pause);
        ASSERT_EQ(result.status, BridgeControlStatus::ok) << result.message;
        EXPECT_EQ(client.synchronize().phase, TimerPhase::paused);
    }
    const auto result = client.execute(ActionOperation::resume);
    ASSERT_EQ(result.status, BridgeControlStatus::ok) << result.message;
    EXPECT_EQ(client.synchronize().phase, TimerPhase::running);

    (void)client.execute(ActionOperation::reset);
}
