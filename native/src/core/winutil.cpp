#include "winutil.h"
#include "naming.h"

#include <windows.h>
#include <tlhelp32.h>
#include <stdexcept>

namespace mr {

void *foreground_window()
{
	return GetForegroundWindow();
}

unsigned long window_pid(void *hwnd)
{
	DWORD pid = 0;
	GetWindowThreadProcessId((HWND)hwnd, &pid);
	return pid;
}

std::optional<std::string> process_image_path(unsigned long pid)
{
	HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
	if (!process)
		return std::nullopt;
	std::wstring buffer(32768, L'\0');
	DWORD size = (DWORD)buffer.size();
	bool ok = QueryFullProcessImageNameW(process, 0, buffer.data(), &size);
	CloseHandle(process);
	if (!ok)
		return std::nullopt;
	buffer.resize(size);
	return narrow(buffer);
}

std::optional<WindowGeometry> window_geometry(void *window)
{
	HWND hwnd = (HWND)window;
	RECT rect;
	if (!hwnd || !GetWindowRect(hwnd, &rect))
		return std::nullopt;
	HMONITOR monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
	MONITORINFO info{sizeof(info)};
	if (!monitor || !GetMonitorInfoW(monitor, &info))
		return std::nullopt;
	wchar_t name[256] = {};
	GetClassNameW(hwnd, name, 256);
	auto &m = info.rcMonitor;
	return WindowGeometry{{rect.left, rect.top, rect.right, rect.bottom},
			      {m.left, m.top, m.right, m.bottom},
			      narrow(name),
			      (unsigned long)GetWindowLongW(hwnd, GWL_STYLE)};
}

std::vector<std::pair<unsigned long, std::string>> list_processes()
{
	HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
	if (snapshot == INVALID_HANDLE_VALUE)
		throw std::runtime_error("CreateToolhelp32Snapshot failed");
	std::vector<std::pair<unsigned long, std::string>> out;
	PROCESSENTRY32W entry{sizeof(entry)};
	for (BOOL ok = Process32FirstW(snapshot, &entry); ok; ok = Process32NextW(snapshot, &entry))
		out.emplace_back(entry.th32ProcessID, narrow(entry.szExeFile));
	CloseHandle(snapshot);
	return out;
}

std::string own_exe_path()
{
	std::wstring buffer(32768, L'\0');
	buffer.resize(GetModuleFileNameW(nullptr, buffer.data(), (DWORD)buffer.size()));
	return narrow(buffer);
}

std::optional<double> file_created_at(const fs::path &path)
{
	WIN32_FILE_ATTRIBUTE_DATA data;
	if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &data))
		return std::nullopt;
	uint64_t ticks = (uint64_t)data.ftCreationTime.dwHighDateTime << 32 | data.ftCreationTime.dwLowDateTime;
	return (double)(ticks - 116444736000000000ULL) / 1e7; // 100 ns since 1601 -> seconds since 1970
}

bool find_in_path(const wchar_t *exe)
{
	return SearchPathW(nullptr, exe, nullptr, 0, nullptr, nullptr) > 0;
}

std::optional<FolderProblem> find_folder_problem(const fs::path &folder, const fs::path *same_drive_as)
{
	if (same_drive_as && on_another_drive(folder, *same_drive_as))
		return FolderProblem{"folder_wrong_drive", path_u8(folder), path_u8(same_drive_as->root_name())};

	std::error_code ec;
	fs::path existing = folder;
	while (!fs::exists(existing, ec)) {
		fs::path parent = existing.parent_path();
		if (parent == existing || parent.empty())
			return FolderProblem{"folder_not_found", path_u8(folder), {}};
		existing = parent;
	}
	// A real attempt: access lists and read-only shares lie. The folder's own date is put back (players sort by it).
	WIN32_FILE_ATTRIBUTE_DATA before{};
	GetFileAttributesExW(existing.c_str(), GetFileExInfoStandard, &before);
	fs::path probe = existing / std::format(L".moment_replays_{}", GetCurrentProcessId());
	bool ok = (CreateDirectoryW(probe.c_str(), nullptr) || GetLastError() == ERROR_ALREADY_EXISTS) &&
		  RemoveDirectoryW(probe.c_str());
	if (!ok)
		return FolderProblem{"folder_not_writable", path_u8(folder), {}};
	HANDLE dir = CreateFileW(existing.c_str(), FILE_WRITE_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
				 nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
	if (dir != INVALID_HANDLE_VALUE) {
		SetFileTime(dir, nullptr, &before.ftLastAccessTime, &before.ftLastWriteTime);
		CloseHandle(dir);
	}
	return std::nullopt;
}

std::pair<int, int> remove_crash_markers(const fs::path &obs_config_dir, std::string *why)
{
	int removed = 0, failed = 0;
	std::error_code ec;
	std::vector<fs::path> markers;
	for (auto &entry : fs::directory_iterator(obs_config_dir / ".sentinel", ec))
		if (entry.is_regular_file(ec) && entry.path().filename().native().starts_with(L"run_"))
			markers.push_back(entry.path());
	if (fs::is_regular_file(obs_config_dir / "safe_mode", ec))
		markers.push_back(obs_config_dir / "safe_mode");
	for (auto &marker : markers) {
		std::error_code error;
		if (fs::remove(marker, error)) {
			removed++;
		} else if (error) {
			failed++;
			if (why)
				*why = error.message();
		}
	}
	return {removed, failed};
}

bool link_clip(const fs::path &file, const fs::path &links_folder)
{
	std::error_code ec;
	fs::create_directories(links_folder, ec);
	fs::path link = links_folder / file.filename();
	if (fs::exists(link, ec)) {
		if (fs::equivalent(link, file, ec))
			return true;
		fs::path other = ensure_unique_filename(link);
		logf("Link path {} already exists and points to a different file. Creating {} instead.", path_u8(link), path_u8(other));
		link = other;
	}
	fs::create_hard_link(file, link, ec);
	if (ec) {
		logf("Cannot create hard link for clip at {}: {}", path_u8(link), ec.message());
		return false;
	}
	return true;
}

} // namespace mr
