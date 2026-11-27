#include "settings.h"
#include "naming.h"

namespace mr {

static const std::vector<std::string> DEFAULT_OTHER_NAMES = {"chrome", "OBS",     "ChatGPT", "SunBrowser", "ms-teams",
							      "Discord", "Telegram", "steam",  "msedge",     "firefox",
							      "opera",   "WhatsApp", "Spotify", "slack",      "Zoom"};
static const std::vector<std::string> DEFAULT_REPLACEMENTS = {"VALORANT-Win64-Shipping > VALORANT", "TslGame > PUBG"};
// The script author's old personal defaults, replaced by the bundled sounds when found in a file.
static const char *LEGACY_BASE = "D:\\Shadow Play\\OBS";

const std::vector<std::pair<std::string, std::string>> &bundled_sounds()
{
	static const std::vector<std::pair<std::string, std::string>> sounds = {
		{"notify_clips_on_success_path", "Replay_Saved.wav"},
		{"notify_clips_on_failure_path", "Replay_Failed.wav"},
		{"notify_recording_on_start_path", "Recording_Started.wav"},
		{"notify_recording_on_stop_path", "Recording_Stoped.wav"},
	};
	return sounds;
}

static std::string bundled_sound_path(const std::string &key, const SettingsEnv &env)
{
	for (auto &[name, file] : bundled_sounds())
		if (name == key)
			return path_u8(env.data_dir / file);
	return {};
}

std::string normalize_sound_path(const std::string &key, const std::string &value, const SettingsEnv &env)
{
	std::string fallback = bundled_sound_path(key, env);
	std::string folded = casefold(value);
	std::string legacy = key == "notify_clips_on_success_path" ? std::string(LEGACY_BASE) + "\\Success_VideoClip.wav"
								   : std::string(LEGACY_BASE);
	if (trim(value).empty() || folded == casefold(legacy))
		return fallback;
	std::error_code ec;
	fs::path path = u8path(value);
	if (casefold(path_u8(path.filename())) == casefold(path_u8(u8path(fallback).filename())) && !fs::is_regular_file(path, ec))
		return fallback; // a bundled sound of a script folder that is gone
	return value;
}

Settings Settings::defaults(const SettingsEnv &env)
{
	Settings s;
	s.clips_links_folder_path = path_u8(env.videos / "_links");
	for (auto &[key, file] : bundled_sounds()) {
		(void)file;
		std::string path = bundled_sound_path(key, env);
		if (key == "notify_clips_on_success_path")
			s.notify_clips_on_success_path = path;
		else if (key == "notify_clips_on_failure_path")
			s.notify_clips_on_failure_path = path;
		else if (key == "notify_recording_on_start_path")
			s.notify_recording_on_start_path = path;
		else
			s.notify_recording_on_stop_path = path;
	}
	s.aliases_list = {"C:\\Windows\\explorer.exe > Desktop"};
	if (!env.obs_exe.empty())
		s.aliases_list.push_back(env.obs_exe + " > OBS");
	s.app_other_names = DEFAULT_OTHER_NAMES;
	s.app_name_replacements = DEFAULT_REPLACEMENTS;
	return s;
}

// A list as the file has it: strings, or OBS's editable-list objects {"value": "..."}.
static std::optional<std::vector<std::string>> read_list(const json &payload, const char *key)
{
	auto found = payload.find(key);
	if (found == payload.end() || !found->is_array())
		return std::nullopt;
	std::vector<std::string> out;
	for (auto &item : *found) {
		if (item.is_string())
			out.push_back(item.get<std::string>());
		else if (item.is_object() && item.contains("value") && item["value"].is_string())
			out.push_back(item["value"].get<std::string>());
		else
			out.push_back(item.dump());
	}
	return out;
}

Settings Settings::from_json(const json &payload, const SettingsEnv &env)
{
	Settings s = defaults(env);
	if (!payload.is_object())
		return s;

#define X(name, value) \
	if (auto it = payload.find(#name); it != payload.end() && it->is_string()) \
		s.name = it->get<std::string>();
	MR_STRING_SETTINGS(X)
#undef X
#define X(name, value) \
	if (auto it = payload.find(#name); it != payload.end() && it->is_boolean()) \
		s.name = it->get<bool>();
	MR_BOOL_SETTINGS(X)
#undef X
#define X(name, value) \
	if (auto it = payload.find(#name); it != payload.end() && it->is_number_integer()) \
		s.name = it->get<int>();
	MR_INT_SETTINGS(X)
#undef X
	s.clips_save_to_folder = true; // always on since script 1.0; old files may say false
	if (!valid_app_folder(s.app_other_folder))
		s.app_other_folder = OTHER_FOLDER_NAME;

	s.notify_clips_on_success_path = normalize_sound_path("notify_clips_on_success_path", s.notify_clips_on_success_path, env);
	s.notify_clips_on_failure_path = normalize_sound_path("notify_clips_on_failure_path", s.notify_clips_on_failure_path, env);
	s.notify_recording_on_start_path =
		normalize_sound_path("notify_recording_on_start_path", s.notify_recording_on_start_path, env);
	s.notify_recording_on_stop_path =
		normalize_sound_path("notify_recording_on_stop_path", s.notify_recording_on_stop_path, env);

	auto load_list = [&](const char *key, std::vector<std::string> &target, auto normalize) {
		if (auto list = read_list(payload, key)) {
			try {
				target = normalize(*list);
			} catch (const RuleError &) {
				logf("Saved {} is invalid. Falling back to defaults for this list.", key);
			}
		}
	};
	load_list("aliases_list", s.aliases_list, normalize_aliases);
	load_list("app_other_names", s.app_other_names, normalize_other_names);
	load_list("app_name_replacements", s.app_name_replacements, normalize_replacements);

	if (auto it = payload.find("hotkeys"); it != payload.end() && it->is_object()) {
		for (const char *name : HOTKEY_NAMES) {
			auto bindings = it->find(name);
			if (bindings == it->end() || !bindings->is_array())
				continue;
			json kept = json::array();
			for (auto &binding : *bindings)
				if (binding.is_object())
					kept.push_back(binding);
			s.hotkeys[name] = kept;
		}
	}
	return s;
}

json Settings::to_json() const
{
	json out = json::object();
	out["version"] = SETTINGS_SCHEMA_VERSION;
#define X(name, value) out[#name] = name;
	MR_STRING_SETTINGS(X)
	MR_BOOL_SETTINGS(X)
	MR_INT_SETTINGS(X)
#undef X
	out["clips_save_to_folder"] = true;
	out["aliases_list"] = aliases_list;
	out["app_other_names"] = app_other_names;
	out["app_name_replacements"] = app_name_replacements;
	out["hotkeys"] = hotkeys;
	return out;
}

Settings load_settings(const std::vector<fs::path> &candidates, const SettingsEnv &env, fs::path *loaded_from)
{
	if (loaded_from)
		loaded_from->clear();
	for (auto &path : candidates) {
		auto text = read_file(path);
		if (!text)
			continue;
		json payload = json::parse(*text, nullptr, false);
		if (!payload.is_object()) {
			logf("Cannot read settings from {}. Skipping this file.", path_u8(path));
			continue;
		}
		if (loaded_from)
			*loaded_from = path;
		return Settings::from_json(payload, env);
	}
	return Settings::defaults(env);
}

void save_settings(const fs::path &path, const Settings &settings)
{
	std::error_code ec;
	fs::create_directories(path.parent_path(), ec);
	write_file_atomic(path, settings.to_json().dump(2) + "\n");
}

} // namespace mr
