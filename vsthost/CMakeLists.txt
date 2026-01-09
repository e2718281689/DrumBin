cmake_minimum_required(VERSION 3.22)

project(vsthost VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if (NOT DEFINED JUCE_WEBVIEW2_PACKAGE_LOCATION)
  set(_maybe_webview2_packages "${CMAKE_SOURCE_DIR}/../WebViewPluginDemo/Builds/VisualStudio2022/packages")
  if (EXISTS "${_maybe_webview2_packages}")
    set(JUCE_WEBVIEW2_PACKAGE_LOCATION "${_maybe_webview2_packages}" CACHE PATH "" FORCE)
  endif ()
endif ()

include(FetchContent)

FetchContent_Declare(
  JUCE
  GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
  GIT_TAG 8.0.0
)
FetchContent_MakeAvailable(JUCE)

juce_add_gui_app(VSTHostApp
  PRODUCT_NAME "VSTHostApp"
  COMPANY_NAME "local"
  NEEDS_WEBVIEW2 TRUE
)

target_sources(VSTHostApp
  PRIVATE
    src/Main.cpp
)

target_compile_definitions(VSTHostApp
  PRIVATE
    JUCE_PLUGINHOST_VST3=1
    JUCE_DISPLAY_SPLASH_SCREEN=0
    JUCE_REPORT_APP_USAGE=0
    JUCE_STRICT_REFCOUNTEDPOINTER=1
    JUCE_MODAL_LOOPS_PERMITTED=1
    JUCE_USE_WIN_WEBVIEW2_WITH_STATIC_LINKING=1
)

target_compile_options(VSTHostApp
  PRIVATE
    $<$<CXX_COMPILER_ID:MSVC>:/utf-8>
)

target_link_libraries(VSTHostApp
  PRIVATE
    juce::juce_gui_extra
    juce::juce_audio_utils
    juce::juce_audio_processors
    juce::juce_audio_formats
  PUBLIC
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)

