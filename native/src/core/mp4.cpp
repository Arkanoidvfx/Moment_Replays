#include "mp4.h"

#include <windows.h>
#include <cstring>

namespace mr {
namespace {

uint32_t be32(const unsigned char *p)
{
	return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}
uint64_t be64(const unsigned char *p)
{
	return (uint64_t)be32(p) << 32 | be32(p + 4);
}
std::string put32(uint32_t value)
{
	return {(char)(value >> 24), (char)(value >> 16), (char)(value >> 8), (char)value};
}

struct File {
	HANDLE handle = INVALID_HANDLE_VALUE;
	File(const fs::path &path, bool write)
	{
		handle = CreateFileW(path.c_str(), GENERIC_READ | (write ? GENERIC_WRITE : 0),
				     write ? FILE_SHARE_READ : FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
				     OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
		if (handle != INVALID_HANDLE_VALUE)
			return;
		DWORD error = GetLastError();
		if (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND)
			throw Mp4Error(Mp4Error::NotFound, "file not found");
		if (error == ERROR_SHARING_VIOLATION || error == ERROR_ACCESS_DENIED || error == ERROR_LOCK_VIOLATION)
			throw Mp4Error(Mp4Error::Locked, "the file is in use");
		throw Mp4Error(Mp4Error::Io, std::format("cannot open the file (error {})", error));
	}
	~File()
	{
		if (handle != INVALID_HANDLE_VALUE)
			CloseHandle(handle);
	}
	uint64_t size() const
	{
		LARGE_INTEGER value{};
		GetFileSizeEx(handle, &value);
		return (uint64_t)value.QuadPart;
	}
	void seek(uint64_t pos) const
	{
		LARGE_INTEGER value;
		value.QuadPart = (LONGLONG)pos;
		SetFilePointerEx(handle, value, nullptr, FILE_BEGIN);
	}
	// Reads up to `size` bytes at `pos`; fewer at the end of the file.
	std::string read(uint64_t pos, size_t size) const
	{
		seek(pos);
		std::string out(size, '\0');
		size_t done = 0;
		while (done < size) {
			DWORD got = 0;
			if (!ReadFile(handle, out.data() + done, (DWORD)(size - done), &got, nullptr) || !got)
				break;
			done += got;
		}
		out.resize(done);
		return out;
	}
	void write(uint64_t pos, std::string_view data) const
	{
		seek(pos);
		size_t done = 0;
		while (done < data.size()) {
			DWORD put = 0;
			if (!WriteFile(handle, data.data() + done, (DWORD)(data.size() - done), &put, nullptr) || !put)
				throw Mp4Error(Mp4Error::Io, std::format("short write (error {})", GetLastError()));
			done += put;
		}
	}
	void truncate(uint64_t size) const
	{
		seek(size);
		SetEndOfFile(handle);
	}
};

struct Box {
	std::string kind;
	uint64_t start, size, header;
};

// (payload start, box end) of the first `kind` box between start and end.
std::optional<std::pair<uint64_t, uint64_t>> find_box(const File &file, uint64_t start, uint64_t end, const char *kind)
{
	uint64_t pos = start;
	while (pos + 8 <= end) {
		std::string head = file.read(pos, 16);
		if (head.size() < 8)
			return std::nullopt;
		auto *p = (const unsigned char *)head.data();
		uint64_t size = be32(p), payload = pos + 8;
		if (size == 1) { // 64-bit size
			if (head.size() < 16)
				return std::nullopt;
			size = be64(p + 8);
			payload += 8;
		} else if (size == 0) { // runs to the end
			size = end - pos;
		}
		if (size < payload - pos)
			return std::nullopt;
		if (!memcmp(p + 4, kind, 4))
			return std::pair{payload, std::min(pos + size, end)};
		pos += size;
	}
	return std::nullopt;
}

// Every top-level box; throws unless they fill the file exactly.
std::vector<Box> top_boxes(const File &file)
{
	std::vector<Box> out;
	uint64_t end = file.size(), pos = 0;
	while (pos < end) {
		std::string head = file.read(pos, 16);
		if (head.size() < 8)
			throw Mp4Error(Mp4Error::NotFinished, "truncated box");
		auto *p = (const unsigned char *)head.data();
		uint64_t size = be32(p), header = 8;
		if (size == 1 && head.size() == 16) {
			size = be64(p + 8);
			header = 16;
		}
		if (size < header || pos + size > end) // includes size 0 ("to the end"): nothing may follow it
			throw Mp4Error(Mp4Error::NotFinished, "open-ended or truncated box");
		out.push_back({head.substr(4, 4), pos, size, header});
		pos += size;
	}
	return out;
}

// The only moov of a finished, unfragmented MP4.
Box finished_moov(const File &file)
{
	auto boxes = top_boxes(file);
	const Box *moov = nullptr;
	int moovs = 0;
	bool mdat = false, moof = false;
	for (auto &box : boxes) {
		if (box.kind == "moov") {
			moov = &box;
			moovs++;
		}
		mdat |= box.kind == "mdat";
		moof |= box.kind == "moof"; // OBS writes a recording as fragments and turns it into a plain MP4 at the end
	}
	if (boxes.empty() || boxes[0].kind != "ftyp" || moovs != 1 || !mdat || moof || moov->header != 8)
		throw Mp4Error(Mp4Error::NotFinished, "not a finished plain MP4");
	return *moov;
}

std::string make_box(std::string_view kind, std::string_view body)
{
	return put32((uint32_t)body.size() + 8) + std::string(kind) + std::string(body);
}

// (kind, whole box) of every child; throws unless they fill `data` exactly.
std::vector<std::pair<std::string, std::string>> children(std::string_view data)
{
	std::vector<std::pair<std::string, std::string>> out;
	size_t pos = 0;
	while (pos < data.size()) {
		if (pos + 8 > data.size())
			throw Mp4Error(Mp4Error::NotFinished, "truncated child box");
		uint32_t size = be32((const unsigned char *)data.data() + pos);
		if (size < 8 || pos + size > data.size())
			throw Mp4Error(Mp4Error::NotFinished, "bad child box");
		out.emplace_back(std::string(data.substr(pos + 4, 4)), std::string(data.substr(pos, size)));
		pos += size;
	}
	return out;
}

const std::string META_HDLR = put32(33) + "hdlr" + std::string(8, '\0') + "mdirappl" + std::string(9, '\0');

// `body` with `leaf` at the end of the nested box `path`, replacing the same kind of leaf; parents are created.
std::string put_leaf(std::string_view body, const std::vector<std::string> &path, size_t depth, const std::string &leaf)
{
	auto kids = children(body);
	std::string out;
	if (depth == path.size()) {
		for (auto &[kind, box] : kids)
			if (kind != leaf.substr(4, 4))
				out += box;
		return out + leaf;
	}
	const std::string &kind = path[depth];
	size_t at = 0;
	while (at < kids.size() && kids[at].first != kind)
		at++;
	if (at == kids.size())
		kids.emplace_back(kind, make_box(kind, kind == "meta" ? std::string(4, '\0') + META_HDLR : std::string()));
	const std::string &box = kids[at].second;
	size_t head = 8;
	if (kind == "meta") { // a full box: 4 bytes of version and flags before its children
		head = 12;
		if (box.size() < 20 || box.substr(16, 4) != "hdlr")
			throw Mp4Error(Mp4Error::NotFinished, "unexpected meta box");
	}
	kids[at].second = make_box(kind, box.substr(8, head - 8) + put_leaf(std::string_view(box).substr(head), path, depth + 1, leaf));
	for (auto &[k, b] : kids)
		out += b;
	return out;
}

} // namespace

std::optional<double> read_mp4_duration(const fs::path &path)
{
	try {
		File file(path, false);
		auto moov = find_box(file, 0, file.size(), "moov");
		if (!moov)
			return std::nullopt;
		auto mvhd = find_box(file, moov->first, moov->second, "mvhd");
		if (!mvhd)
			return std::nullopt;
		std::string head = file.read(mvhd->first, 32);
		if (head.empty())
			return std::nullopt;
		auto *p = (const unsigned char *)head.data();
		uint64_t timescale, duration;
		if (p[0] == 1) { // version 1: 64-bit times
			if (head.size() < 32)
				return std::nullopt;
			timescale = be32(p + 20);
			duration = be64(p + 24);
		} else {
			if (head.size() < 20)
				return std::nullopt;
			timescale = be32(p + 12);
			duration = be32(p + 16);
		}
		if (!timescale || !duration)
			return std::nullopt;
		return (double)duration / (double)timescale;
	} catch (const Mp4Error &) {
		return std::nullopt;
	}
}

void check_finished_mp4(const fs::path &path)
{
	File file(path, false);
	finished_moov(file);
}

void embed_clip_info(const fs::path &path, std::string_view info)
{
	File file(path, true);
	FILETIME accessed{}, modified{};
	GetFileTime(file.handle, nullptr, &accessed, &modified);

	Box old = finished_moov(file);
	std::string moov = file.read(old.start, (size_t)old.size);
	if (moov.size() != old.size)
		throw Mp4Error(Mp4Error::NotFinished, "truncated moov");
	std::string leaf = make_box("ldes", make_box("data", put32(1) + put32(0) + std::string(info)));
	std::string new_moov = make_box("moov", put_leaf(std::string_view(moov).substr(8), {"udta", "meta", "ilst"}, 0, leaf));

	uint64_t end = file.size();
	try {
		file.write(end, new_moov);
		if (!FlushFileBuffers(file.handle)) // the new index must be on disk before the old one is retired
			throw Mp4Error(Mp4Error::Io, "cannot flush the clip");
	} catch (...) {
		file.truncate(end);
		throw;
	}
	file.write(old.start + 4, "free");
	SetFileTime(file.handle, nullptr, &accessed, &modified); // players sort by date
}

std::optional<std::string> read_clip_info(const fs::path &path)
{
	try {
		File file(path, false);
		auto found = find_box(file, 0, file.size(), "moov");
		for (const char *kind : {"udta", "meta", "ilst", "ldes", "data"}) {
			if (!found)
				return std::nullopt;
			uint64_t start = found->first + (!strcmp(kind, "ilst") ? 4 : 0); // meta is a full box
			found = find_box(file, start, found->second, kind);
		}
		if (!found || found->second - found->first < 8)
			return std::nullopt;
		return file.read(found->first + 8, (size_t)(found->second - found->first - 8));
	} catch (const Mp4Error &) {
		return std::nullopt;
	}
}

} // namespace mr
