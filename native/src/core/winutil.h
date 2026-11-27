// Win32 lookups: the window in front, its process, running processes, folder checks, hard links.
#pragma once
#include "util.h"

namespace mr {

struct Rect {
	long left, top, right, bottom;
};
struct WindowGeometry {
	Rect window, monitor;
	std::string window_class;
	unsigned long style;
};

void *foreground_window();
unsigned long window_pid(void *hwnd);
std::optional<std::string> process_image_path(unsigned long pid); // nullopt: not readable (elevated, gone)
std::optional<WindowGeometry> window_geometry(void *hwnd);
std::vector<std::pair<unsigned long, std::string>> list_processes(); // (pid, exe file name); throws std::runtime_error
std::string own_exe_path();

std::optional<double> file_created_at(const fs::path &path); // wall time; NTFS keeps it through a rename
bool find_in_path(const wchar_t *exe);                       // e.g. L"ffmpeg.exe"

// Why clips can't be saved in a folder, as a UI text key with its arguments. A folder that does not exist yet is
// fine: it is made when the first clip is saved.
struct FolderProblem {
	std::string key; // folder_wrong_drive | folder_not_found | folder_not_writable
	std::string path, drive;
};
std::optional<FolderProblem> find_folder_problem(const fs::path &folder, const fs::path *same_drive_as = nullptr);

// OBS notes every start in a marker file and deletes it on a clean exit; a marker found at the next start makes it
// ask "OBS Studio Crash Detected. Run in Safe Mode?". OBS 32+: <config>\.sentinel\run_<id>, OBS 30 and 31:
// <config>\safe_mode. Removes them from that one folder. Returns {removed, failed}; `why` gets the last error.
std::pair<int, int> remove_crash_markers(const fs::path &obs_config_dir, std::string *why = nullptr);

// A second name for the same file in `links_folder` (same drive). False when it could not be made.
bool link_clip(const fs::path &file, const fs::path &links_folder);

} // namespace mr
