# ---------------------------------------------------------------------------
# Install / ZIP distribution.
# ---------------------------------------------------------------------------

if(NOT TARGET DivergenceSplitter AND NOT TARGET ScenarioBuilder)
    return()
endif()

include(GNUInstallDirs)

if(TARGET DivergenceSplitter)
    install(TARGETS DivergenceSplitter RUNTIME DESTINATION .)
    install(FILES "${PROJECT_SOURCE_DIR}/licenses/NDI.md" DESTINATION licenses)
    set(_distribution "divergencesplitter")
    if(TARGET ScenarioBuilder)
        set(_distribution "combined")
    endif()
    set(_notice "${PROJECT_SOURCE_DIR}/DISTRIBUTION-NOTICE.txt")
else()
    set(_distribution "scenario-builder")
    set(_notice "${PROJECT_SOURCE_DIR}/apps/scenario-builder/DISTRIBUTION-NOTICE.txt")
    set(_component COMPONENT ScenarioBuilder)
endif()
install(FILES "${PROJECT_SOURCE_DIR}/LICENSE" DESTINATION . RENAME LICENSE.txt ${_component})
install(FILES "${_notice}" DESTINATION . ${_component})

# Third-party license bodies belong to the dependencies, not this repository.
# Collect the actual installed notices only when producing a distribution.
file(TO_CMAKE_PATH "${Python3_EXECUTABLE}" _license_python)
set(_license_args)
if(TARGET DivergenceSplitter)
    file(TO_CMAKE_PATH "${imgui_SOURCE_DIR}" _license_imgui_dir)
    file(TO_CMAKE_PATH "${implot_SOURCE_DIR}" _license_implot_dir)
    string(APPEND _license_args " --bridge-source \"${livesplit_bridge_SOURCE_DIR}\""
        " --imgui-source \"${_license_imgui_dir}\" --implot-source \"${_license_implot_dir}\"")
endif()
if(TARGET ScenarioBuilder)
    get_target_property(_frontend ScenarioBuilder DIVERGENCESPLITTER_FRONTEND_BUILD)
    string(APPEND _license_args " --frontend \"${_frontend}\"")
endif()
install(CODE "
    execute_process(
        COMMAND \"${_license_python}\" \"${PROJECT_SOURCE_DIR}/tools/collect_licenses.py\"
            --destination \"\${CMAKE_INSTALL_PREFIX}/licenses\"
            --vcpkg-share \"${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/share\"
            --cache \"${CMAKE_BINARY_DIR}/license-cache\"
            --distribution \"${_distribution}\"${_license_args}
        COMMAND_ERROR_IS_FATAL ANY
    )
" ${_component})

if(NOT TARGET DivergenceSplitter)
    return()
endif()

if(WIN32)
    install(CODE "
        file(GLOB _app_dlls \"$<TARGET_FILE_DIR:DivergenceSplitter>/*.dll\")
        list(FILTER _app_dlls EXCLUDE REGEX \"gtest\")
        list(FILTER _app_dlls EXCLUDE REGEX \"Processing[.]NDI[.]\")
        if(_app_dlls)
            file(COPY \${_app_dlls} DESTINATION \"\${CMAKE_INSTALL_PREFIX}\")
        endif()
    ")
endif()

if(WIN32)
    install(CODE "
        file(REMOVE_RECURSE \"\${CMAKE_INSTALL_PREFIX}/include\")
        file(REMOVE_RECURSE \"\${CMAKE_INSTALL_PREFIX}/lib\")
        file(GLOB _test_dlls \"\${CMAKE_INSTALL_PREFIX}/gtest*.dll\")
        if(_test_dlls)
            file(REMOVE \${_test_dlls})
        endif()
    ")
endif()

set(CPACK_GENERATOR "ZIP")
set(CPACK_PACKAGE_NAME "DivergenceSplitter")
set(CPACK_PACKAGE_VENDOR "Nanahuse")
set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
set(CPACK_PACKAGE_FILE_NAME "DivergenceSplitter-${PROJECT_VERSION}-windows-x64")
set(CPACK_INCLUDE_TOPLEVEL_DIRECTORY OFF)
include(CPack)
