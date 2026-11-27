// The plugin's one object. Everything here runs on OBS's UI thread; workers (key thread, clip-info writers,
// update check, process scan) only use the core and post their results back.
#pragma once
#include "core/autoscene.h"
#include "core/clipwrite.h"
#include "core/keys.h"
#include "core/settings.h"
#include "core/update.h"

#include <QObject>
#include <QPointer>
#include <QTimer>

#include <obs-module.h>
#include <obs-frontend-api.h>

#include <array>
#include <thread>

namespace mr {

class SettingsWindow;
struct LumaSampler;

enum class AutoSceneState { Off, WaitingScenes, OtherObs, Checking, WaitingSource, On, Error };

struct LastClip {
	std::string path;
	double saved_at = 0; // wall time
	double duration = 0;
	int marks = 0;
	bool keys = false;
	std::string info; // "mp4", "json", "" (none), "..." (being written)
	bool failed = false;
};

class Plugin : public QObject {
	Q_OBJECT
public:
	Plugin();
	~Plugin() override;
	void shutdown(); // OBS is closing: stop everything while OBS's own objects still exist

	// ---- for the settings window ----
	const Settings &settings() const { return current; }
	// Applies and saves at once. A list that breaks a rule is refused: the message names the entry.
	std::optional<RuleError> set_settings(Settings next);
	const SettingsEnv &env() const { return environment; }
	fs::path settings_path() const { return own_settings_path; }
	std::string imported_from() const { return import_source; }

	bool paused_by_script() const { return paused; }
	bool replay_buffer_active() const { return buffer_active; }
	int replay_buffer_seconds() const;
	std::string obs_recording_path() const;
	fs::path base_path() const; // where clips go: the setting, or the OBS recording folder
	std::map<std::string, FolderProblem> folder_problems() const; // by settings key
	AutoSceneState auto_scene_state() const { return auto_state; }
	std::string auto_scene_detail() const; // the hooked exe, or the other OBS
	bool keys_recording_now() const { return recorder && recorder->game_now(); }
	bool ffmpeg_found() const { return has_ffmpeg; }
	const LastClip &last_clip() const { return last; }
	std::vector<std::string> recent_apps() const; // exe paths seen in front, newest first
	std::vector<std::string> scene_names() const;
	std::vector<std::string> game_capture_names() const;
	std::string obs_save_key_text() const;

	json hotkey_bindings(const std::string &name) const;
	void set_hotkey_bindings(const std::string &name, const json &bindings);
	std::string hotkey_text(const std::string &name) const; // "Ctrl + F10", or ""

	void open_last_video();
	void play_test_sound();
	void play_sound_file(const std::string &path);
	void check_updates(bool by_user);
	const UpdateResult *update_result() const { return update_done ? &update : nullptr; }
	bool update_running() const { return update_busy; }
	void show_window();

signals:
	void state_changed();

private:
	// events
	static void frontend_event(enum obs_frontend_event event, void *data);
	void on_event(enum obs_frontend_event event);
	static void hotkey_pressed(void *data, obs_hotkey_id id, obs_hotkey_t *hotkey, bool pressed);
	static void bindings_changed(void *data, calldata_t *cd);
	void on_hotkey(const std::string &name, double pressed_at);
	void tick();
	bool refresh_paused();

	// settings
	void load_settings_first_time();
	void apply_settings();
	void save();
	void register_hotkeys();
	void skip_crash_prompt();
	void store_hotkeys();

	// replay saves
	void on_buffer_started(bool known_start);
	void on_buffer_stopped();
	void on_buffer_saved();
	fs::path move_clip(bool create_links);
	fs::path move_clip_override();
	std::string gen_clip_base_name();
	std::string clip_name_fallback();
	std::string active_exe(bool refresh = false);
	void append_exe_history();
	void forced_save(bool half);
	void reset_forced_save();
	void notify(bool success);
	void play_event_sound(bool enabled, const std::string &path);

