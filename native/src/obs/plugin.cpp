#include "plugin.h"
#include "ui/texts.h"
#include "ui/window.h"
#include "core/mp4.h"
#include "core/sound.h"

#include <QAction>
#include <QMainWindow>

#include <util/config-file.h>
#include <util/dstr.h>

#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>

OBS_DECLARE_MODULE()

namespace mr {

static Plugin *the_plugin = nullptr;

Plugin *plugin()
{
	return the_plugin;
}

bool test_mode()
{
	static bool on = GetEnvironmentVariableW(L"MOMENT_REPLAYS_TEST", nullptr, 0) > 0;
	return on;
}

// ---- small OBS helpers ----

static std::string cfg_string(const char *section, const char *name)
{
	config_t *config = obs_frontend_get_profile_config();
	const char *value = config ? config_get_string(config, section, name) : nullptr;
	return value ? value : "";
}

static long long cfg_int(const char *section, const char *name)
{
	config_t *config = obs_frontend_get_profile_config();
	return config ? config_get_int(config, section, name) : 0;
}

static bool simple_output()
{
	return cfg_string("Output", "Mode") == "Simple";
}

static std::string current_scene_name()
{
	obs_source_t *scene = obs_frontend_get_current_scene();
	const char *name = scene ? obs_source_get_name(scene) : nullptr;
	std::string out = name ? name : "";
	obs_source_release(scene);
	return out;
}

static std::string take(char *text) // a string OBS allocated for us
{
	std::string out = text ? text : "";
	bfree(text);
	return out;
}

static obs_data_array_t *bindings_to_obs(const json &bindings)
{
	obs_data_array_t *array = obs_data_array_create();
	if (bindings.is_array()) {
		for (auto &binding : bindings) {
			obs_data_t *item = obs_data_create_from_json(binding.dump().c_str());
			if (item)
				obs_data_array_push_back(array, item);
			obs_data_release(item);
		}
	}
	return array;
}

static json bindings_from_obs(obs_data_array_t *array)
{
	json out = json::array();
	for (size_t i = 0; array && i < obs_data_array_count(array); i++) {
		obs_data_t *item = obs_data_array_item(array, i);
		json parsed = json::parse(obs_data_get_json(item), nullptr, false);
		if (parsed.is_object())
			out.push_back(parsed);
		obs_data_release(item);
	}
	return out;
}

static const json &default_bindings(const std::string &name)
{
	static const json defaults = {
		{"save_buffer_half", {{{"key", "OBS_KEY_F10"}, {"control", true}}}},
		{"save_buffer_override_folder", {{{"key", "OBS_KEY_F10"}, {"alt", true}}}},
		{"open_last_video", {{{"key", "OBS_KEY_F10"}, {"control", true}, {"alt", true}}}},
		{"mark_moment", {{{"key", "OBS_KEY_F8"}}}},
		{"record_alternative_folder", json::array()},
	};
	return defaults[name];
}

static std::string binding_text(const json &binding)
{
	std::string text;
	for (auto &[flag, label] : std::initializer_list<std::pair<const char *, const char *>>{
		     {"control", "Ctrl"}, {"alt", "Alt"}, {"shift", "Shift"}, {"command", "Win"}})
		if (binding.value(flag, false))
			text += std::string(label) + " + ";
	dstr key = {};
	obs_key_to_str(obs_key_from_name(binding.value("key", "").c_str()), &key);
	text += key.array ? key.array : "";
	dstr_free(&key);
	return text;
}

// ---- lifecycle ----

// OBS 33 loads third-party plugins from <plugin folder>\<name>.dll and calls the older <plugin folder>\bin\64bit
// "legacy". An earlier install of this plugin may have left its DLL there: OBS skips it once the new one is loaded,
// and here it is removed for good.
static void remove_legacy_copy(const fs::path &plugin_dir)
{
	if (casefold(path_u8(plugin_dir.filename())) == "64bit")
		return; // this is the legacy layout itself (OBS 30 to 32 know no other)
	fs::path old = plugin_dir / "bin" / "64bit";
	std::error_code ec;
	if (!fs::is_directory(old, ec))
		return;
	for (const char *name : {"moment-replays.dll", "moment-replays.pdb", "moment-replays.dll.old", "moment-replays.dll.new"})
		fs::remove(old / name, ec);
	fs::remove(old, ec); // only when empty
	fs::remove(plugin_dir / "bin", ec);
}

// What the Plugin Manager's "Legacy" label says, from the same OBS function (OBS 33+; older ones have no such thing).
static const char *location_kind()
{
	using is_legacy_t = bool (*)(obs_module_t *);
	HMODULE obs = GetModuleHandleW(L"obs.dll");
	auto is_legacy = obs ? (is_legacy_t)GetProcAddress(obs, "obs_is_legacy_module") : nullptr;
	if (!is_legacy)
		return "this OBS has one plugin layout";
	return is_legacy(obs_current_module()) ? "legacy location, OBS will stop loading plugins from it" : "current location";
}

Plugin::Plugin()
{
	the_plugin = this;
	log_sink = [](const std::string &text) { blog(LOG_INFO, "[Moment Replays] %s", text.c_str()); };
	if (test_mode())
		sounds_muted = true;

	// A portable OBS gives these relative to its bin folder: sound paths are saved, so make them whole.
	environment.data_dir = fs::absolute(u8path(obs_get_module_data_path(obs_current_module()))).lexically_normal();
	bin_dir = fs::absolute(u8path(obs_get_module_binary_path(obs_current_module()))).lexically_normal().parent_path();
	PWSTR videos = nullptr;
	if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_Videos, 0, nullptr, &videos)))
		environment.videos = videos;
	CoTaskMemFree(videos);
	environment.obs_exe = own_exe_path();
	own_settings_path = fs::absolute(u8path(take(obs_module_config_path(SETTINGS_FILE_NAME)))).lexically_normal();
	has_ffmpeg = find_in_path(L"ffmpeg.exe");
	remove_update_leftovers(bin_dir);
	remove_legacy_copy(bin_dir);

	load_settings_first_time();
	register_hotkeys();
	apply_settings();

	obs_frontend_add_event_callback(frontend_event, this);
	signal_handler_connect(obs_get_signal_handler(), "hotkey_bindings_changed", bindings_changed, this);

	auto *action = (QAction *)obs_frontend_add_tools_menu_qaction("Moment Replays");
	connect(action, &QAction::triggered, this, &Plugin::show_window);

	connect(&ticker, &QTimer::timeout, this, &Plugin::tick);
	ticker.start(1000);
	open_wait.setInterval(250);
	connect(&open_wait, &QTimer::timeout, this, [this] {
		if (save_in_progress() && --open_wait_ticks > 0)
			return;
		open_wait.stop();
		open_last_video_now();
	});
	forced_watchdog.setSingleShot(true);
	connect(&forced_watchdog, &QTimer::timeout, this, [this] {
		if (forced_pending) {
			log_line("Forced save timed out. Resetting forced-save state.");
			reset_forced_save();
		}
	});
	alt_watchdog.setSingleShot(true);
	connect(&alt_watchdog, &QTimer::timeout, this, [this] {
		// Recording never became active: undo the path override so normal recordings are not redirected.
		if (obs_frontend_recording_active())
			return;
		if (saved_recording_path) {
			log_line("Alternative recording did not start; restoring the OBS recording path.");
			restore_recording_path();
		}
		alt_pending = false;
	});
	mark_stop.setSingleShot(true);
	connect(&mark_stop, &QTimer::timeout, this, [] { stop_sound(); });

	logf("Loaded, version {}. Settings: {}", VERSION, path_u8(own_settings_path));
	logf("Plugin folder: {} ({})", path_u8(bin_dir), location_kind());
}

