#include <gtest/gtest.h>

#include <opencv2/imgcodecs.hpp>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>

#include "divergencesplitter/scenario/editor/document.hpp"
#include "divergencesplitter/scenario/editor/workspace.hpp"

using namespace divergencesplitter::scenario_editor;

namespace {

class TemporaryDirectory {
public:
    TemporaryDirectory() {
        static int counter = 0;
        path_ = std::filesystem::temp_directory_path()
            / ("divergencesplitter-workspace-" + std::to_string(++counter) + "-"
               + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directories(path_);
    }
    ~TemporaryDirectory() {
        std::error_code error;
        std::filesystem::remove_all(path_, error);
    }
    [[nodiscard]] const std::filesystem::path& path() const { return path_; }

private:
    std::filesystem::path path_;
};

std::string read_text(const std::filesystem::path& path) {
    std::ifstream stream{path, std::ios::binary};
    return {std::istreambuf_iterator<char>{stream}, std::istreambuf_iterator<char>{}};
}

void write_image(const std::filesystem::path& path) {
    cv::Mat image(8, 8, CV_8UC3);
    for (int row = 0; row < image.rows; ++row) {
        for (int column = 0; column < image.cols; ++column) {
            image.at<cv::Vec3b>(row, column) = cv::Vec3b{
                static_cast<unsigned char>(row * 20),
                static_cast<unsigned char>(column * 20),
                static_cast<unsigned char>((row + column) * 10),
            };
        }
    }
    ASSERT_TRUE(cv::imwrite(path.string(), image));
}

std::size_t file_count(const std::filesystem::path& directory) {
    std::size_t count = 0;
    for (const auto& entry : std::filesystem::directory_iterator{directory}) {
        (void)entry;
        ++count;
    }
    return count;
}

}  // namespace

TEST(ScenarioWorkspace, OpenCreatesAssetDirectory) {
    TemporaryDirectory directory;
    ScenarioWorkspace workspace;
    workspace.open(directory.path());
    EXPECT_TRUE(std::filesystem::is_directory(workspace.asset_directory()));
    EXPECT_EQ(workspace.root(), std::filesystem::weakly_canonical(directory.path()));
}

TEST(ScenarioWorkspace, ImportsImagesAndNeverOverwrites) {
    TemporaryDirectory directory;
    const auto source = directory.path() / "DPC.png";
    write_image(source);

    TemporaryDirectory workspace_directory;
    ScenarioWorkspace workspace;
    workspace.open(workspace_directory.path());
    const auto first = workspace.import_asset(source);
    const auto second = workspace.import_asset(source);
    EXPECT_EQ(first, "Asset/DPC.png");
    EXPECT_EQ(second, "Asset/DPC_2.png");
    EXPECT_TRUE(std::filesystem::is_regular_file(workspace.resolve_asset_reference(first)));
    EXPECT_TRUE(std::filesystem::is_regular_file(workspace.resolve_asset_reference(second)));
    const auto assets = workspace.list_assets();
    ASSERT_EQ(assets.size(), 2U);
    EXPECT_EQ(assets[0], "Asset/DPC.png");
    EXPECT_EQ(assets[1], "Asset/DPC_2.png");
}

TEST(ScenarioWorkspace, RejectsInvalidImagesWithoutLeavingFiles) {
    TemporaryDirectory directory;
    const auto source = directory.path() / "broken.png";
    {
        std::ofstream stream{source, std::ios::binary};
        stream << "not an image";
    }
    TemporaryDirectory workspace_directory;
    ScenarioWorkspace workspace;
    workspace.open(workspace_directory.path());
    EXPECT_THROW((void)workspace.import_asset(source), ScenarioEditorError);
    EXPECT_EQ(file_count(workspace.asset_directory()), 0U);
}

TEST(ScenarioWorkspace, PreservesUnicodeAssetNames) {
    TemporaryDirectory directory;
    const auto source = directory.path() / L"クリア.png";
    write_image(source);
    TemporaryDirectory workspace_directory;
    ScenarioWorkspace workspace;
    workspace.open(workspace_directory.path());
    const auto reference = workspace.import_asset(source);
    EXPECT_EQ(reference, "Asset/クリア.png");
    EXPECT_TRUE(std::filesystem::is_regular_file(workspace.resolve_asset_reference(reference)));
}

TEST(ScenarioWorkspace, ListsOnlyRootScenarios) {
    TemporaryDirectory directory;
    ScenarioWorkspace workspace;
    workspace.open(directory.path());
    std::ofstream{directory.path() / "a.yaml"}.put('a');
    std::ofstream{directory.path() / "b.yml"}.put('b');
    std::ofstream{directory.path() / "notes.txt"}.put('n');
    std::ofstream{directory.path() / "Asset" / "c.yaml"}.put('c');
    const auto scenarios = workspace.list_scenarios();
    ASSERT_EQ(scenarios.size(), 2U);
    EXPECT_EQ(scenarios[0], "a.yaml");
    EXPECT_EQ(scenarios[1], "b.yml");
}

TEST(ScenarioWorkspace, RejectsPathsOutsideTheWorkspace) {
    TemporaryDirectory directory;
    ScenarioWorkspace workspace;
    workspace.open(directory.path());
    EXPECT_THROW((void)workspace.scenario_path("../outside.yaml"), ScenarioEditorError);
    EXPECT_THROW((void)workspace.scenario_path("sub/inside.yaml"), ScenarioEditorError);
    EXPECT_THROW((void)workspace.scenario_path("scenario.txt"), ScenarioEditorError);
    EXPECT_THROW(
        workspace.validate_scenario_destination(directory.path().parent_path() / "outside.yaml"),
        ScenarioEditorError
    );
    EXPECT_NO_THROW((void)workspace.scenario_path("valid-name.yaml"));
}

TEST(ScenarioWorkspace, ValidatesAssetReferences) {
    TemporaryDirectory directory;
    ScenarioWorkspace workspace;
    workspace.open(directory.path());
    EXPECT_NO_THROW(ScenarioWorkspace::validate_asset_reference("Asset/image.png"));
    EXPECT_THROW(
        ScenarioWorkspace::validate_asset_reference("../Asset/image.png"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        ScenarioWorkspace::validate_asset_reference("Asset\\image.png"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        ScenarioWorkspace::validate_asset_reference("Other/image.png"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        ScenarioWorkspace::validate_asset_reference("Asset/sub/image.png"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        ScenarioWorkspace::validate_asset_reference("C:/Asset/image.png"),
        ScenarioEditorError
    );
}

TEST(ScenarioWorkspace, EditorSessionSavesOnlyInWorkspaceRoot) {
    TemporaryDirectory directory;
    ScenarioWorkspace workspace;
    workspace.open(directory.path());
    auto session = new_editor_session(workspace.root());
    const auto path = directory.path() / "test.yaml";
    save_editor_session(session, path);
    EXPECT_TRUE(std::filesystem::is_regular_file(path));
    EXPECT_THROW(
        save_editor_session(session, directory.path().parent_path() / "outside.yaml"),
        ScenarioEditorError
    );
    const auto reopened = open_editor_session(path, workspace.root());
    EXPECT_TRUE(reopened.document.start_condition.has_value());
}

TEST(ScenarioWorkspace, SavesAndReloadsAssetReferences) {
    TemporaryDirectory source_directory;
    const auto source = source_directory.path() / "YI1.png";
    write_image(source);
    TemporaryDirectory workspace_directory;
    ScenarioWorkspace workspace;
    workspace.open(workspace_directory.path());
    const auto reference = workspace.import_asset(source);

    const std::string yaml =
        "schema_version: 2\n"
        "start_condition:\n"
        "  type: detected\n"
        "  minimum_score: 0.5\n"
        "  detector:\n"
        "    type: template_match\n"
        "    reference: " + reference + "\n"
        "splits: []\n";
    auto session = new_editor_session(workspace.root());
    session.document = import_scenario_yaml(yaml);
    const auto scenario = workspace.scenario_path("my_scenario.yaml");
    save_editor_session(session, scenario);
    const auto original = read_text(scenario);

    auto reopened = open_editor_session(scenario, workspace.root());
    const auto* reference_node =
        reopened.document.start_condition->value.find("detector")->find("reference");
    ASSERT_NE(reference_node, nullptr);
    EXPECT_EQ(reference_node->scalar, reference);

    auto missing = reopened.document;
    missing.start_condition->value.find("detector")->find("reference")->scalar =
        "Asset/missing.png";
    reopened.document = std::move(missing);
    EXPECT_THROW(save_editor_session(reopened, scenario), ScenarioEditorError);
    EXPECT_EQ(read_text(scenario), original);
}
