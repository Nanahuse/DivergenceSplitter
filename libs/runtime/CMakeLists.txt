add_library(divergencesplitter_runtime STATIC
    src/evaluation_history.cpp
    src/scenario_runtime.cpp
    src/instance_runtime.cpp
    src/livesplit_adapter.cpp
    src/livesplit_client.cpp
    src/session.cpp
    src/configuration.cpp
    src/logging.cpp
)

add_library(divergencesplitter::runtime ALIAS divergencesplitter_runtime)

target_compile_features(divergencesplitter_runtime PUBLIC cxx_std_23)
target_include_directories(divergencesplitter_runtime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
target_link_libraries(divergencesplitter_runtime
    PUBLIC
        divergencesplitter::capture
    PRIVATE
        livesplit_bridge::livesplit_bridge
)

if(WIN32)
    target_compile_definitions(divergencesplitter_runtime PRIVATE _WIN32_WINNT=0x0A00 WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(divergencesplitter_runtime PRIVATE
        ws2_32 mswsock
    )
endif()
