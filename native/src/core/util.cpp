#include "util.h"

#include <windows.h>
#include <bcrypt.h>
#include <chrono>
#include <fstream>
#include <stdexcept>

namespace mr {

std::function<void(const std::string &)> log_sink;

void log_line(const std::string &text)
{
	if (log_sink)
		log_sink(text);
}

std::wstring widen(std::string_view text)
{
	if (text.empty())
		return {};
	int size = MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), nullptr, 0);
	std::wstring out(size, L'\0');
	MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), out.data(), size);
	return out;
}

std::string narrow(std::wstring_view text)
{
	if (text.empty())
		return {};
	int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), (int)text.size(), nullptr, 0, nullptr, nullptr);
	std::string out(size, '\0');
	WideCharToMultiByte(CP_UTF8, 0, text.data(), (int)text.size(), out.data(), size, nullptr, nullptr);
	return out;
}

fs::path u8path(std::string_view text)
{
	return fs::path(widen(text));
}

std::string path_u8(const fs::path &path)
{
	return narrow(path.native());
}

std::string trim(std::string_view text)
{
	const char *space = " \t\r\n\f\v";
	size_t first = text.find_first_not_of(space);
	if (first == std::string_view::npos)
		return {};
	return std::string(text.substr(first, text.find_last_not_of(space) - first + 1));
}

std::string casefold(std::string_view text)
{
	std::wstring wide = widen(text);
	if (!wide.empty())
		CharLowerBuffW(wide.data(), (DWORD)wide.size());
	return narrow(wide);
}

bool contains_any(std::string_view text, std::string_view chars)
{
	return text.find_first_of(chars) != std::string_view::npos;
}

double now_wall()
{
	using namespace std::chrono;
	return duration<double>(system_clock::now().time_since_epoch()).count();
}

double now_mono()
{
	using namespace std::chrono;
	return duration<double>(steady_clock::now().time_since_epoch()).count();
}

std::optional<std::string> read_file(const fs::path &path)
{
	std::ifstream in(path, std::ios::binary);
	if (!in)
		return std::nullopt;
	return std::string(std::istreambuf_iterator<char>(in), {});
}

void write_file_atomic(const fs::path &path, std::string_view data)
{
	fs::path temp = path.parent_path() / (L"." + path.filename().native() + L".tmp");
	HANDLE file = CreateFileW(temp.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
	if (file == INVALID_HANDLE_VALUE)
		throw std::runtime_error("cannot create " + path_u8(temp));
	DWORD written = 0;
	bool ok = WriteFile(file, data.data(), (DWORD)data.size(), &written, nullptr) && written == data.size() &&
		  FlushFileBuffers(file);
	CloseHandle(file);
	if (!ok || !MoveFileExW(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING)) {
		DeleteFileW(temp.c_str());
		throw std::runtime_error("cannot write " + path_u8(path));
	}
}

std::string sha256_hex(std::string_view data)
{
	unsigned char hash[32] = {};
	if (BCryptHash(BCRYPT_SHA256_ALG_HANDLE, nullptr, 0, (PUCHAR)data.data(), (ULONG)data.size(), hash, sizeof(hash)) != 0)
		throw std::runtime_error("SHA-256 failed");
	std::string out;
	for (unsigned char byte : hash)
		out += std::format("{:02x}", byte);
	return out;
}

} // namespace mr
