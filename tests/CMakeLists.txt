include(GoogleTest)

add_executable(divergencesplitter_tests
    camera_tests.cpp
    condition_tests.cpp
    detector_tests.cpp
    frame_cache_tests.cpp
    instance_runtime_tests.cpp
    logging_tests.cpp
    normalizer_tests.cpp
    ndi_tests.cpp
    profile_tests.cpp
    recorded_pipeline_tests.cpp
    scenario_loader_tests.cpp
    scenario_runtime_tests.cpp
    test_support.cpp
)
target_compile_features(divergencesplitter_tests PRIVATE cxx_std_23)
target_link_libraries(divergencesplitter_tests
    PRIVATE
        divergencesplitter::runtime
        GTest::gtest_main
)
target_include_directories(divergencesplitter_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
gtest_discover_tests(divergencesplitter_tests)
# Each iteration starts a fresh process so decoder startup is covered too.
add_test(NAME recorded_pipeline_repeat COMMAND "${CMAKE_COMMAND}"
    "-DTEST_EXECUTABLE=$<TARGET_FILE:divergencesplitter_tests>"
    -P "${CMAKE_CURRENT_LIST_DIR}/repeat_recorded_pipeline.cmake")
set_tests_properties(recorded_pipeline_repeat PROPERTIES
    TIMEOUT 180 LABELS "recording;regression")
if(DIVERGENCESPLITTER_ENABLE_NDI)
    add_test(NAME ndi_sdk_initialization COMMAND divergencesplitter_cli --ndi-check)
    add_executable(divergencesplitter_ndi_loopback_tests ndi_loopback_tests.cpp)
    target_include_directories(divergencesplitter_ndi_loopback_tests SYSTEM PRIVATE "${NDI_SDK_DIR}/Include")
    target_compile_definitions(divergencesplitter_ndi_loopback_tests PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(divergencesplitter_ndi_loopback_tests PRIVATE divergencesplitter::runtime GTest::gtest_main)
    add_test(NAME ndi_sdk_loopback COMMAND divergencesplitter_ndi_loopback_tests)
    set_tests_properties(ndi_sdk_loopback PROPERTIES TIMEOUT 90 LABELS "ndi;integration")
endif()

if(DIVERGENCESPLITTER_BUILD_TESTHOST_TESTS)
    add_executable(divergencesplitter_testhost_tests testhost_tests.cpp)
    target_compile_features(divergencesplitter_testhost_tests PRIVATE cxx_std_23)
    target_link_libraries(divergencesplitter_testhost_tests
        PRIVATE
            divergencesplitter::runtime
            GTest::gtest_main
    )
    add_test(NAME divergencesplitter_testhost_tests COMMAND divergencesplitter_testhost_tests)
endif()

if(DIVERGENCESPLITTER_BUILD_UI)
    add_executable(divergencesplitter_ui_tests ui_model_tests.cpp)
    target_compile_features(divergencesplitter_ui_tests PRIVATE cxx_std_23)
    target_link_libraries(divergencesplitter_ui_tests
        PRIVATE
            divergencesplitter::ui
            GTest::gtest_main
    )
    target_include_directories(divergencesplitter_ui_tests PRIVATE "${PROJECT_SOURCE_DIR}/src/ui")
    gtest_discover_tests(divergencesplitter_ui_tests)
endif()
