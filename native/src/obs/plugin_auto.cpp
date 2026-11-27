// Auto scene Game/Desktop and key recording: the parts of the plugin that watch the game.
#include "plugin.h"

#include <graphics/graphics.h>
#include <graphics/vec4.h>

#include <windows.h>
#include <mutex>

namespace mr {

// ---- black-frame sampler ----
// The brightest channel of a 32x18 downscale of the game capture, read back from the GPU on OBS's graphics thread.
// Each run returns the frame staged by the previous run and stages a new one, so mapping never stalls on the GPU.
struct LumaSampler {
	std::mutex mutex;
	std::string source_name;
	std::atomic<int> luma{-1}; // -1: unknown
	gs_texrender_t *texrender = nullptr;
	gs_stagesurf_t *stage = nullptr;
	bool staged = false;

	static constexpr uint32_t W = 32, H = 18;

	static void sample(void *param)
	{
		auto *self = (LumaSampler *)param;
		std::string name;
		{
			std::lock_guard lock(self->mutex);
			name = self->source_name;
		}
		obs_source_t *source = name.empty() ? nullptr : obs_get_source_by_name(name.c_str());
		obs_enter_graphics();
		int result = -1;
		if (self->staged) {
			self->staged = false;
			uint8_t *data = nullptr;
			uint32_t linesize = 0;
			if (gs_stagesurface_map(self->stage, &data, &linesize)) {
				result = max_rgb(data, W, H, (int)linesize);
				gs_stagesurface_unmap(self->stage);
			}
		}
		self->luma = result;
		uint32_t width = source ? obs_source_get_width(source) : 0, height = source ? obs_source_get_height(source) : 0;
		if (width && height) {
			if (!self->texrender)
				self->texrender = gs_texrender_create(GS_RGBA, GS_ZS_NONE);
			if (!self->stage)
				self->stage = gs_stagesurface_create(W, H, GS_RGBA);
			gs_texrender_reset(self->texrender);
			if (self->stage && gs_texrender_begin(self->texrender, W, H)) {
				vec4 black;
				vec4_zero(&black);
				gs_clear(GS_CLEAR_COLOR, &black, 0.0f, 0);
				gs_ortho(0.0f, (float)width, 0.0f, (float)height, -100.0f, 100.0f);
				obs_source_video_render(source);
				gs_texrender_end(self->texrender);
				if (gs_texture_t *texture = gs_texrender_get_texture(self->texrender)) {
					gs_stage_texture(self->stage, texture);
					self->staged = true;
				}
			}
		}
		obs_leave_graphics();
		obs_source_release(source);
	}

