#include "update.h"
#include "settings.h"

#include <windows.h>
#include <winhttp.h>
#include <cctype>

namespace mr {

static std::vector<int> version_parts(std::string_view value)
{
	std::vector<int> parts;
	for (size_t i = 0; i < value.size();) {
		if (!isdigit((unsigned char)value[i])) {
			i++;
			continue;
		}
		int number = 0;
		for (; i < value.size() && isdigit((unsigned char)value[i]); i++)
			number = number * 10 + (value[i] - '0');
		parts.push_back(number);
	}
	return parts;
}

bool is_newer_version(std::string_view candidate, std::string_view current)
{
	auto a = version_parts(candidate), b = version_parts(current);
	if (a.empty() || b.empty())
		return false;
	a.resize(std::max(a.size(), b.size()));
	b.resize(a.size());
	return a > b;
}

bool is_valid_update_tag(std::string_view tag)
{
	if (!tag.empty() && tag[0] == 'v')
		tag.remove_prefix(1);
	if (tag.empty() || !isdigit((unsigned char)tag.front()) || !isdigit((unsigned char)tag.back()))
		return false;
	for (size_t i = 0; i < tag.size(); i++)
		if (!(isdigit((unsigned char)tag[i]) || (tag[i] == '.' && tag[i - 1] != '.')))
			return false;
	return true;
}

bool is_valid_update_file_name(std::string_view name)
{
	if (name.empty() || name[0] == '.' || name.find("..") != std::string_view::npos)
		return false;
	for (char c : name)
		if (!(isalnum((unsigned char)c) || c == '_' || c == '-' || c == '.'))
			return false;
	return true;
}

std::optional<std::map<std::string, std::string>> parse_update_list(std::string_view text, std::string_view plugin_file)
{
	json list = json::parse(text, nullptr, false);
	if (!list.is_object() || !list.contains(std::string(plugin_file)))
		return std::nullopt;
	std::map<std::string, std::string> out;
	for (auto &[name, hash] : list.items()) {
		if (!hash.is_string() || !is_valid_update_file_name(name))
			return std::nullopt;
		out[name] = casefold(hash.get<std::string>());
	}
	return out;
}

void replace_file_in_use(const fs::path &path, std::string_view data)
{
	fs::path fresh = path.native() + L".new", old = path.native() + L".old";
	HANDLE file = CreateFileW(fresh.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
	if (file == INVALID_HANDLE_VALUE)
		throw std::runtime_error("cannot write to " + path_u8(path.parent_path()));
	DWORD written = 0;
	bool ok = WriteFile(file, data.data(), (DWORD)data.size(), &written, nullptr) && written == data.size() &&
		  FlushFileBuffers(file);
	CloseHandle(file);
	if (ok && !MoveFileExW(fresh.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING)) {
		// In use: Windows lets a loaded DLL be renamed, not overwritten.
		DeleteFileW(old.c_str());
		ok = MoveFileExW(path.c_str(), old.c_str(), MOVEFILE_REPLACE_EXISTING) && MoveFileExW(fresh.c_str(), path.c_str(), 0);
		if (!ok && !fs::exists(path))
			MoveFileExW(old.c_str(), path.c_str(), 0); // put the running one back
	}
	if (!ok) {
		DeleteFileW(fresh.c_str());
		throw std::runtime_error("cannot replace " + path_u8(path.filename()));
	}
}

void remove_update_leftovers(const fs::path &folder)
{
	std::error_code ec;
	for (auto &entry : fs::directory_iterator(folder, ec))
		if (entry.path().extension() == L".old" || entry.path().extension() == L".new")
			DeleteFileW(entry.path().c_str());
}

std::string http_get(const std::string &url, size_t limit)
{
	std::wstring wide = widen(url);
	URL_COMPONENTS parts{sizeof(parts)};
	wchar_t host[256] = {}, path[2048] = {};
	parts.lpszHostName = host, parts.dwHostNameLength = 256;
	parts.lpszUrlPath = path, parts.dwUrlPathLength = 2048;
	if (!WinHttpCrackUrl(wide.c_str(), 0, 0, &parts) || parts.nScheme != INTERNET_SCHEME_HTTPS)
		throw HttpError(0, "not an https address");

	std::wstring agent = widen(std::string("Moment-Replays-Plugin/") + VERSION);
	HINTERNET session = WinHttpOpen(agent.c_str(), WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, nullptr, nullptr, 0);
	HINTERNET connect = session ? WinHttpConnect(session, host, parts.nPort, 0) : nullptr;
	HINTERNET request = connect ? WinHttpOpenRequest(connect, L"GET", path, nullptr, nullptr, nullptr, WINHTTP_FLAG_SECURE) : nullptr;
	auto close = [&] {
		for (HINTERNET handle : {request, connect, session})
			if (handle)
				WinHttpCloseHandle(handle);
	};
	std::string body;
	DWORD status = 0, size = sizeof(status);
	bool ok = request && WinHttpSetTimeouts(request, 5000, 5000, 5000, 15000) &&
		  WinHttpSendRequest(request, L"Accept: application/vnd.github+json\r\n", (DWORD)-1, nullptr, 0, 0, 0) &&
		  WinHttpReceiveResponse(request, nullptr) &&
		  WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, nullptr, &status, &size, nullptr);
	while (ok && status == 200) {
		char chunk[16384];
		DWORD got = 0;
		if (!WinHttpReadData(request, chunk, sizeof(chunk), &got)) {
			ok = false;
			break;
		}
		if (!got)
			break;
		body.append(chunk, got);
		if (body.size() > limit) {
			close();
			throw HttpError(0, "the file is too large");
		}
	}
	DWORD error = GetLastError();
	close();
	if (!ok)
		throw HttpError(0, std::format("no answer (error {})", error));
	if (status != 200)
		throw HttpError((int)status, std::format("HTTP {}", status));
	return body;
}

UpdateResult check_for_updates(const fs::path &bin_dir, const fs::path &data_dir)
{
	UpdateResult result;
	result.release_url = std::string("https://github.com/") + UPDATE_REPO + "/releases/latest";
	try {
		json release = json::parse(http_get(std::string("https://api.github.com/repos/") + UPDATE_REPO + "/releases/latest", 1 << 20),
					   nullptr, false);
		if (!release.is_object() || !release.contains("tag_name") || !release["tag_name"].is_string())
			throw std::runtime_error("GitHub returned an invalid release");
		result.latest = release["tag_name"].get<std::string>();
		if (release.contains("html_url") && release["html_url"].is_string())
			result.release_url = release["html_url"].get<std::string>();
		if (!is_newer_version(result.latest, VERSION)) {
			result.state = UpdateResult::Current;
			return result;
		}

		result.state = UpdateResult::Available;
		std::error_code ec;
		if (fs::exists(bin_dir / ".git", ec) || fs::exists(bin_dir / "moment-replays.dev", ec)) {
			result.reason = "update_reason_dev"; // a developer's build folder is never overwritten
			return result;
		}
		if (!is_valid_update_tag(result.latest)) {
			result.reason = "update_reason_tag";
			return result;
		}
		std::string base = std::string("https://github.com/") + UPDATE_REPO + "/releases/download/" + result.latest + "/";
		std::optional<std::map<std::string, std::string>> list;
		try {
			list = parse_update_list(http_get(base + UPDATE_HASHES_FILE, 65536), UPDATE_PLUGIN_FILE);
		} catch (const HttpError &) {
		}
		if (!list) {
			result.reason = "update_reason_list"; // e.g. a release of the script only
			return result;
		}

		std::vector<std::pair<fs::path, std::string>> ready; // target, new content
		for (auto &[name, want] : *list) {
			fs::path target = (name == UPDATE_PLUGIN_FILE ? bin_dir : data_dir) / u8path(name);
			auto have = read_file(target);
			if (have && sha256_hex(*have) == want)
				continue;
			std::string data = http_get(base + name, UPDATE_FILE_MAX);
			if (sha256_hex(data) != want) {
				result.reason = "update_reason_damaged";
				result.detail = name;
				return result;
			}
			if (name == UPDATE_PLUGIN_FILE && (data.size() < 1024 || data.substr(0, 2) != "MZ" ||
							   data.find("obs_module_load") == std::string::npos)) {
				result.reason = "update_reason_list"; // not an OBS plugin: OBS would start without one
				return result;
			}
			if (name == UPDATE_PLUGIN_FILE)
				ready.emplace_back(target, std::move(data)); // the plugin last: the rest is in place by then
			else
				ready.emplace(ready.begin(), target, std::move(data));
		}
		try {
			for (auto &[target, data] : ready)
				replace_file_in_use(target, data);
		} catch (const std::exception &) {
			result.reason = "update_reason_folder";
			return result;
		}
		result.state = UpdateResult::Installed;
	} catch (const HttpError &e) {
		result.state = e.status == 404 ? UpdateResult::NoRelease : UpdateResult::Failed;
		result.reason = e.what();
	} catch (const std::exception &e) {
		result.state = UpdateResult::Failed;
		result.reason = e.what();
	}
	return result;
}

} // namespace mr
