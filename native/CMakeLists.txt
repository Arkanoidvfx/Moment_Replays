cmake_minimum_required(VERSION 3.24)
project(moment-replays VERSION 2.0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_compile_options(/utf-8 /W3 /permissive- /MP)
add_compile_definitions(UNICODE _UNICODE NOMINMAX _CRT_SECURE_NO_WARNINGS)

# Everything that needs neither OBS nor Qt: the logic the unit tests cover.
file(GLOB CORE_SOURCES CONFIGURE_DEPENDS src/core/*.cpp src/core/*.h)
add_library(mr_core STATIC ${CORE_SOURCES})
target_include_directories(mr_core PUBLIC src/core third_party)
target_link_libraries(mr_core PUBLIC winmm bcrypt winhttp)

file(GLOB TEST_SOURCES CONFIGURE_DEPENDS tests/*.cpp)
if(TEST_SOURCES)
  add_executable(mr_tests ${TEST_SOURCES})
  target_link_libraries(mr_tests PRIVATE mr_core)
endif()

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tools/parity.cpp")
  add_executable(mr_parity tools/parity.cpp)
  target_link_libraries(mr_parity PRIVATE mr_core)
endif()

option(MR_BUILD_PLUGIN "Build the OBS plugin (needs .deps: OBS headers, import libraries, Qt)" ON)
if(MR_BUILD_PLUGIN)
  set(DEPS ${CMAKE_SOURCE_DIR}/.deps)
  set(OBS_SRC ${DEPS}/obs-studio-30.0.0) # the oldest OBS the plugin loads in
  list(PREPEND CMAKE_PREFIX_PATH ${DEPS}/qt6)
  find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)
  set(CMAKE_AUTOMOC ON)

  file(GLOB PLUGIN_SOURCES CONFIGURE_DEPENDS src/obs/*.cpp src/obs/*.h src/ui/*.cpp src/ui/*.h)
  add_library(moment-replays MODULE ${PLUGIN_SOURCES})
  target_include_directories(moment-replays PRIVATE src ${OBS_SRC}/libobs ${OBS_SRC}/UI/obs-frontend-api)
  target_link_directories(moment-replays PRIVATE ${DEPS}/implib)
  target_link_libraries(moment-replays PRIVATE mr_core obs obs-frontend-api Qt6::Core Qt6::Gui Qt6::Widgets)
endif()