Plugin::~Plugin()
{
	shutdown();
	the_plugin = nullptr;
	log_sink = nullptr;
}

void Plugin::shutdown()
{
	if (closing)
		return;
	closing = true;
	unloading = true; // clip info still waiting for a file stops retrying and uses the sidecar
	ticker.stop();
	open_wait.stop();
	forced_watchdog.stop();
	alt_watchdog.stop();
	obs_frontend_remove_event_callback(frontend_event, this);
	signal_handler_disconnect(obs_get_signal_handler(), "hotkey_bindings_changed", bindings_changed, this);
	if (window)
		window->close();
	store_hotkeys();
	auto_scene_detach();
	restore_recording_path();
	if (recorder)
		recorder->stop();
	recorder.reset();
	stop_sound();
	join_workers(true);
	for (auto &[name, id] : hotkey_ids)
		obs_hotkey_unregister(id);
	hotkey_ids.clear();
	log_line("Unloaded.");
}

void Plugin::frontend_event(enum obs_frontend_event event, void *data)
{
	((Plugin *)data)->on_event(event);
}

void Plugin::on_event(enum obs_frontend_event event)
{
	switch (event) {
	case OBS_FRONTEND_EVENT_EXIT:
		auto_blocked = true;
		shutdown();
		return;
	case OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGING:
	case OBS_FRONTEND_EVENT_SCENE_COLLECTION_CLEANUP:
		auto_blocked = true; // OBS is about to tear sources down: let go of the game capture first
		auto_scene_detach();
		return;
	case OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED:
	case OBS_FRONTEND_EVENT_FINISHED_LOADING:
		auto_blocked = false;
		if (event == OBS_FRONTEND_EVENT_FINISHED_LOADING) {
			obs_started = true;
			skip_crash_prompt();
			recording_active = obs_frontend_recording_active();
			if (obs_frontend_replay_buffer_active() && !buffer_active)
				on_buffer_started(false);
			if (!test_mode())
				check_updates(false);
			if (QString shots = qEnvironmentVariable("MOMENT_REPLAYS_TEST_SHOTS"); test_mode() && !shots.isEmpty())
				QTimer::singleShot(12000, this, [this, shots] {
					show_window();
					window->save_shots(shots);
					logf("UI self-test: {}", window->self_test());
					window->close();
				});
		}
		return;
	case OBS_FRONTEND_EVENT_SCENE_CHANGED:
		if (!timeline.empty()) { // the moment the scene changes, not up to 1 s later
			auto last_entry = timeline.back();
			record_timeline_sample(timeline, now_wall(), last_entry.app, last_entry.exe, current_scene_name());
		}
		return;
	case OBS_FRONTEND_EVENT_PROFILE_CHANGED:
		push_key_config();
		emit state_changed();
		return;
	default:
		break;
	}
	if (refresh_paused())
		return;
	switch (event) {
	case OBS_FRONTEND_EVENT_REPLAY_BUFFER_STARTED:
		on_buffer_started(true);
		break;
	case OBS_FRONTEND_EVENT_REPLAY_BUFFER_STOPPED:
		on_buffer_stopped();
		break;
	case OBS_FRONTEND_EVENT_REPLAY_BUFFER_SAVED:
		on_buffer_saved();
		break;
	case OBS_FRONTEND_EVENT_RECORDING_STARTED:
		on_recording_started();
		break;
	case OBS_FRONTEND_EVENT_RECORDING_STOPPING:
		recording_stop_at = now_wall(); // a recording ends when it was asked to stop
		break;
	case OBS_FRONTEND_EVENT_RECORDING_STOPPED:
		on_recording_stopped();
		break;
	default:
		break;
	}
}

