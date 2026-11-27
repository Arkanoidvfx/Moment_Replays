// Small helpers shared by the core. Strings are UTF-8 everywhere; paths go through u8path()/path_u8().
#pragma once
#include <filesystem>
#include <format>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace mr {
namespace fs = std::filesystem;

inline constexpr const char *VERSION = "2.0.1";
inline constexpr const char *FALLBACK_CLIP_NAME = "UnknownApp";
inline constexpr const char *OTHER_FOLDER_NAME = "Other";

std::wstring widen(std::string_view text);
std::string narrow(std::wstring_view text);
fs::path u8path(std::string_view text);
std::string path_u8(const fs::path &path);

std::string trim(std::string_view text);
std::string casefold(std::string_view text); // lower case, any language
bool contains_any(std::string_view text, std::string_view chars);

double now_wall(); // seconds since 1970, like Python's time.time()
double now_mono(); // seconds, monotonic

std::optional<std::string> read_file(const fs::path &path);
void write_file_atomic(const fs::path &path, std::string_view data); // temp file, flush, replace; throws std::runtime_error
std::string sha256_hex(std::string_view data);

// The core never prints: the plugin routes this to OBS's log, tests collect or drop it.
extern std::function<void(const std::string &)> log_sink;
void log_line(const std::string &text);
template<class... Args> void logf(std::format_string<Args...> fmt, Args &&...args)
{
	log_line(std::format(fmt, std::forward<Args>(args)...));
}
} // namespace mr
