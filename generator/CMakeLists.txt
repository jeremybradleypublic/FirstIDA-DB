cmake_minimum_required(VERSION 3.24)
project(disasmgen LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

# --- pinned native deps (network needed at first configure only) -----------
set(ASMJIT_STATIC TRUE CACHE BOOL "" FORCE)
set(ASMJIT_TEST OFF CACHE BOOL "" FORCE)
FetchContent_Declare(asmjit
  GIT_REPOSITORY https://github.com/asmjit/asmjit.git
  GIT_TAG 7596c6d035c27c9e5faad445f3214f2c971b2f2b)  # v1.18 (2025-09-06), zlib license

set(ZYDIS_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(ZYDIS_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(ZYDIS_BUILD_DOXYGEN OFF CACHE BOOL "" FORCE)
FetchContent_Declare(zydis
  GIT_REPOSITORY https://github.com/zyantific/zydis.git
  GIT_TAG v4.1.1)                                    # MIT license

FetchContent_MakeAvailable(asmjit zydis)

add_library(disasmgen_core STATIC
  src/jsonl.cpp
  src/direct.cpp
  src/render_c.cpp
  src/lower_asmjit.cpp
  src/format_zydis.cpp
  src/hybrid.cpp)
target_include_directories(disasmgen_core PUBLIC src)
target_link_libraries(disasmgen_core PUBLIC asmjit Zydis)

enable_testing()
add_executable(test_jsonl tests/test_jsonl.cpp)
target_link_libraries(test_jsonl PRIVATE disasmgen_core)
add_test(NAME jsonl COMMAND test_jsonl)

add_executable(test_direct tests/test_direct.cpp)
target_link_libraries(test_direct PRIVATE disasmgen_core)
add_test(NAME direct COMMAND test_direct)

add_executable(test_render_c tests/test_render_c.cpp)
target_link_libraries(test_render_c PRIVATE disasmgen_core)
add_test(NAME render_c COMMAND test_render_c)

add_executable(test_hybrid tests/test_hybrid.cpp)
target_link_libraries(test_hybrid PRIVATE disasmgen_core)
add_test(NAME hybrid COMMAND test_hybrid)

add_executable(disasmgen src/main.cpp)
target_link_libraries(disasmgen PRIVATE disasmgen_core)

add_test(NAME cli_direct COMMAND disasmgen direct --count 3 --seed 1)
add_test(NAME cli_hybrid COMMAND disasmgen hybrid --count 3 --seed 1)
add_test(NAME cli_bad_route COMMAND disasmgen bogus)
set_tests_properties(cli_bad_route PROPERTIES WILL_FAIL TRUE)
