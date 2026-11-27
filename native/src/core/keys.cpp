#include "keys.h"

#include <windows.h>
#include <mmsystem.h>
#include <algorithm>
#include <array>
#include <bitset>

namespace mr {

bool is_never_recorded_app(std::string_view stem)
{
	static const std::set<std::string, std::less<>> apps = {
		"chrome", "msedge", "firefox", "opera", "opera_gx", "brave", "vivaldi", "arc", "browser", "chromium",
		"waterfox", "librewolf", "zen", "iexplore", "discord", "discordptb", "discordcanary", "telegram", "signal",
		"whatsapp", "slack", "zoom", "skype", "teams", "ms-teams", "vlc", "mpv", "mpc-hc", "mpc-hc64", "mpc-be64",
		"potplayermini64", "potplayermini", "kmplayer", "smplayer", "wmplayer", "momentplayer", "moment player",
		"windowsterminal", "wt", "cmd", "powershell", "pwsh", "conhost", "alacritty", "wezterm-gui", "mintty",
		"code", "cursor", "explorer", "obs64", "obs",
	};
	return apps.find(stem) != apps.end();
}

// ---- GameInFront ----

GameInFront::GameInFront(WindowProbe probe_) : probe(std::move(probe_))
{
	if (!probe.own_pid)
		probe.own_pid = GetCurrentProcessId();
}

bool GameInFront::operator()(const KeyConfig &config)
{
	void *hwnd = probe.foreground();
	double now = probe.clock();
	if (hwnd != seen || now >= until) { // another window is looked at at once
		seen = hwnd;
		until = now + GAME_CHECK_S;
		answer = false;
		answer = is_game(hwnd, config);
	}
	return answer;
}

bool GameInFront::is_game(void *hwnd, const KeyConfig &config)
{
	if (!hwnd)
		return false;
	unsigned long pid = probe.pid(hwnd);
	if (!pid || pid == probe.own_pid)
		return false;
	if (named_hwnd != hwnd || named_pid != pid) {
		auto path = probe.image_path(pid);
		exe = exe_basename(path.value_or(""));
		app = path ? config.rules.app_clip_name(*path) : "";
		named_hwnd = hwnd;
		named_pid = pid;
	}
	if (exe.empty())
		return false;
	std::string stem = casefold(exe_stem(exe));
	auto &other = config.rules.other_names;
	if (is_never_recorded_app(stem) || other.count(stem) || other.count(casefold(app)))
		return false;

	auto geometry = probe.geometry(hwnd);
	if (!geometry)
		return false;
	if (is_fullscreen_game_window(*geometry, exe, app, other))
		return true;
	auto &hooked = config.hooked_exe;
	return hooked && *hooked != HOOKED_EXE_UNKNOWN && *hooked == exe && !is_shell_window_class(geometry->window_class);
}

// ---- KeyRecorder ----

KeyRecorder::KeyRecorder(GameCheck game_in_front_, KeyState key_state_)
	: game_in_front(std::move(game_in_front_)), key_state(std::move(key_state_)), config(std::make_shared<const KeyConfig>())
{
	for (auto &[name, vk] : recorded_keys()) {
		(void)vk;
		closed[name];
	}
}

KeyRecorder::~KeyRecorder()
{
	stop();
}

void KeyRecorder::set_config(KeyConfig value)
{
	// Win32 virtual-key codes range from 0x01 to 0xFE.
	std::erase_if(value.save_bindings, [](const SaveKeyBinding &binding) { return binding.vk < 1 || binding.vk > 0xFE; });
	config.store(std::make_shared<const KeyConfig>(std::move(value)));
}

void KeyRecorder::start()
{
	if (thread.joinable())
		return;
	stopping = false;
	thread = std::thread([this] { run(); });
}

void KeyRecorder::stop()
{
	stopping = true;
	if (thread.joinable())
		thread.join();
}

void KeyRecorder::run()
{
	LARGE_INTEGER freq, counter;
	QueryPerformanceFrequency(&freq);
	auto perf = [&] {
		QueryPerformanceCounter(&counter);
		return (double)counter.QuadPart / (double)freq.QuadPart;
	};
	bool fast = false, error_logged = false;
	double due = perf();
	while (!stopping) {
		try {
			poll(now_wall());
		} catch (...) {
			if (!error_logged) {
				error_logged = true;
				log_line("Key recording: a poll failed; recording continues.");
			}
		}
		if (game != fast) {
			// Sleeping follows the Windows timer: 15.6 ms by default, too slow only while keys are recorded.
			fast = game;
			fast ? timeBeginPeriod(1) : timeEndPeriod(1);
		}
		double now = perf();
		due = std::max(due + (fast ? KEY_POLL_S : KEY_IDLE_S), now);
		Sleep(std::max<DWORD>((DWORD)((due - now) * 1000 + 0.5), 1));
	}
	if (fast)
		timeEndPeriod(1);
}

void KeyRecorder::poll(double now)
{
	auto cfg = config.load();
	bool in_game = false;
	if (cfg->record_inputs) {
		try { // any doubt: record nothing
			in_game = game_in_front(*cfg);
		} catch (...) {
		}
	}
	auto &keys = recorded_keys();
	std::vector<short> states;
	if (in_game) {
		states.reserve(keys.size());
		for (auto &[name, vk] : keys)
			states.push_back(key_state(vk));
	}
	if (!cfg->save_bindings.empty() || !seen_bindings.empty()) {
		// One GetAsyncKeyState call per key per poll: it clears the "pressed since the last call" bit.
		constexpr size_t vk_slots = 256;
		std::array<short, vk_slots> cache;
		std::bitset<vk_slots> sampled;
		if (in_game) {
			for (size_t i = 0; i < keys.size(); i++) {
				const int vk = keys[i].second;
				cache[vk] = states[i];
				sampled[vk] = true;
			}
		}
		poll_save_keys(now, *cfg, [&](int vk) {
			if (!sampled[vk]) {
				cache[vk] = key_state(vk);
				sampled[vk] = true;
			}
			return cache[vk];
		});
	}
	if (!cfg->record_inputs) {
		forget();
		return;
	}
	std::lock_guard lock(mutex);
	poll_keys(now, in_game ? &states : nullptr);
	if (++polls % 250 == 0) // about once a second
		trim(now, *cfg);
}

void KeyRecorder::poll_save_keys(double now, const KeyConfig &cfg, const std::function<short(int)> &read)
{
	bool changed = cfg.save_bindings != seen_bindings; // first poll or rebound: low bits and held keys are stale
	if (changed) {
		seen_bindings = cfg.save_bindings;
		save_active.clear();
	}
	auto down = [&](std::initializer_list<int> vks) {
		return std::any_of(vks.begin(), vks.end(), [&](int vk) { return (read(vk) & 0x8000) != 0; });
	};
	auto pressed = [&] {
		std::lock_guard lock(mutex);
		save_presses.push_back(now);
		if (save_presses.size() > 64)
			save_presses.pop_front();
	};
	for (size_t i = 0; i < cfg.save_bindings.size(); i++) {
		auto &binding = cfg.save_bindings[i];
		short state = read(binding.vk);
		bool match = (state & 0x8001) && down({0x10}) == binding.shift && down({0x11}) == binding.control &&
			     down({0x12}) == binding.alt && down({0x5B, 0x5C}) == binding.command;
		if (match && (state & 0x8000)) {
			if (!save_active.count(i) && !changed)
				pressed();
			save_active.insert(i);
		} else if (save_active.count(i)) {
			save_active.erase(i);
		} else if (match && !changed) { // pressed and released between two polls
			pressed();
		}
	}
}

void KeyRecorder::poll_keys(double now, const std::vector<short> *states)
{
	if (!states) {
		release(now);
		return;
	}
	bool prime = !game; // just came to the front: presses before this moment don't count
	if (prime) {
		game = true;
		focus.push_back({now, std::nullopt});
		if (focus.size() > KEY_LOG_MAXLEN)
			focus.pop_front();
	}
	bool any = std::any_of(states->begin(), states->end(), [](short s) { return s != 0; });
	if (!open.empty() || any) {
		auto &keys = recorded_keys();
		for (size_t i = 0; i < keys.size(); i++) {
			const std::string &name = keys[i].first;
			short state = (*states)[i];
			auto held = open.find(name);
			auto &log = closed[name];
			if (state & 0x8000) {
				if (held == open.end())
					open[name] = now;
			} else if (held != open.end()) {
				log.push_back({held->second, now});
				open.erase(held);
			} else if ((state & 1) && !prime) { // pressed and released between two polls
				log.push_back({std::max(last_poll, now - 2 * KEY_POLL_S), now});
			}
			if (log.size() > KEY_LOG_MAXLEN)
				log.pop_front();
		}
	}
	last_poll = now;
}

void KeyRecorder::release(double now)
{
	if (!game) // the game is not in front: every key counts as released
		return;
	game = false;
	focus.back().end = now;
	for (auto &[name, down] : open)
		closed[name].push_back({down, now});
	open.clear();
}

void KeyRecorder::forget()
{
	if (focus.empty() && open.empty()) // recording is off: drop everything (save-key presses stay)
		return;
	std::lock_guard lock(mutex);
	game = false;
	open.clear();
	focus.clear();
	for (auto &[name, log] : closed)
		log.clear();
}

void KeyRecorder::trim(double now, const KeyConfig &cfg)
{
	double keep = now - (cfg.buffer_active ? cfg.buffer_max_time + 10 : 0);
	if (cfg.recording_active && cfg.recording_started_at)
		keep = std::min(keep, *cfg.recording_started_at - 1);
	for (auto &[name, log] : closed)
		while (!log.empty() && *log.front().end < keep)
			log.pop_front();
	while (!focus.empty() && focus.front().end && *focus.front().end < keep)
		focus.pop_front();
}

KeyLog KeyRecorder::snapshot()
{
	std::lock_guard lock(mutex);
	KeyLog out;
	out.focus.assign(focus.begin(), focus.end());
	for (auto &[name, log] : closed) {
		auto &list = out.keys[name];
		list.assign(log.begin(), log.end());
		if (auto held = open.find(name); held != open.end())
			list.push_back({held->second, std::nullopt});
	}
	return out;
}

std::vector<double> KeyRecorder::save_key_presses()
{
	std::lock_guard lock(mutex);
	return {save_presses.begin(), save_presses.end()};
}

void KeyRecorder::drop_save_key_presses(double until)
{
	std::lock_guard lock(mutex);
	while (!save_presses.empty() && save_presses.front() <= until)
		save_presses.pop_front();
}

} // namespace mr
