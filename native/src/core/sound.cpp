#include "sound.h"

#include <windows.h>
#include <mmsystem.h>
#include <cstring>
#include <map>
#include <mutex>

namespace mr {

bool sounds_muted = GetEnvironmentVariableW(L"MOMENT_REPLAYS_MUTE", nullptr, 0) > 0;

static uint32_t le32(const char *p)
{
	uint32_t value;
	memcpy(&value, p, 4);
	return value;
}
static uint16_t le16(const char *p)
{
	uint16_t value;
	memcpy(&value, p, 2);
	return value;
}
template<class T> static void put(std::string &out, T value)
{
	out.append((const char *)&value, sizeof(value));
}

std::optional<std::string> scale_wav(std::string_view wav, int percent)
{
	if (wav.size() < 12 || wav.substr(0, 4) != "RIFF" || wav.substr(8, 4) != "WAVE")
		return std::nullopt;
	uint16_t format = 0, channels = 0, bits = 0;
	uint32_t rate = 0;
	std::string_view data;
	bool has_data = false;
	for (size_t pos = 12; pos + 8 <= wav.size();) {
		std::string_view id = wav.substr(pos, 4);
		size_t size = le32(wav.data() + pos + 4);
		size_t body = pos + 8;
		if (id == "fmt " && size >= 16 && body + 16 <= wav.size()) {
			format = le16(wav.data() + body);
			channels = le16(wav.data() + body + 2);
			rate = le32(wav.data() + body + 4);
			bits = le16(wav.data() + body + 14);
		} else if (id == "data") {
			data = wav.substr(body, std::min(size, wav.size() - body));
			has_data = true;
			break;
		}
		pos = body + size + (size & 1);
	}
	size_t width = (bits + 7) / 8;
	if (!has_data || !channels || (format != 1 && format != 0xFFFE) || width < 1 || width > 4)
		return std::nullopt;

	std::string samples; // 16-bit little-endian
	size_t count = data.size() / width;
	samples.reserve(count * 2);
	for (size_t i = 0; i < count; i++) {
		int value;
		if (width == 1) { // unsigned
			value = ((unsigned char)data[i] - 128) * 256;
		} else { // the two high bytes of each little-endian sample
			const char *p = data.data() + i * width + width - 2;
			value = (int16_t)((unsigned char)p[0] | (unsigned char)p[1] << 8);
		}
		int scaled = value * percent;
		scaled = scaled >= 0 ? scaled / 100 : -((-scaled + 99) / 100); // floor, like Python's //
		put(samples, (int16_t)scaled);
	}

	std::string out = "RIFF";
	put(out, (uint32_t)(36 + samples.size()));
	out += "WAVEfmt ";
	put(out, (uint32_t)16);
	put(out, (uint16_t)1);
	put(out, channels);
	put(out, rate);
	put(out, (uint32_t)(rate * channels * 2));
	put(out, (uint16_t)(channels * 2));
	put(out, (uint16_t)16);
	out += "data";
	put(out, (uint32_t)samples.size());
	return out + samples;
}

void stop_sound()
{
	PlaySoundW(nullptr, nullptr, 0);
}

void play_sound(const std::string &path, int percent)
{
	if (percent <= 0 || path.empty() || sounds_muted)
		return;
	if (percent < 100) {
		// SND_MEMORY | SND_ASYNC needs the buffer to stay alive while it plays: copies are kept for the session.
		static std::mutex mutex;
		static std::map<std::string, std::string> cache;
		std::error_code ec;
		fs::path file = u8path(path);
		auto stamp = fs::last_write_time(file, ec).time_since_epoch().count();
		std::string key = std::format("{}|{}|{}|{}", path, stamp, fs::file_size(file, ec), percent);
		std::lock_guard lock(mutex);
		auto found = cache.find(key);
		if (found == cache.end()) {
			auto wav = read_file(file);
			auto scaled = wav ? scale_wav(*wav, percent) : std::nullopt;
			if (!scaled)
				logf("Cannot change the volume of {}; playing it unchanged.", path);
			found = cache.emplace(key, scaled.value_or(std::string())).first;
		}
		if (!found->second.empty()) {
			PlaySoundW((LPCWSTR)found->second.data(), nullptr, SND_MEMORY | SND_ASYNC | SND_NODEFAULT);
			return;
		}
	}
	PlaySoundW(widen(path).c_str(), nullptr, SND_FILENAME | SND_ASYNC | SND_NODEFAULT);
}

} // namespace mr