	// recordings
	void on_recording_started();
	void on_recording_stopped();
	void toggle_alt_recording();
	void restore_recording_path();

	// clip info
	std::optional<ClipInfoInputs> collect(const std::string &origin, double clip_end, double duration, obs_output_t *output);
	void write_info_async(const fs::path &clip, std::optional<ClipInfoInputs> inputs);
	void info_written(const fs::path &clip, const std::string &where);
	double frames_to_seconds(double frames) const;
	void mark_moment();
	bool save_in_progress() const;
	void open_last_video_now();

	// auto scene
	std::optional<std::array<std::string, 3>> auto_scene_prepare(const std::string &scene);
	void auto_scene_switching(const std::string &exe_path, const std::string &scene, const std::array<std::string, 3> &names);
	bool auto_scene_attach(const std::string &source_name);
	void auto_scene_detach();
	void set_auto_state(AutoSceneState state, const std::string &log_text);
	void switch_scene(const std::string &name);
	bool run_rehook_step(const std::string &scene, const std::string &desktop_scene);
	static void capture_hooked(void *data, calldata_t *cd);
	static void capture_unhooked(void *data, calldata_t *cd);
	void request_other_obs_scan(double now);

	// keys
	void sync_keys();
	void push_key_config();
	std::vector<SaveKeyBinding> read_save_key_bindings() const;

	template<class F> void run_worker(F &&work);
	void join_workers(bool all);

	Settings current;
	SettingsEnv environment;
	NamingRules rules;
	fs::path own_settings_path, bin_dir;
	std::string import_source;
	std::vector<std::pair<std::string, obs_hotkey_id>> hotkey_ids;
	bool hotkeys_loading = false;

	QTimer ticker, open_wait, forced_watchdog, alt_watchdog, mark_stop;
	QPointer<SettingsWindow> window;
	bool closing = false, paused = false, has_ffmpeg = false, obs_started = false;
	std::atomic<bool> unloading{false};

	// replay buffer
	bool buffer_active = false;
	std::optional<double> buffer_started_at;
	int buffer_max_time = 0;
	std::deque<std::string> exe_history;
	std::map<std::string, int> exe_counts;
	std::deque<std::string> seen_apps;
	unsigned long cached_pid = 0;
	std::string cached_exe;
	bool force_override = false, half_save = false, forced_pending = false;
	std::optional<double> save_requested_at;
	double created_lag = CLIP_CREATED_LAG_S;
	bool saving = false;
	std::atomic<int> pending_info{0};
	int open_wait_ticks = 0;
	LastClip last;

	// recordings
	bool recording_active = false, alt_pending = false;
	std::optional<double> recording_started_at, recording_stop_at;
	std::optional<std::string> saved_recording_path;

	// clip info
	Timeline timeline;
	std::deque<double> markers;

	// auto scene
	AutoSceneState auto_state = AutoSceneState::Off;
	std::string auto_log;
	std::optional<AutoSceneMachine> machine;
	obs_source_t *auto_source = nullptr;
	bool auto_blocked = false, showing_held = false;
	std::string rehook_phase; // "", "pending" (wait for Desktop), "released" (ref dropped)
	BlackFrameGuard black_guard;
	LumaSampler *luma = nullptr;
	std::optional<std::string> other_obs;
	std::optional<double> other_obs_checked_at, other_obs_answered_at;
	bool other_obs_scanning = false, other_obs_paused = false;

	// keys
	std::unique_ptr<KeyRecorder> recorder;

	// updates
	UpdateResult update;
	bool update_done = false, update_busy = false;

	struct Worker {
		std::thread thread;
		std::shared_ptr<std::atomic<bool>> done;
	};
	std::vector<Worker> workers;
};

Plugin *plugin(); // nullptr before load and after unload
bool test_mode(); // MOMENT_REPLAYS_TEST is set: no sounds, nothing is opened, no network

} // namespace mr
