#include "texts.h"
#include "core/settings.h"

#include <map>
#include <mutex>

namespace mr {

static std::mutex mutex;
static std::map<std::string, std::string> table;
static std::string loaded = "en";

const std::vector<std::pair<std::string, std::string>> &languages()
{
	static const std::vector<std::pair<std::string, std::string>> list = {
		{"en", "English"},
		{"de", "Deutsch"},
		{"es", "Español"},
		{"fr", "Français"},
		{"it", "Italiano"},
		{"nl", "Nederlands"},
		{"pl", "Polski"},
		{"pt-PT", "Português (Portugal)"},
		{"ru", "Русский"},
		{"uk", "Українська"},
		{"zh-CN", "简体中文（普通话）"},
		{"zh-HK", "廣東話（繁體）"},
		{"hi", "हिन्दी"},
		{"ja", "日本語"},
	};
	return list;
}

void load_language(const std::string &code, const fs::path &data_dir)
{
	std::lock_guard lock(mutex);
	if (code == loaded)
		return;
	table.clear();
	loaded = code;
	if (code == "en")
		return;
	auto text = read_file(data_dir / "locale" / (code + ".json"));
	json parsed = text ? json::parse(*text, nullptr, false) : json();
	if (!parsed.is_object())
		return; // an unknown code or a missing file reads as English
	for (auto &[english, translated] : parsed.items())
		if (translated.is_string() && !translated.get<std::string>().empty())
			table[english] = translated.get<std::string>();
}

static std::string lookup(const char *english)
{
	std::lock_guard lock(mutex);
	auto found = table.find(english);
	return found == table.end() ? std::string(english) : found->second;
}

QString T(const char *english)
{
	return QString::fromStdString(lookup(english));
}

const char *hotkey_title(const std::string &name)
{
	if (name == "save_buffer_half")
		return "Save short clip";
	if (name == "save_buffer_override_folder")
		return "Save to the second folder";
	if (name == "open_last_video")
		return "Open last saved video";
	if (name == "record_alternative_folder")
		return "Start or stop recording into the recordings folder";
	return "Mark moment";
}

std::string hotkey_description(const std::string &name)
{
	// The prefix stays in every language: the installer tells users to filter the hotkey list by it.
	return "[Moment Replays] " + lookup(hotkey_title(name));
}

} // namespace mr