// The script and the plugin must never both handle a clip. The script registers frontend hotkeys with the same
// names as ours, so one of those names with an id that is not ours means the script is loaded.
bool Plugin::refresh_paused()
{
	struct Search {
		Plugin *self;
		bool found;
	} search{this, false};
	obs_enum_hotkeys(
		[](void *data, obs_hotkey_id id, obs_hotkey_t *key) {
			auto *s = (Search *)data;
			if (obs_hotkey_get_registerer_type(key) != OBS_HOTKEY_REGISTERER_FRONTEND)
				return true;
			const char *name = obs_hotkey_get_name(key);
			for (auto &[ours, our_id] : s->self->hotkey_ids)
				if (name && ours == name && our_id != id)
					s->found = true;
			return !s->found;
		},
		&search);
	if (search.found != paused) {
		paused = search.found;
		if (paused) {
			log_line("The Moment Replays script is loaded too: the plugin is paused so clips are not handled twice. "
				 "Remove the script in Tools > Scripts and the plugin takes over.");
			auto_scene_detach();
			reset_forced_save();
		} else {
			log_line("The Moment Replays script is gone: the plugin is active.");
			buffer_active = false;
			if (obs_frontend_replay_buffer_active())
				on_buffer_started(false);
			recording_active = obs_frontend_recording_active();
		}
		sync_keys();
		emit state_changed();
	}
	return paused;
}

// ---- settings ----

// The script's settings files of this OBS: next to a Moment_Replays.py named in a scene collection. The collection
// in use comes first (that script is the one the user runs), then the others, newest first.
static std::vector<fs::path> script_settings_files(const fs::path &own_settings, const std::string &current_collection)
{
	std::vector<std::tuple<bool, fs::file_time_type, fs::path>> found;
	std::error_code ec;
	fs::path scenes = own_settings.parent_path().parent_path().parent_path() / "basic" / "scenes";
	for (auto &entry : fs::directory_iterator(scenes, ec)) {
		if (entry.path().extension() != L".json")
			continue;
		auto text = read_file(entry.path());
		json collection = text ? json::parse(*text, nullptr, false) : json();
		if (!collection.is_object() || !collection.contains("modules") || !collection["modules"].is_object())
			continue;
		json scripts = collection["modules"].value("scripts-tool", json::array());
		bool in_use = collection.value("name", "") == current_collection;
		for (auto &script : scripts) {
			if (!script.is_object() || !script.contains("path") || !script["path"].is_string())
				continue;
			fs::path file = u8path(script["path"].get<std::string>());
			if (casefold(path_u8(file.filename())) != "moment_replays.py")
				continue;
			for (const char *name : {SETTINGS_FILE_NAME, "arkanoid_replays.settings.json"}) {
				fs::path sidecar = file.parent_path() / name;
				if (fs::exists(sidecar, ec))
					found.emplace_back(in_use, fs::last_write_time(sidecar, ec), sidecar);
			}
		}
	}
	std::sort(found.begin(), found.end(), [](auto &a, auto &b) {
		return std::pair(std::get<0>(a), std::get<1>(a)) > std::pair(std::get<0>(b), std::get<1>(b));
	});
	std::vector<fs::path> out;
	for (auto &item : found)
		if (std::find(out.begin(), out.end(), std::get<2>(item)) == out.end())
			out.push_back(std::get<2>(item));
	return out;
}

void Plugin::load_settings_first_time()
{
	std::vector<fs::path> candidates = {own_settings_path};
	for (auto &file : script_settings_files(own_settings_path, take(obs_frontend_get_current_scene_collection())))
		candidates.push_back(file);
	wchar_t appdata[MAX_PATH] = {};
	if (GetEnvironmentVariableW(L"APPDATA", appdata, MAX_PATH))
		candidates.push_back(fs::path(appdata) / "Moment Replays" / SETTINGS_FILE_NAME); // the script's backup copy

	fs::path from;
	current = load_settings(candidates, environment, &from);
	if (from.empty() || from == own_settings_path)
		return;

	// Taken over from the script: its bundled sounds become ours, so its folder can go. Custom sounds stay.
	import_source = path_u8(from);
	for (auto &[key, file] : bundled_sounds()) {
		std::string *value = key == "notify_clips_on_success_path"     ? &current.notify_clips_on_success_path
				     : key == "notify_clips_on_failure_path"   ? &current.notify_clips_on_failure_path
				     : key == "notify_recording_on_start_path" ? &current.notify_recording_on_start_path
									       : &current.notify_recording_on_stop_path;
		if (casefold(path_u8(u8path(*value).filename())) == casefold(file))
			*value = path_u8(environment.data_dir / file);
	}
	logf("Settings and hotkeys taken over from the script: {}", import_source);
	save();
}

void Plugin::save()
{
	try {
		save_settings(own_settings_path, current);
	} catch (const std::exception &error) {
		logf("Cannot save the settings: {}", error.what());
	}
}

void Plugin::apply_settings()
{
	auto load = [&](const char *what, auto &&loader, const std::vector<std::string> &list, const std::vector<std::string> &fallback) {
		try {
			loader(list);
		} catch (const RuleError &) {
			logf("Saved {} are invalid. Falling back to defaults.", what);
			loader(fallback);
		}
	};
	Settings defaults = Settings::defaults(environment);
	load("path names", [&](auto &list) { rules.load_aliases(list); }, current.aliases_list, defaults.aliases_list);
	load("Other apps", [&](auto &list) { rules.load_other_names(list); }, current.app_other_names, defaults.app_other_names);
	load("name fixes", [&](auto &list) { rules.load_replacements(list); }, current.app_name_replacements,
	     defaults.app_name_replacements);

	load_language(current.interface_language, environment.data_dir);
	for (auto &[name, id] : hotkey_ids)
		obs_hotkey_set_description(id, hotkey_description(name).c_str());
	if (!current.auto_scene_enabled)
		auto_scene_detach();
	skip_crash_prompt(); // just turned on: from now on
	sync_keys();
	emit state_changed();
}

std::optional<RuleError> Plugin::set_settings(Settings next)
{
	try {
		next.aliases_list = normalize_aliases(next.aliases_list);
		next.app_other_names = normalize_other_names(next.app_other_names);
		next.app_name_replacements = normalize_replacements(next.app_name_replacements);
	} catch (const RuleError &error) {
		return error;
	}
	next.hotkeys = current.hotkeys;
	next.short_buffer_percent = std::clamp(next.short_buffer_percent, 5, 100);
	next.sound_volume = std::clamp(next.sound_volume, 0, 100);
	if (next == current)
		return std::nullopt;
	current = std::move(next);
	save();
	apply_settings();
	return std::nullopt;
}

