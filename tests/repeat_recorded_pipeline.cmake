foreach(iteration RANGE 1 20)
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
message(STATUS "Recording/decoder regressions passed in 20 fresh processes")
