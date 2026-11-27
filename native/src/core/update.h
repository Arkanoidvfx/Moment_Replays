// Self-update from GitHub releases (script: updates_check.py). A release lists its files in SHA256.json
// ({"file name": "sha256 hex"}); only changed files are downloaded, each is checked against its hash, and the
// running DLL is renamed away so the new one loads with the next OBS start.
#pragma once
#include "util.h"

#include <map>

namespace mr {

inline constexpr const char *UPDATE_REPO = "Arkanoidvfx/Moment_Replays";
inline constexpr const char *UPDATE_PLUGIN_FILE = "moment-replays.dll";
inline constexpr const char *UPDATE_HASHES_FILE = "SHA256.json";
inline constexpr size_t UPDATE_FILE_MAX = 40 * 1024 * 1024;

bool is_newer_version(std::string_view candidate, std::string_view current);
bool is_valid_update_tag(std::string_view tag);        // v?N(.N)*
bool is_valid_update_file_name(std::string_view name); // a plain name: no folders, no ".."
// {file: lower-case sha256}; nullopt unless it is a valid list that names `plugin_file`.
std::optional<std::map<std::string, std::string>> parse_update_list(std::string_view text, std::string_view plugin_file);

// Writes `data` as `path`. A file that is in use (the loaded DLL) is renamed to "<name>.old" first. Throws.
void replace_file_in_use(const fs::path &path, std::string_view data);
void remove_update_leftovers(const fs::path &folder); // "*.old" of an earlier update; in-use ones stay

struct HttpError : std::runtime_error {
	HttpError(int status, const std::string &what) : std::runtime_error(what), status(status) {}
	int status; // 0: no answer
};
std::string http_get(const std::string &url, size_t limit); // https only, follows redirects; throws HttpError

struct UpdateResult {
	enum State { Current, Installed, Available, NoRelease, Failed } state = Failed;
	std::string latest;      // the latest release's tag
	std::string release_url; // its page
	std::string reason;      // Available: a UI text key (update_reason_*); Failed: the error text
	std::string detail;      // the file name for update_reason_damaged
};
// One check, and the install when the release is newer. `bin_dir` holds the DLL, `data_dir` everything else.
// Blocking: call it on a worker thread.
UpdateResult check_for_updates(const fs::path &bin_dir, const fs::path &data_dir);

} // namespace mr
