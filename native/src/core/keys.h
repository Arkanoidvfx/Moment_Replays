// Key recording (script: key_recorder.py). One thread reads the state of a fixed set of keys about 250 times a
// second while the game is the window in front, 50 times otherwise. It hooks nothing and touches no other
// process. Press times stay in memory and leave it only inside a clip the user saves. Never log them.
#pragma once
#include "autoscene.h"
#include "clipinfo.h"

#include <atomic>
#include <memory>
#include <mutex>
#include <thread>

namespace mr {

inline constexpr double KEY_POLL_S = 0.004;  // 250 Hz while a game is in front
inline constexpr double KEY_IDLE_S = 0.02;   // otherwise: only the window in front and OBS's save key are looked at
inline constexpr double GAME_CHECK_S = 0.1;  // how long the same window keeps its answer to "is it the game"
inline constexpr size_t KEY_LOG_MAXLEN = 100000; // press intervals per key

// Never a game even when fullscreen, whatever the user's Other list says: typing happens there.
bool is_never_recorded_app(std::string_view casefolded_exe_stem);

struct SaveKeyBinding { // one key bound to OBS's own "Save Replay"; modifiers must match exactly, like in OBS
	int vk = 0;
	bool shift = false, control = false, alt = false, command = false;
	bool operator==(const SaveKeyBinding &) const = default;
};

// What the key thread needs to know; the UI thread replaces the whole thing when something changes.
struct KeyConfig {
	bool record_inputs = false;
	std::vector<SaveKeyBinding> save_bindings;
	bool buffer_active = false;
	double buffer_max_time = 0;
	bool recording_active = false;
	std::optional<double> recording_started_at;
	NamingRules rules;
	std::optional<std::string> hooked_exe; // what the game capture has hooked, if auto scene is attached
};

struct WindowProbe { // the Win32 calls behind the "game in front" rule; tests replace them
	std::function<void *()> foreground = foreground_window;
	std::function<unsigned long(void *)> pid = window_pid;
	std::function<std::optional<std::string>(unsigned long)> image_path = process_image_path;
	std::function<std::optional<WindowGeometry>(void *)> geometry = window_geometry;
	std::function<double()> clock = now_mono;
	unsigned long own_pid = 0;
};

// True while the window in front is the game: the fullscreen-game rule, or the exe the game capture has hooked.
// Any doubt counts as no.
class GameInFront {
public:
	explicit GameInFront(WindowProbe probe);
	bool operator()(const KeyConfig &config);

private:
	bool is_game(void *hwnd, const KeyConfig &config);
	WindowProbe probe;
	void *named_hwnd = nullptr; // the window the cached names belong to
	unsigned long named_pid = 0;
	std::string exe, app;
	void *seen = nullptr;
	double until = 0;
	bool answer = false;
};

class KeyRecorder {
public:
	using GameCheck = std::function<bool(const KeyConfig &)>;
	using KeyState = std::function<short(int)>; // GetAsyncKeyState
	KeyRecorder(GameCheck game_in_front, KeyState key_state);
	~KeyRecorder();

	void set_config(KeyConfig config);
	void start(); // the thread; no-op if running
	void stop();
	bool running() const { return thread.joinable(); }

	void poll(double now); // one poll; the thread calls it, tests call it directly
	KeyLog snapshot();
	std::vector<double> save_key_presses();
	void drop_save_key_presses(double until); // older saves can't claim them
	bool game_now() const { return game; }

private:
	void run();
	void poll_save_keys(double now, const KeyConfig &config, const std::function<short(int)> &read);
	void poll_keys(double now, const std::vector<short> *states);
	void release(double now);
	void forget();
	void trim(double now, const KeyConfig &config);

	GameCheck game_in_front;
	KeyState key_state;
	std::atomic<std::shared_ptr<const KeyConfig>> config;
	std::mutex mutex;
	std::thread thread;
	std::atomic<bool> stopping{false}, game{false};
	unsigned long long polls = 0;
	double last_poll = 0;
	std::map<std::string, double> open; // keys held now: press time
	std::map<std::string, std::deque<Interval>> closed;
	std::deque<Interval> focus;
	std::vector<SaveKeyBinding> seen_bindings;
	std::set<size_t> save_active;
	std::deque<double> save_presses;
};

} // namespace mr
