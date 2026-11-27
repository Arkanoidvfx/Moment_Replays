// The settings file: same keys and schema as the script's Moment_Replays.settings.json (version 6), so a file
// written by the script loads here unchanged. Key names are a contract with the installer: never rename one.
#pragma once
#include "util.h"

#include <json.hpp>

namespace mr {
using json = nlohmann::ordered_json;

inline constexpr int SETTINGS_SCHEMA_VERSION = 6;
inline constexpr const char *SETTINGS_FILE_NAME = "Moment_Replays.settings.json";
inline constexpr const char *HOTKEY_NAMES[] = {"save_buffer_half", "save_buffer_override_folder", "open_last_video",
					       "record_alternative_folder", "mark_moment"};

// name, default
#define MR_STRING_SETTINGS(X) \
	X(interface_language, "en") \
	X(clips_base_path, "") \
	X(app_other_folder, OTHER_FOLDER_NAME) \
	X(clips_override_path, "") \
	X(recording_alt_folder, "") \
	X(clips_filename_template, "%NAME_%d.%m.%Y_%H-%M-%S") \
	X(clips_links_folder_path, "") \
	X(notify_clips_on_success_path, "") \
	X(notify_clips_on_failure_path, "") \
	X(notify_recording_on_start_path, "") \
	X(notify_recording_on_stop_path, "") \
	X(aliases_import_path, "") \
	X(aliases_export_path, "") \
	X(auto_scene_game, "Game") \
	X(auto_scene_desktop, "Desktop") \
	X(auto_scene_game_source, "Game Capture")

#define MR_BOOL_SETTINGS(X) \
	X(clips_save_to_folder, true) \
	X(clips_create_links, false) \
	X(sound_notification_settings, true) \
	X(notify_clips_on_success, true) \
	X(notify_clips_on_failure, true) \
	X(notify_recording_on_start, false) \
	X(notify_recording_on_stop, false) \
	X(show_more_folders, false) \
	X(show_override_folder_settings, true) \
	X(show_clip_naming_settings, false) \
	X(auto_scene_enabled, false) \
	X(write_moment_metadata, true) \
	X(record_inputs, false) \
	X(skip_crash_prompt, true) /* plugin only: OBS's "Crash Detected, run in Safe Mode?" question is not asked */

#define MR_INT_SETTINGS(X) \
	X(clips_naming_mode, 1) \
	X(short_buffer_percent, 40) \
	X(sound_volume, 40)

// What the defaults depend on outside the settings file.
struct SettingsEnv {
	fs::path data_dir;  // the plugin's data folder: bundled sounds live here
	fs::path videos;    // the user's Videos folder
	std::string obs_exe; // full path of the running OBS
};

struct Settings {
#define X(name, value) std::string name = value;
	MR_STRING_SETTINGS(X)
#undef X
#define X(name, value) bool name = value;
	MR_BOOL_SETTINGS(X)
#undef X
#define X(name, value) int name = value;
	MR_INT_SETTINGS(X)
#undef X
	std::vector<std::string> aliases_list;
	std::vector<std::string> app_other_names;
	std::vector<std::string> app_name_replacements;
	json hotkeys = json::object(); // {hotkey name: [OBS binding objects]}

	static Settings defaults(const SettingsEnv &env);
	// From a parsed settings file. Wrong types and invalid lists fall back to the defaults, key by key.
	static Settings from_json(const json &payload, const SettingsEnv &env);
	json to_json() const; // in the order the script writes the file
	bool operator==(const Settings &other) const { return to_json() == other.to_json(); }
};

// Bundled sound names, by settings key: {notify_clips_on_success_path: Replay_Saved.wav, ...}
const std::vector<std::pair<std::string, std::string>> &bundled_sounds();
// Empty, an old personal default, or a bundled sound whose file is gone -> this install's bundled file.
std::string normalize_sound_path(const std::string &key, const std::string &value, const SettingsEnv &env);

// The first existing file of `candidates` (the plugin's own file first, then where the script kept its settings),
// or the defaults. `loaded_from` gets the path used, empty for defaults.
Settings load_settings(const std::vector<fs::path> &candidates, const SettingsEnv &env, fs::path *loaded_from = nullptr);
void save_settings(const fs::path &path, const Settings &settings); // atomic; throws std::runtime_error

} // namespace mr