// OBS asks "Crash Detected, run in Safe Mode?" at a start that finds the marker of an earlier run. With the setting
// on, the markers go once OBS has finished loading, this run's own included: whatever ends this run, the next start
// asks nothing. Not earlier than that on purpose: if OBS dies while it starts (a broken plugin, this one included),
// the marker is still there and OBS offers Safe Mode, which is the way out of a crash at every start.
void Plugin::skip_crash_prompt()
{
	if (!current.skip_crash_prompt || !obs_started)
		return;
	std::string why;
	auto [removed, failed] = remove_crash_markers(own_settings_path.parent_path().parent_path().parent_path(), &why);
	if (failed)
		logf("Crash question: {} start marker(s) of OBS could not be removed ({}); OBS may ask about Safe Mode at its next start.",
		     failed, why);
	else if (removed)
		logf("Crash question: {} start marker(s) of OBS removed; OBS will not ask about Safe Mode at its next start. "
		     "Safe Mode is still there: start OBS with --safe-mode.",
		     removed);
}

// ---- hotkeys ----

void Plugin::register_hotkeys()
{
	load_language(current.interface_language, environment.data_dir);
	hotkeys_loading = true;
	for (const char *name : HOTKEY_NAMES) {
		obs_hotkey_id id = obs_hotkey_register_frontend(name, hotkey_description(name).c_str(), hotkey_pressed, this);
		hotkey_ids.emplace_back(name, id);
		// The settings file's keys (the script wrote them there too), else the same defaults as the script's.
		obs_data_array_t *array = bindings_to_obs(current.hotkeys.contains(name) ? current.hotkeys[name] : default_bindings(name));
		obs_hotkey_load(id, array);
		obs_data_array_release(array);
	}
	hotkeys_loading = false;
	store_hotkeys();
}

void Plugin::store_hotkeys()
{
	if (hotkey_ids.empty())
		return;
	json all = json::object();
	for (auto &[name, id] : hotkey_ids) {
		obs_data_array_t *array = obs_hotkey_save(id);
		all[name] = bindings_from_obs(array);
		obs_data_array_release(array);
	}
	if (all == current.hotkeys)
		return;
	current.hotkeys = all;
	save();
	emit state_changed();
}

void Plugin::bindings_changed(void *data, calldata_t *cd)
{
	auto *self = (Plugin *)data;
	auto *key = (obs_hotkey_t *)calldata_ptr(cd, "key");
	if (!key || self->hotkeys_loading)
		return;
	// OBS holds its hotkey lock here: look and save later, on the UI thread.
	QMetaObject::invokeMethod(
		self,
		[self] {
			if (self->closing)
				return;
			self->store_hotkeys();
			self->push_key_config(); // OBS's own Save Replay key may be the one that changed
		},
		Qt::QueuedConnection);
}

void Plugin::hotkey_pressed(void *data, obs_hotkey_id id, obs_hotkey_t *, bool pressed)
{
	if (!pressed)
		return;
	auto *self = (Plugin *)data;
	double at = now_wall(); // the clip ends here, whenever the UI thread gets to it
	for (auto &[name, our_id] : self->hotkey_ids)
		if (our_id == id)
			QMetaObject::invokeMethod(self, [self, name = name, at] { self->on_hotkey(name, at); });
}

void Plugin::on_hotkey(const std::string &name, double pressed_at)
{
	if (closing || refresh_paused())
		return;
	if (name == "mark_moment") {
		markers.push_back(pressed_at);
		if (markers.size() > MARKERS_MAXLEN)
			markers.pop_front();
		mark_moment();
	} else if (name == "open_last_video") {
		open_last_video();
	} else if (name == "record_alternative_folder") {
		toggle_alt_recording();
	} else {
		save_requested_at = pressed_at;
		forced_save(name == "save_buffer_half");
	}
}

json Plugin::hotkey_bindings(const std::string &name) const
{
	return current.hotkeys.value(name, json::array());
}

void Plugin::set_hotkey_bindings(const std::string &name, const json &bindings)
{
	for (auto &[ours, id] : hotkey_ids) {
		if (ours != name)
			continue;
		obs_data_array_t *array = bindings_to_obs(bindings);
		hotkeys_loading = true;
		obs_hotkey_load(id, array);
		hotkeys_loading = false;
		obs_data_array_release(array);
	}
	store_hotkeys();
}

std::string Plugin::hotkey_text(const std::string &name) const
{
	std::string text;
	for (auto &binding : hotkey_bindings(name))
		text += (text.empty() ? "" : ", ") + binding_text(binding);
	return text;
}

std::string Plugin::obs_save_key_text() const
{
	struct Search {
		std::string text;
	} search;
	obs_enum_hotkey_bindings(
		[](void *data, size_t, obs_hotkey_binding_t *binding) {
			const char *name = obs_hotkey_get_name(obs_hotkey_binding_get_hotkey(binding));
			if (!name || (strcmp(name, "OBSBasic.SaveReplayBuffer") && strcmp(name, "ReplayBuffer.Save")))
				return true;
			obs_key_combination_t combo = obs_hotkey_binding_get_key_combination(binding);
			json item = {{"key", obs_key_to_name(combo.key)},
				     {"control", (combo.modifiers & INTERACT_CONTROL_KEY) != 0},
				     {"alt", (combo.modifiers & INTERACT_ALT_KEY) != 0},
				     {"shift", (combo.modifiers & INTERACT_SHIFT_KEY) != 0},
				     {"command", (combo.modifiers & INTERACT_COMMAND_KEY) != 0}};
			auto *s = (Search *)data;
			s->text += (s->text.empty() ? "" : ", ") + binding_text(item);
			return true;
		},
		&search);
	return search.text;
}

// ---- replay buffer ----