	static void destroy(void *param)
	{
		auto *self = (LumaSampler *)param;
		obs_enter_graphics();
		gs_texrender_destroy(self->texrender);
		gs_stagesurface_destroy(self->stage);
		obs_leave_graphics();
		delete self;
	}
};

// ---- auto scene ----

static obs_source_t *live_source(const std::string &name)
{
	obs_source_t *source = name.empty() ? nullptr : obs_get_source_by_name(name.c_str());
	if (source && obs_source_removed(source)) {
		obs_source_release(source);
		return nullptr;
	}
	return source;
}

static bool scene_exists(const std::string &name)
{
	obs_source_t *source = live_source(name);
	bool is_scene = source && obs_scene_from_source(source);
	obs_source_release(source);
	return is_scene;
}

void Plugin::set_auto_state(AutoSceneState state, const std::string &log_text)
{
	if (log_text != auto_log) {
		auto_log = log_text;
		logf("Auto scene: {}", log_text);
	}
	if (state != auto_state) {
		auto_state = state;
		emit state_changed();
	}
}

std::string Plugin::auto_scene_detail() const
{
	if (auto_state == AutoSceneState::OtherObs)
		return other_obs.value_or("");
	if (machine && machine->hooked_exe)
		return *machine->hooked_exe;
	return "";
}

void Plugin::capture_hooked(void *data, calldata_t *cd)
{
	auto *self = (Plugin *)data;
	auto *source = (obs_source_t *)calldata_ptr(cd, "source");
	const char *exe = calldata_string(cd, "executable");
	std::string name = exe_basename(exe ? exe : "");
	QMetaObject::invokeMethod(
		self,
		[self, source, name] {
			if (self->auto_source != source || !self->machine)
				return;
			self->machine->hooked_exe = name.empty() ? std::string(HOOKED_EXE_UNKNOWN) : name;
			self->push_key_config();
			emit self->state_changed();
		},
		Qt::QueuedConnection);
}

void Plugin::capture_unhooked(void *data, calldata_t *cd)
{
	auto *self = (Plugin *)data;
	auto *source = (obs_source_t *)calldata_ptr(cd, "source");
	QMetaObject::invokeMethod(
		self,
		[self, source] {
			if (self->auto_source != source || !self->machine)
				return;
			self->machine->hooked_exe.reset();
			self->push_key_config();
			emit self->state_changed();
		},
		Qt::QueuedConnection);
}

// Takes the game capture: a reference, its hooked/unhooked signals, and a "showing" reference so that it keeps
// hooking while the Desktop scene is on air.
bool Plugin::auto_scene_attach(const std::string &source_name)
{
	obs_source_t *source = live_source(source_name);
	if (!source)
		return false;
	const char *id = obs_source_get_unversioned_id(source);
	if (!id || strcmp(id, "game_capture") != 0) {
		obs_source_release(source);
		return false;
	}
	machine.emplace();
	if (obs_source_get_width(source) > 0) // already capturing: `hooked` will not fire again
		machine->hooked_exe = HOOKED_EXE_UNKNOWN;
	signal_handler_t *handler = obs_source_get_signal_handler(source);
	signal_handler_connect(handler, "hooked", capture_hooked, this);
	signal_handler_connect(handler, "unhooked", capture_unhooked, this);
	obs_source_inc_showing(source);
	showing_held = true;
	rehook_phase.clear();
	auto_source = source;
	if (!luma)
		luma = new LumaSampler();
	{
		std::lock_guard lock(luma->mutex);
		luma->source_name = source_name;
	}
	push_key_config();
	return true;
}

void Plugin::auto_scene_detach()
{
	if (obs_source_t *source = auto_source) {
		auto_source = nullptr;
		machine.reset();
		signal_handler_t *handler = obs_source_get_signal_handler(source);
		signal_handler_disconnect(handler, "hooked", capture_hooked, this);
		signal_handler_disconnect(handler, "unhooked", capture_unhooked, this);
		if (showing_held) // not held in the middle of a rehook
			obs_source_dec_showing(source);
		showing_held = false;
		rehook_phase.clear();
		if (luma) {
			std::lock_guard lock(luma->mutex);
			luma->source_name.clear();
			luma->luma = -1;
		}
		obs_source_release(source);
		push_key_config();
	}
	if (closing && luma) {
		// OBS's graphics thread still runs during the exit event: it frees the GPU objects after any queued sample.
		obs_queue_task(OBS_TASK_GRAPHICS, LumaSampler::destroy, luma, false);
		luma = nullptr;
	}
}

void Plugin::switch_scene(const std::string &name)
{
	obs_source_t *scene = live_source(name);
	if (!scene) {
		logf("Auto scene: scene '{}' not found.", name);
		return;
	}
	obs_frontend_set_current_scene(scene);
	obs_source_release(scene);
	logf("Auto scene: switched to '{}'.", name);
}

// First step of every tick: is auto scene active, and attach or detach the game capture. Returns
// {game scene, desktop scene, source name} when switching should run.
std::optional<std::array<std::string, 3>> Plugin::auto_scene_prepare(const std::string &scene)
{
	if (auto_blocked || !current.auto_scene_enabled) {
		auto_scene_detach();
		set_auto_state(AutoSceneState::Off, "off");
		return std::nullopt;
	}
	const std::string &game = current.auto_scene_game, &desktop = current.auto_scene_desktop,
			  &source_name = current.auto_scene_game_source;
	if (game == desktop || !scene_exists(game) || !scene_exists(desktop)) {
		auto_scene_detach();
		set_auto_state(AutoSceneState::WaitingScenes, std::format("waiting for scenes '{}' and '{}'", game, desktop));
		return std::nullopt;
	}

	double now = now_mono();
	bool fresh = other_obs_answered_at && now - *other_obs_answered_at < 2 * OTHER_OBS_CHECK_S;
	request_other_obs_scan(now);
	// Only one OBS can hold a game's hook: while another OBS runs, let go of the capture (it unhooks once nothing
	// shows it) and stay off the Game scene.
	if (other_obs) {
		auto_scene_detach();
		other_obs_paused = true;
		set_auto_state(AutoSceneState::OtherObs,
			       std::format("another OBS is running ({}); game capture paused so its game hook is left alone", *other_obs));
		if (scene == game)
			switch_scene(desktop);
		return std::nullopt;
	}
	if (!fresh) { // never attach on a stale "no other OBS"
		auto_scene_detach();
		set_auto_state(AutoSceneState::Checking, "checking whether another OBS is running");
		return std::nullopt;
	}
	if (other_obs_paused) {
		other_obs_paused = false;
		log_line("Auto scene: no other OBS is running any more; resuming game capture.");
	}

	if (auto_source) {
		const char *name = obs_source_get_name(auto_source);
		if (obs_source_removed(auto_source) || !name || source_name != name)
			auto_scene_detach();
	}
	if (!auto_source && !auto_scene_attach(source_name)) {
		set_auto_state(AutoSceneState::WaitingSource, std::format("waiting for game capture source '{}'", source_name));
		return std::nullopt;
	}
	set_auto_state(AutoSceneState::On, std::format("on ('{}' / '{}', source '{}')", game, desktop, source_name));
	return std::array<std::string, 3>{game, desktop, source_name};
}

// One-shot rehook after a black fallback: once Desktop is on air, drop our showing reference for one tick (the
// game capture unhooks when nothing shows it), then take it again (it re-hooks). True while a step ran.
bool Plugin::run_rehook_step(const std::string &scene, const std::string &desktop_scene)
{
	if (rehook_phase.empty() || !auto_source)
		return false;
	if (rehook_phase == "pending") {
		if (scene != desktop_scene)
			return false; // the Game scene would keep the capture showing
		if (showing_held) {
			obs_source_dec_showing(auto_source);
			showing_held = false;
		}
		rehook_phase = "released";
		log_line("Auto scene: re-hooking the game capture once.");
		return true;
	}
	if (!showing_held) {
		obs_source_inc_showing(auto_source);
		showing_held = true;
	}
	rehook_phase.clear();
	return true;
}

void Plugin::auto_scene_switching(const std::string &exe_path, const std::string &scene, const std::array<std::string, 3> &names)
{
	auto &[game, desktop, source_name] = names;
	if (!machine)
		return;
	double now = now_mono();
	if (run_rehook_step(scene, desktop))
		return;
	std::optional<int> sample;
	if (machine->hooked_exe && luma) {
		int value = luma->luma.load();
		if (value >= 0)
			sample = value;
		obs_queue_task(OBS_TASK_GRAPHICS, LumaSampler::sample, luma, false);
	}
	black_guard.observe(now, sample);

	std::string fg_exe = exe_basename(exe_path);
	bool fg_is_game = false;
	void *hwnd = foreground_window();
	if (!exe_path.empty() && window_pid(hwnd) != GetCurrentProcessId())
		if (auto geometry = window_geometry(hwnd))
			fg_is_game = is_fullscreen_game_window(*geometry, fg_exe, rules.app_clip_name(exe_path), rules.other_names);

	auto &hooked = machine->hooked_exe;
	std::string process = hooked && *hooked != HOOKED_EXE_UNKNOWN ? *hooked : fg_exe;
	if (scene == game && hooked && black_guard.should_fall_back(now)) {
		if (black_guard.fall_back(now, process))
			rehook_phase = "pending";
		logf("Auto scene: '{}' shows only black frames for {}; showing '{}' and keeping it off '{}' for {:.0f}s.", source_name,
		     process.empty() ? "the game" : process, desktop, game, black_guard.cooldown_s);
		switch_scene(desktop);
		return;
	}
	if (auto target = machine->decide(now, scene, fg_exe, fg_is_game, game, desktop, black_guard.can_show_game(now, process)))
		switch_scene(*target);
}

// ---- keys ----

std::vector<SaveKeyBinding> Plugin::read_save_key_bindings() const
{
	// The keys bound to OBS's own "Save Replay", as OBS holds them right now.
	std::vector<SaveKeyBinding> out;
	obs_enum_hotkey_bindings(
		[](void *data, size_t, obs_hotkey_binding_t *binding) {
			const char *name = obs_hotkey_get_name(obs_hotkey_binding_get_hotkey(binding));
			if (!name || (strcmp(name, "OBSBasic.SaveReplayBuffer") && strcmp(name, "ReplayBuffer.Save")))
				return true;
			obs_key_combination_t combo = obs_hotkey_binding_get_key_combination(binding);
			if (int vk = obs_key_to_virtual_key(combo.key))
				((std::vector<SaveKeyBinding> *)data)
					->push_back({vk, (combo.modifiers & INTERACT_SHIFT_KEY) != 0, (combo.modifiers & INTERACT_CONTROL_KEY) != 0,
						     (combo.modifiers & INTERACT_ALT_KEY) != 0, (combo.modifiers & INTERACT_COMMAND_KEY) != 0});
			return true;
		},
		&out);
	return out;
}

void Plugin::push_key_config()
{
	if (!recorder)
		return;
	KeyConfig config;
	config.record_inputs = current.record_inputs;
	config.save_bindings = read_save_key_bindings();
	config.buffer_active = buffer_active;
	config.buffer_max_time = buffer_max_time;
	config.recording_active = recording_active;
	config.recording_started_at = recording_started_at;
	config.rules = rules;
	if (machine)
		config.hooked_exe = machine->hooked_exe;
	recorder->set_config(std::move(config));
}

// The key thread runs with the replay buffer (it also times OBS's Save Replay key), and with a recording when
// key recording is on.
void Plugin::sync_keys()
{
	bool wanted = !closing && !paused && (buffer_active || (recording_active && current.record_inputs));
	if (wanted && !recorder) {
		auto front = std::make_shared<GameInFront>(WindowProbe{});
		recorder = std::make_unique<KeyRecorder>([front](const KeyConfig &config) { return (*front)(config); },
							 [](int vk) { return GetAsyncKeyState(vk); });
		push_key_config();
		recorder->start();
	} else if (!wanted && recorder) {
		recorder->stop();
		recorder.reset();
	} else {
		push_key_config();
	}
}

std::vector<std::string> Plugin::scene_names() const
{
	std::vector<std::string> out;
	char **names = obs_frontend_get_scene_names();
	for (char **name = names; name && *name; name++)
		out.emplace_back(*name);
	bfree(names);
	return out;
}

std::vector<std::string> Plugin::game_capture_names() const
{
	std::vector<std::string> out;
	obs_enum_sources(
		[](void *data, obs_source_t *source) {
			const char *id = obs_source_get_unversioned_id(source);
			if (id && !strcmp(id, "game_capture"))
				((std::vector<std::string> *)data)->emplace_back(obs_source_get_name(source));
			return true;
		},
		&out);
	return out;
}

} // namespace mr
