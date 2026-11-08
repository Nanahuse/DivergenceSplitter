# ---------------------------------------------------------------------------
# Install / ZIP distribution.
# ---------------------------------------------------------------------------

if(NOT TARGET DivergenceSplitter)
    return()
endif()

include(GNUInstallDirs)

if(TARGET DivergenceSplitter)
    install(TARGETS DivergenceSplitter RUNTIME DESTINATION .)
endif()
install(FILES "${PROJECT_SOURCE_DIR}/LICENSE" DESTINATION . RENAME LICENSE.txt)
install(FILES "${PROJECT_SOURCE_DIR}/DISTRIBUTION-NOTICE.txt" DESTINATION .)
install(DIRECTORY "${PROJECT_SOURCE_DIR}/licenses/" DESTINATION licenses)
# Third-party license bodies belong to the dependencies, not this repository.
# Collect the actual installed notices only when producing a distribution.
file(TO_CMAKE_PATH "${Python3_EXECUTABLE}" _license_python)
set(_license_imgui_args)
if(DIVERGENCESPLITTER_BUILD_UI)
    file(TO_CMAKE_PATH "${imgui_SOURCE_DIR}" _license_imgui_dir)
    set(_license_imgui_args "--imgui-source \"${_license_imgui_dir}\"")
endif()
install(CODE "
    execute_process(
        COMMAND \"${_license_python}\" \"${PROJECT_SOURCE_DIR}/tools/collect_licenses.py\"
            --destination \"\${CMAKE_INSTALL_PREFIX}/licenses\"
            --vcpkg-share \"${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/share\"
            --bridge-source \"${livesplit_bridge_SOURCE_DIR}\"
            --cache \"${CMAKE_BINARY_DIR}/license-cache\"
            ${_license_imgui_args}
        COMMAND_ERROR_IS_FATAL ANY
    )
")
if(WIN32)
    install(CODE "
        file(GLOB _app_dlls \"${CMAKE_BINARY_DIR}/*.dll\")
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