int Plugin::replay_buffer_seconds() const
{
	return (int)cfg_int(simple_output() ? "SimpleOutput" : "AdvOut", "RecRBTime");
}

std::string Plugin::obs_recording_path() const
{
	return simple_output() ? cfg_string("SimpleOutput", "FilePath") : cfg_string("AdvOut", "RecFilePath");
}

fs::path Plugin::base_path() const
{
	return u8path(current.clips_base_path.empty() ? obs_recording_path() : current.clips_base_path);
}

std::map<std::string, FolderProblem> Plugin::folder_problems() const
{
	std::string obs_path = obs_recording_path();
	fs::path obs_folder = u8path(obs_path);
	std::vector<std::tuple<std::string, std::string, bool>> folders = {
		{"clips_base_path", current.clips_base_path.empty() ? obs_path : current.clips_base_path, true}};
	if (current.show_override_folder_settings) {
		folders.emplace_back("clips_override_path", current.clips_override_path, true);
		folders.emplace_back("recording_alt_folder", current.recording_alt_folder, false); // recordings: any drive
	}
	if (current.clips_create_links)
		folders.emplace_back("clips_links_folder_path", current.clips_links_folder_path, true);
	std::map<std::string, FolderProblem> out;
	for (auto &[key, folder, same_drive] : folders) {
		if (folder.empty())
			continue;
		if (auto problem = find_folder_problem(u8path(folder), same_drive ? &obs_folder : nullptr))
			out[key] = *problem;
	}
	return out;
}

void Plugin::on_buffer_started(bool known_start)
{
	buffer_active = true;
	buffer_started_at = known_start ? std::optional(now_wall()) : std::nullopt; // unknown: assume a full buffer
	buffer_max_time = replay_buffer_seconds();
	exe_history.clear();
	exe_counts.clear();
	cached_pid = 0;
	cached_exe.clear();
	saving = false;
	open_wait.stop();
	if (recorder)
		recorder->drop_save_key_presses(now_wall());
	logf("Replay buffer is on ({} s).", buffer_max_time);
	sync_keys();
	emit state_changed();
}

void Plugin::on_buffer_stopped()
{
	buffer_active = false;
	buffer_started_at.reset();
	exe_history.clear();
	exe_counts.clear();
	saving = false;
	open_wait.stop();
	reset_forced_save();
	sync_keys();
	emit state_changed();
}

std::string Plugin::active_exe(bool refresh)
{
	unsigned long pid = window_pid(foreground_window());
	if (refresh || pid != cached_pid || cached_exe.empty()) {
		auto path = process_image_path(pid);
		cached_pid = path ? pid : 0;
		cached_exe = path.value_or("");
	}
	return cached_exe;
}

void Plugin::append_exe_history()
{
	std::string exe = active_exe();
	if (!exe.empty()) { // for "Add from recent apps": remembered whether or not the buffer runs
		auto known = std::find(seen_apps.begin(), seen_apps.end(), exe);
		if (known != seen_apps.end())
			seen_apps.erase(known);
		seen_apps.push_front(exe);
		if (seen_apps.size() > 12)
			seen_apps.pop_back();
	}
	if (!buffer_active || buffer_max_time <= 0 || exe.empty())
		return;
	if ((int)exe_history.size() == buffer_max_time) {
		std::string dropped = exe_history.back();
		exe_history.pop_back();
		if (--exe_counts[dropped] <= 0)
			exe_counts.erase(dropped);
	}
	exe_history.push_front(exe);
	exe_counts[exe]++;
}

std::string Plugin::clip_name_fallback()
{
	std::string scene = current_scene_name();
	if (!scene.empty() && !contains_any(scene, FILENAME_PROHIBITED)) {
		logf("Falling back to current scene name: {}", scene);
		return scene;
	}
	return FALLBACK_CLIP_NAME;
}

std::string Plugin::gen_clip_base_name()
{
	auto mode = (NamingMode)std::clamp(current.clips_naming_mode, 0, 2);
	if (mode == NamingMode::CurrentScene)
		return current_scene_name();
	std::string exe;
	if (mode == NamingMode::MostRecordedProcess && !exe_counts.empty())
		exe = std::max_element(exe_counts.begin(), exe_counts.end(), [](auto &a, auto &b) { return a.second < b.second; })->first;
	if (exe.empty())
		exe = active_exe(true);
	if (exe.empty()) {
		log_line("Cannot find the app in front for the clip name.");
		return clip_name_fallback();
	}
	return rules.app_clip_name(exe);
}

static std::string last_replay_path()
{
	obs_output_t *output = obs_frontend_get_replay_buffer_output();
	if (!output)
		throw std::runtime_error("Replay buffer output is unavailable.");
	calldata_t cd = {};
	proc_handler_call(obs_output_get_proc_handler(output), "get_last_replay", &cd);
	const char *path = calldata_string(&cd, "path");
	std::string out = path ? path : "";
	calldata_free(&cd);
	obs_output_release(output);
	if (out.empty())
		throw std::runtime_error("OBS did not return the last replay file path.");
	return out;
}

static void move_file(const fs::path &from, const fs::path &to)
{
	if (on_another_drive(from, to))
		throw std::runtime_error(std::format("Cannot move clip across drives: {} -> {}. Keep the OBS recording path and "
						     "the Moment Replays folders on the same drive.",
						     path_u8(from), path_u8(to)));
	std::error_code ec;
	fs::create_directories(to.parent_path(), ec);
	if (!MoveFileExW(from.c_str(), to.c_str(), 0)) // never a copy: a big clip would stall OBS
		throw std::runtime_error(std::format("Cannot move the clip to {} (error {}).", path_u8(to), GetLastError()));
	fs::last_write_time(to.parent_path(), fs::file_time_type::clock::now(), ec); // players sort folders by date
}

