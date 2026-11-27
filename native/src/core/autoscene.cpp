#include "autoscene.h"

#include <algorithm>

namespace mr {

static constexpr unsigned long STYLE_MAXIMIZE = 0x01000000, STYLE_BORDER = 0x00800000;

bool is_shell_window_class(std::string_view window_class)
{
	std::string folded = casefold(window_class);
	return folded == "progman" || folded == "workerw" || folded == "shell_traywnd";
}

bool is_fullscreen_game_window(const WindowGeometry &g, std::string_view exe_name, std::string_view app_name,
			       const std::set<std::string> &other_names)
{
	if (is_shell_window_class(g.window_class))
		return false;
	if ((g.style & STYLE_MAXIMIZE) && (g.style & STYLE_BORDER))
		return false;
	if (other_names.count(casefold(exe_stem(exe_name))) || other_names.count(casefold(app_name)))
		return false;
	return g.window.left <= g.monitor.left && g.window.top <= g.monitor.top && g.window.right >= g.monitor.right &&
	       g.window.bottom >= g.monitor.bottom;
}

std::optional<std::string> AutoSceneMachine::decide(double now, const std::string &current_scene, const std::string &fg_exe,
						     bool fg_is_game, const std::string &game_scene,
						     const std::string &desktop_scene, bool game_allowed)
{
	if (current_scene != game_scene && current_scene != desktop_scene) {
		lost_since.reset();
		return std::nullopt;
	}
	bool in_game = fg_is_game && hooked_exe && !hooked_exe->empty() && (*hooked_exe == HOOKED_EXE_UNKNOWN || *hooked_exe == fg_exe);

	if (current_scene == desktop_scene) {
		lost_since.reset();
		return in_game && game_allowed ? std::optional(game_scene) : std::nullopt;
	}
	if (!hooked_exe) {
		lost_since.reset();
		return desktop_scene;
	}
	if (in_game) {
		lost_since.reset();
		return std::nullopt;
	}
	if (!lost_since) {
		lost_since = now;
		return std::nullopt;
	}
	if (now - *lost_since > debounce_s) {
		lost_since.reset();
		return desktop_scene;
	}
	return std::nullopt;
}

void BlackFrameGuard::observe(double now, std::optional<int> value)
{
	luma = value;
	if (!is_black())
		black_since.reset();
	else if (!black_since)
		black_since = now;
}

bool BlackFrameGuard::fall_back(double now, const std::string &process)
{
	cooldown_until[process] = now + cooldown_s;
	black_since.reset();
	return rehooked.insert(process).second;
}

bool BlackFrameGuard::can_show_game(double now, const std::string &process) const
{
	auto found = cooldown_until.find(process);
	return now >= (found == cooldown_until.end() ? 0.0 : found->second) && !is_black();
}

int max_rgb(const unsigned char *raw, int width, int height, int linesize)
{
	int best = 0;
	for (int y = 0; y < height; y++) {
		const unsigned char *row = raw + (size_t)y * linesize;
		for (int x = 0; x < width; x++)
			best = std::max({best, (int)row[x * 4], (int)row[x * 4 + 1], (int)row[x * 4 + 2]});
	}
	return best;
}

std::vector<unsigned long> other_obs_pids(const std::vector<std::pair<unsigned long, std::string>> &processes, unsigned long own_pid)
{
	std::vector<unsigned long> out;
	for (auto &[pid, exe] : processes)
		if (pid != own_pid && casefold(exe) == OBS_PROCESS_NAME)
			out.push_back(pid);
	return out;
}

std::optional<std::string> describe_other_obs(const std::vector<std::pair<unsigned long, std::string>> &processes,
					      unsigned long own_pid,
					      const std::function<std::optional<std::string>(unsigned long)> &path_of)
{
	std::string out;
	for (unsigned long pid : other_obs_pids(processes, own_pid)) {
		if (!out.empty())
			out += ", ";
		out += path_of(pid).value_or(std::format("pid {}, path not readable", pid));
	}
	return out.empty() ? std::nullopt : std::optional(out);
}

} // namespace mr
