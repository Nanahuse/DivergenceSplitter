add_library(divergencesplitter_capture STATIC
    src/camera_devices.cpp
    src/capture_pipeline.cpp
    src/configured_source.cpp
    src/frame_sources.cpp
    src/ndi.cpp
    src/ndi_sdk.cpp
    src/source_configuration.cpp
)

add_library(divergencesplitter::capture ALIAS divergencesplitter_capture)

target_compile_features(divergencesplitter_capture PUBLIC cxx_std_23)
target_include_directories(divergencesplitter_capture
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
target_include_directories(divergencesplitter_capture SYSTEM PRIVATE
    "${PROJECT_SOURCE_DIR}/third_party/ndi/include"
)
target_link_libraries(divergencesplitter_capture
    PUBLIC
        divergencesplitter::core
    PRIVATE
        opencv_videoio
)

if(WIN32)
    target_compile_definitions(divergencesplitter_capture PRIVATE _WIN32_WINNT=0x0A00 WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(divergencesplitter_capture PRIVATE
        ole32 oleaut32 strmiids mf mfplat mfuuid mfreadwrite
    )
endif()