fs::path Plugin::move_clip(bool create_links)
{
	fs::path old = u8path(last_replay_path());
	auto mode = (NamingMode)std::clamp(current.clips_naming_mode, 0, 2);
	std::string raw = gen_clip_base_name();
	std::string name = sanitize_clip_component(raw);
	if (name != raw)
		logf("Clip name sanitized: '{}' -> '{}'.", raw, name);
	fs::path folder = base_path() / u8path(rules.folder_name(name, mode, current.app_other_folder));
	fs::path target = ensure_unique_filename(folder / (u8path(gen_filename_now(name, current.clips_filename_template)).native() +
							    old.extension().native()));
	move_file(old, target);
	if (create_links && current.clips_create_links)
		link_clip(target, u8path(current.clips_links_folder_path));
	return target;
}

fs::path Plugin::move_clip_override()
{
	fs::path old = u8path(last_replay_path());
	fs::path folder = current.clips_override_path.empty() ? base_path() : u8path(current.clips_override_path);
	fs::path target = ensure_unique_filename(folder / old.filename());
	move_file(old, target);
	return target;
}

void Plugin::forced_save(bool half)
{
	// Second folder and short clip: only with "Extra hotkeys" on, a running buffer, and one at a time.
	if (!current.show_override_folder_settings || !obs_frontend_replay_buffer_active() || forced_pending) {
		save_requested_at.reset();
		return;
	}
	forced_pending = true;
	force_override = !half;
	half_save = half;
	obs_frontend_replay_buffer_save();
	forced_watchdog.start(std::max(30000, (replay_buffer_seconds() + 30) * 1000));
}

void Plugin::reset_forced_save()
{
	forced_pending = force_override = half_save = false;
	save_requested_at.reset();
	forced_watchdog.stop();
}

void Plugin::play_event_sound(bool enabled, const std::string &path)
{
	if (current.sound_notification_settings && enabled && !path.empty())
		play_sound(path, current.sound_volume);
}

void Plugin::notify(bool success)
{
	if (success)
		play_event_sound(current.notify_clips_on_success, current.notify_clips_on_success_path);
	else
		play_event_sound(current.notify_clips_on_failure, current.notify_clips_on_failure_path);
}

void Plugin::play_test_sound()
{
	// The first enabled sound (the "clip saved" one if none is), at the current volume.
	const std::string *path = &current.notify_clips_on_success_path;
	if (!current.notify_clips_on_success) {
		if (current.notify_clips_on_failure)
			path = &current.notify_clips_on_failure_path;
		else if (current.notify_recording_on_start)
			path = &current.notify_recording_on_start_path;
		else if (current.notify_recording_on_stop)
			path = &current.notify_recording_on_stop_path;
	}
	play_sound(*path, current.sound_volume);
}

void Plugin::play_sound_file(const std::string &path)
{
	play_sound(path, current.sound_volume);
}

double Plugin::frames_to_seconds(double frames) const
{
	obs_video_info info;
	double fps = obs_get_video_info(&info) && info.fps_den ? (double)info.fps_num / info.fps_den : 60.0;
	return frames / fps;
}

void Plugin::on_buffer_saved()
{
	double event_at = now_wall();
	saving = true;
	bool override_save = force_override, half = half_save;
	fs::path path;
	try {
		path = override_save ? move_clip_override() : move_clip(!half);
	} catch (const std::exception &error) {
		logf("The clip could not be moved: {}", error.what());
		reset_forced_save();
		notify(false);
		saving = false;
		last = {};
		last.failed = true;
		last.saved_at = event_at;
		emit state_changed();
		return;
	}
	logf("Clip saved at {}", path_u8(path));

	auto created_at = file_created_at(path);
	std::vector<double> presses = recorder ? recorder->save_key_presses() : std::vector<double>();
	ClipEnd end = pick_clip_end(event_at, created_at, save_requested_at, presses, frames_to_seconds(REPLAY_END_FRAMES), created_lag);
	if (auto lag = learn_created_lag(end, created_at))
		created_lag = *lag;
	if (recorder)
		recorder->drop_save_key_presses(event_at); // older saves can't claim them
	logf("Clip end taken from: {}", end.anchor);

	int max_time = replay_buffer_seconds();
	double elapsed = buffer_started_at ? std::max(end.time - *buffer_started_at, 0.0) : (double)max_time;
	double full_duration = max_time ? std::min((double)max_time, elapsed) : elapsed;
	obs_output_t *output = obs_frontend_get_replay_buffer_output();
	auto full = collect("replay_buffer", end.time, full_duration, output);

	last = {};
	last.path = path_u8(path);
	last.saved_at = event_at;
	last.duration = full_duration;
	last.info = full ? "..." : "";
	last.marks = (int)std::count_if(markers.begin(), markers.end(),
					[&](double m) { return end.time - full_duration <= m && m <= end.time; });

	if (half) {
		double seconds = max_time * std::clamp(current.short_buffer_percent, 5, 100) / 100.0;
		auto brief = collect("short_clip", end.time, std::min(seconds, full_duration), output);
		bool links = current.clips_create_links;
		fs::path links_folder = u8path(current.clips_links_folder_path);
		pending_info++;
		run_worker([this, path, seconds, links, links_folder, brief, full] {
			bool trimmed = trim_clip_to_last_seconds(path, seconds, unloading);
			if (links)
				link_clip(path, links_folder);
			// A failed trim keeps the full clip, so its info must describe the full clip.
			auto &inputs = trimmed ? brief : full;
			std::string where = inputs ? write_clip_info(path, *inputs, INFO_RETRY_S, unloading) : "";
			pending_info--;
			QMetaObject::invokeMethod(this, [this, path, where] { info_written(path, where); }, Qt::QueuedConnection);
		});
	} else {
		write_info_async(path, full);
	}
	obs_output_release(output);
	reset_forced_save();
	notify(true);
	saving = false;
	emit state_changed();
}

// ---- recordings ----

void Plugin::on_recording_started()
{
	recording_started_at = now_wall();
	recording_stop_at.reset();
	recording_active = true;
	// The recording is live and has taken its output path: put OBS's path back so the next one is not redirected.
	alt_watchdog.stop();
	restore_recording_path();
	play_event_sound(current.notify_recording_on_start, current.notify_recording_on_start_path);
	sync_keys();
	emit state_changed();
}

