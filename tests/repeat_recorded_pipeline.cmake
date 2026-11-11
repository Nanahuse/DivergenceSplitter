math(EXPR first_iteration "(${GROUP} - 1) * 5 + 1")
math(EXPR last_iteration "${first_iteration} + 4")
foreach(iteration RANGE ${first_iteration} ${last_iteration})
    execute_process(
        COMMAND "${TEST_EXECUTABLE}" "--gtest_filter=RecordedPipeline.*:VideoFileSource.*"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE output
        ERROR_VARIABLE error
        TIMEOUT 30
    )
    if(NOT result STREQUAL "0")
        message(FATAL_ERROR
            "Recording/decoder repetition ${iteration}/20 failed (${result}):\n${output}\n${error}")
    endif()
endforeach()
message(STATUS "Recording/decoder repetitions ${first_iteration}-${last_iteration}/20 passed in 5 fresh processes")
