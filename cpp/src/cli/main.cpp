#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <thread>

#include "divergencesplitter/configuration/configuration.hpp"
#include "divergencesplitter/runtime/session.hpp"

namespace {

std::atomic_bool g_interrupted{false};

void handle_signal(int) {
    g_interrupted.store(true);
}

void print_usage() {
    std::cerr
        << "usage: divergencesplitter --profile <profile.json> [--settings <settings.json>]\n"
        << "                         [--seconds <n>] [--check]\n";
}

std::string describe_state(divergencesplitter::InstanceState state) {
    using divergencesplitter::InstanceState;
    switch (state) {
        case InstanceState::connecting:
            return "connecting";
        case InstanceState::ready:
            return "ready";
        case InstanceState::failed:
            return "failed";
        case InstanceState::stopped:
            return "stopped";
    }
    return "unknown";
}

}  // namespace

int main(int argc, char** argv) {
    std::filesystem::path profile_path;
    std::filesystem::path settings_path;
    int seconds = 0;
    bool check_only = false;

    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        const auto require_value = [&](const char* name) -> std::string {
            if (index + 1 >= argc) {
                std::cerr << name << " requires a value\n";
                std::exit(2);
            }
            return argv[++index];
        };
        if (argument == "--profile") {
            profile_path = require_value("--profile");
        } else if (argument == "--settings") {
            settings_path = require_value("--settings");
        } else if (argument == "--seconds") {
            seconds = std::stoi(require_value("--seconds"));
        } else if (argument == "--check") {
            check_only = true;
        } else if (argument == "--help" || argument == "-h") {
            print_usage();
            return 0;
        } else {
            std::cerr << "unknown argument: " << argument << '\n';
            print_usage();
            return 2;
        }
    }

    if (profile_path.empty()) {
        print_usage();
        return 2;
    }

    try {
        using namespace divergencesplitter;
        AppSettings settings;
        if (!settings_path.empty() && std::filesystem::exists(settings_path)) {
            settings = load_app_settings(settings_path);
        }
        auto loaded = load_profile(profile_path);
        if (loaded.migrated) {
            std::cout << "migrated profile from version 1 to version 2\n";
        }
        if (check_only) {
            for (const auto& instance : loaded.profile.instances) {
                (void)load_profile_scenario(
                    std::filesystem::path{instance.scenario}, loaded.profile.source
                );
            }
            std::cout << "profile and scenarios are valid\n";
            return 0;
        }

        std::signal(SIGINT, handle_signal);
        Session session;
        session.apply_profile(loaded.profile, settings);
        const auto started = std::chrono::steady_clock::now();

        while (!g_interrupted.load()) {
            const auto instances = session.instance_diagnostics();
            const auto capture = session.capture_stats();
            std::cout << "frames=" << capture.frames_published
                      << " fps=" << capture.measured_fps;
            for (const auto& instance : instances) {
                std::cout << " scenario[" << instance.index << "]="
                          << describe_state(instance.state);
                if (!instance.error.empty()) {
                    std::cout << " (" << instance.error << ')';
                }
            }
            std::cout << '\n';
            const auto error = session.last_error();
            if (!error.empty()) {
                std::cerr << "runtime error: " << error << '\n';
                session.stop();
                return 4;
            }
            if (seconds > 0) {
                const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                    std::chrono::steady_clock::now() - started
                );
                if (elapsed.count() >= seconds) {
                    break;
                }
            }
            std::this_thread::sleep_for(std::chrono::seconds{1});
        }
        session.stop();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 3;
    }
}