void Plugin::on_recording_stopped()
{
	alt_watchdog.stop();
	restore_recording_path();
	double clip_end = recording_stop_at ? *recording_stop_at + frames_to_seconds(RECORDING_END_FRAMES) : now_wall();
	recording_stop_at.reset();
	std::string origin = alt_pending ? "alt_recording" : "recording";
	auto started = recording_started_at;
	recording_started_at.reset();
	std::string file = take(obs_frontend_get_last_recording());

	if (alt_pending) {
		alt_pending = false;
		if (!file.empty())
			logf("Alternative recording saved at {}", file);
	}
	// Only for a recording we saw start; otherwise the last recording may be an older file.
	if (!file.empty() && started) {
		obs_output_t *output = obs_frontend_get_recording_output();
		auto inputs = collect(origin, clip_end, clip_end - *started, output);
		obs_output_release(output);
		last = {};
		last.path = file;
		last.saved_at = now_wall();
		last.duration = clip_end - *started;
		last.info = inputs ? "..." : "";
		write_info_async(u8path(file), inputs);
	}
	recording_active = false;
	play_event_sound(current.notify_recording_on_stop, current.notify_recording_on_stop_path);
	sync_keys();
	emit state_changed();
}

void Plugin::restore_recording_path()
{
	if (!saved_recording_path)
		return;
	if (config_t *config = obs_frontend_get_profile_config())
		config_set_string(config, simple_output() ? "SimpleOutput" : "AdvOut", simple_output() ? "FilePath" : "RecFilePath",
				  saved_recording_path->c_str());
	logf("Restored OBS recording path to {}", *saved_recording_path);
	saved_recording_path.reset();
}

void Plugin::toggle_alt_recording()
{
	if (!current.show_override_folder_settings)
		return;
	if (obs_frontend_recording_active()) {
		obs_frontend_recording_stop();
		return;
	}
	fs::path folder = current.recording_alt_folder.empty() ? base_path() : u8path(current.recording_alt_folder);
	std::error_code ec;
	fs::create_directories(folder, ec);
	config_t *config = obs_frontend_get_profile_config();
	if (ec || !config) {
		logf("Cannot create the recordings folder {}. Not recording.", path_u8(folder));
		return;
	}
	// The path is changed in memory only and put back as soon as the recording has started, so a normal
	// recording never goes to this folder, and remux and file splitting work as usual.
	saved_recording_path = obs_recording_path();
	config_set_string(config, simple_output() ? "SimpleOutput" : "AdvOut", simple_output() ? "FilePath" : "RecFilePath",
			  path_u8(folder).c_str());
	alt_pending = true;
	logf("Starting a recording into {}", path_u8(folder));
	obs_frontend_recording_start();
	alt_watchdog.start(8000);
}

// ---- clip info ----

std::optional<ClipInfoInputs> Plugin::collect(const std::string &origin, double clip_end, double duration, obs_output_t *output)
{
	if (!current.write_moment_metadata)
		return std::nullopt;
	ClipInfoInputs in;
	in.origin = origin;
	in.clip_end = clip_end;
	in.duration = duration;
	in.timeline_log = timeline;
	in.markers.assign(markers.begin(), markers.end());
	in.game_scene = current.auto_scene_game;
	in.obs_version = obs_get_version_string();

	long long mask = cfg_int(simple_output() ? "SimpleOutput" : "AdvOut", "RecTracks");
	if (!mask)
		mask = 1;
	for (int n = 1; n <= 6; n++) {
		if (!(mask & (1LL << (n - 1))))
			continue;
		std::string name = cfg_string("AdvOut", std::format("Track{}Name", n).c_str());
		in.audio_tracks.emplace_back(n, name.empty() ? std::format("Track {}", n) : name);
	}

	obs_video_info video;
	if (obs_get_video_info(&video) && video.fps_den)
		in.preset.fps = (double)video.fps_num / video.fps_den;
	if (obs_encoder_t *encoder = output ? obs_output_get_video_encoder(output) : nullptr) {
		if (const char *id = obs_encoder_get_id(encoder); id && *id)
			in.preset.encoder = id;
		if (uint32_t width = obs_encoder_get_width(encoder))
			in.preset.width = (int)width;
		if (uint32_t height = obs_encoder_get_height(encoder))
			in.preset.height = (int)height;
		if (obs_data_t *data = obs_encoder_get_settings(encoder)) {
			std::string rate = obs_data_get_string(data, "rate_control");
			if (!rate.empty())
				in.preset.rate_control = rate;
			std::string upper = rate;
			for (char &c : upper)
				c = (char)toupper((unsigned char)c);
			const char *quality = upper == "CQP" ? "cqp" : upper == "CRF" ? "crf" : upper == "ICQ" ? "icq_quality" : nullptr;
			if (quality)
				in.preset.cq = (int)obs_data_get_int(data, quality);
			obs_data_release(data);
		}
	}
	if (current.record_inputs && recorder)
		in.key_log = recorder->snapshot();

	return in;
}

void Plugin::write_info_async(const fs::path &clip, std::optional<ClipInfoInputs> inputs)
{
	if (!inputs)
		return;
	pending_info++;
	run_worker([this, clip, inputs = std::move(*inputs)] {
		std::string where = write_clip_info(clip, inputs, INFO_RETRY_S, unloading);
		pending_info--;
		QMetaObject::invokeMethod(this, [this, clip, where] { info_written(clip, where); }, Qt::QueuedConnection);
	});
}

void Plugin::info_written(const fs::path &clip, const std::string &where)
{
	if (closing || last.path != path_u8(clip))
		return;
	last.info = where;
	if (auto length = read_mp4_duration(clip))
		last.duration = *length;
	if (where == "mp4") {
		if (auto info = read_clip_info(clip)) {
			json payload = json::parse(*info, nullptr, false);
			last.keys = payload.is_object() && payload.contains("inputs");
			if (payload.is_object() && payload.contains("annotations"))
				last.marks = (int)payload["annotations"].size();
		}
	}
	emit state_changed();
}

