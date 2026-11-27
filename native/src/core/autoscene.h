// Auto scene Game/Desktop: the decisions, without OBS (script: auto_scene.py).
#pragma once
#include "naming.h"
#include "winutil.h"

namespace mr {

inline constexpr double AUTO_SCENE_DEBOUNCE_S = 1.5;
inline constexpr int BLACK_LUMA_THRESHOLD = 12; // brightest R/G/B value at or below which a frame is "black"
inline constexpr double BLACK_FALLBACK_S = 2.0;  // black this long on the Game scene -> show Desktop
inline constexpr double BLACK_COOLDOWN_S = 60.0; // then keep that process off the Game scene this long
inline constexpr double OTHER_OBS_CHECK_S = 2.5;
inline constexpr const char *HOOKED_EXE_UNKNOWN = "*"; // capturing already when we attached: exe not known
inline constexpr const char *OBS_PROCESS_NAME = "obs64.exe";

// True when the window in front looks like a game: it covers its whole monitor, is not the desktop or taskbar,
// is not a regular maximized window (OBS game capture's own rule), and its app is not in the Other list.
bool is_fullscreen_game_window(const WindowGeometry &geometry, std::string_view exe_name, std::string_view app_name,
			       const std::set<std::string> &other_names);
bool is_shell_window_class(std::string_view window_class);

// Game/Desktop decision with a debounce on the way back to Desktop.
class AutoSceneMachine {
public:
	explicit AutoSceneMachine(double debounce_s = AUTO_SCENE_DEBOUNCE_S) : debounce_s(debounce_s) {}
	// The scene to switch to, or nullopt. Scenes other than the two are left alone.
	std::optional<std::string> decide(double now, const std::string &current_scene, const std::string &fg_exe, bool fg_is_game,
					  const std::string &game_scene, const std::string &desktop_scene, bool game_allowed = true);

	std::optional<std::string> hooked_exe; // set by the game capture's hooked/unhooked signals
	std::optional<double> lost_since;
	double debounce_s;
};

// "Hooked but black" protection, per process, for the whole OBS session.
class BlackFrameGuard {
public:
	void observe(double now, std::optional<int> luma); // brightest sampled channel; nullopt = unknown
	bool is_black() const { return luma && *luma <= threshold; }
	bool should_fall_back(double now) const { return black_since && now - *black_since >= window_s; }
	bool fall_back(double now, const std::string &process); // true the first time per process: one rehook is worth a try
	bool can_show_game(double now, const std::string &process) const;

	int threshold = BLACK_LUMA_THRESHOLD;
	double window_s = BLACK_FALLBACK_S, cooldown_s = BLACK_COOLDOWN_S;
	std::optional<int> luma;
	std::optional<double> black_since;
	std::map<std::string, double> cooldown_until;
	std::set<std::string> rehooked;
};

int max_rgb(const unsigned char *raw, int width, int height, int linesize); // alpha ignored

std::vector<unsigned long> other_obs_pids(const std::vector<std::pair<unsigned long, std::string>> &processes, unsigned long own_pid);
// Human-readable list of other running OBS instances, or nullopt. Unreadable paths still count.
std::optional<std::string> describe_other_obs(const std::vector<std::pair<unsigned long, std::string>> &processes,
					      unsigned long own_pid,
					      const std::function<std::optional<std::string>(unsigned long)> &path_of);

} // namespace mr