void Plugin::mark_moment()
{
	log_line("Moment marked.");
	// A short blip of the success sound.
	if (current.sound_notification_settings && current.notify_clips_on_success) {
		play_sound(current.notify_clips_on_success_path, current.sound_volume);
		mark_stop.start(200);
	}
}

bool Plugin::save_in_progress() const
{
	return saving || pending_info > 0 || forced_pending; // a clip counts as saved only once its info is written
}

void Plugin::open_last_video()
{
	if (open_wait.isActive())
		return; // already waiting for a save: repeated presses do nothing
	if (save_in_progress()) {
		log_line("A save is in progress; the last video will open once it finishes.");
		open_wait_ticks = (std::max(30000, (replay_buffer_seconds() + 30) * 1000) + 5000) / 250;
		open_wait.start();
		return;
	}
	open_last_video_now();
}

void Plugin::open_last_video_now()
{
	// The newest existing file among the last clip handled here, OBS's last recording and OBS's last replay.
	std::vector<fs::path> candidates;
	if (!last.path.empty())
		candidates.push_back(u8path(last.path));
	for (std::string path : {take(obs_frontend_get_last_recording()), take(obs_frontend_get_last_replay())})
		if (!path.empty())
			candidates.push_back(u8path(path));
	std::optional<fs::path> newest;
	std::error_code ec;
	for (auto &candidate : candidates)
		if (fs::is_regular_file(candidate, ec) &&
		    (!newest || fs::last_write_time(candidate, ec) > fs::last_write_time(*newest, ec)))
			newest = candidate;
	if (!newest) {
		log_line("Open last video: no saved video found yet.");
		return;
	}
	logf("Opening last video: {}", path_u8(*newest));
	if (!test_mode())
		ShellExecuteW(nullptr, L"open", newest->c_str(), nullptr, nullptr, SW_SHOWNORMAL);
}

// ---- the 1 s sampler ----

void Plugin::tick()
{
	if (closing)
		return;
	join_workers(false);
	if (refresh_paused())
		return;
	std::string scene = current_scene_name();
	auto names = auto_scene_prepare(scene);
	append_exe_history();
	std::string exe = active_exe();
	record_timeline_sample(timeline, now_wall(), rules.app_clip_name(exe), exe_basename(exe), scene);
	if (names)
		auto_scene_switching(exe, scene, *names);
}

std::vector<std::string> Plugin::recent_apps() const
{
	return {seen_apps.begin(), seen_apps.end()};
}

// ---- workers ----

template<class F> void Plugin::run_worker(F &&work)
{
	auto done = std::make_shared<std::atomic<bool>>(false);
	workers.push_back({std::thread([work = std::forward<F>(work), done]() mutable {
				   try {
					   work();
				   } catch (...) {
				   }
				   *done = true;
			   }),
			   done});
}

void Plugin::join_workers(bool all)
{
	for (auto it = workers.begin(); it != workers.end();) {
		if (all || *it->done) {
			it->thread.join();
			it = workers.erase(it);
		} else {
			++it;
		}
	}
}

// ---- updates ----

void Plugin::check_updates(bool by_user)
{
	if (update_busy || closing)
		return;
	(void)by_user;
	update_busy = true;
	emit state_changed();
	run_worker([this, bin = bin_dir, data = environment.data_dir] {
		UpdateResult result = check_for_updates(bin, data);
		QMetaObject::invokeMethod(
			this,
			[this, result] {
				update = result;
				update_done = true;
				update_busy = false;
				static const char *states[] = {"up to date", "a new version was installed; it starts with the next OBS start",
							       "a new version is available but was not installed", "no release is published",
							       "the check failed"};
				logf("Update check: {} (latest: {}{}{})", states[result.state], result.latest.empty() ? "?" : result.latest,
				     result.reason.empty() ? "" : ", ", result.reason);
				emit state_changed();
			},
			Qt::QueuedConnection);
	});
}

void Plugin::show_window()
{
	if (!window) {
		window = new SettingsWindow(this, (QWidget *)obs_frontend_get_main_window());
		window->setAttribute(Qt::WA_DeleteOnClose);
	}
	window->show();
	window->raise();
	window->activateWindow();
}

// run_worker is a template used by plugin_auto.cpp too: give it the one instantiation it needs.
void Plugin::request_other_obs_scan(double now)
{
	if (other_obs_scanning || (other_obs_checked_at && now - *other_obs_checked_at < OTHER_OBS_CHECK_S))
		return;
	other_obs_checked_at = now;
	other_obs_scanning = true;
	// A scan takes several ms with hundreds of processes: not on the UI thread.
	run_worker([this] {
		std::optional<std::string> found;
		bool ok = true;
		try {
			// Tests run next to the user's own OBS: there the guard would always be on.
			if (!(test_mode() && GetEnvironmentVariableW(L"MOMENT_REPLAYS_TEST_ALONE", nullptr, 0)))
				found = describe_other_obs(list_processes(), GetCurrentProcessId(), process_image_path);
		} catch (...) {
			ok = false; // keeps the previous answer
		}
		QMetaObject::invokeMethod(
			this,
			[this, found, ok] {
				if (ok)
					other_obs = found;
				other_obs_answered_at = now_mono();
				other_obs_scanning = false;
			},
			Qt::QueuedConnection);
	});
}

} // namespace mr

// ---- module entry points ----

MODULE_EXPORT const char *obs_module_name(void)
{
	return "Moment Replays";
}

MODULE_EXPORT const char *obs_module_description(void)
{
	return "Names and sorts replay clips by game, with sounds, short clips, marks, Game/Desktop auto scenes and clip info for "
	       "Moment Player.";
}

bool obs_module_load(void)
{
	new mr::Plugin();
	return true;
}

void obs_module_unload(void)
{
	delete mr::plugin();
}
