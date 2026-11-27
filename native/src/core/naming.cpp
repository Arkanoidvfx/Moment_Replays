#include "naming.h"

#include <windows.h>
#include <array>
#include <locale.h>

namespace mr {

static std::pair<std::string, std::string> split_rule(std::string_view value)
{
	size_t at = value.find('>');
	if (at == std::string_view::npos)
		return {};
	return {trim(value.substr(0, at)), trim(value.substr(at + 1))};
}

static std::string expand_vars(const std::string &path)
{
	std::wstring wide = widen(path);
	std::wstring out(ExpandEnvironmentStringsW(wide.c_str(), nullptr, 0), L'\0');
	if (out.empty())
		return path;
	ExpandEnvironmentStringsW(wide.c_str(), out.data(), (DWORD)out.size());
	out.resize(wcslen(out.c_str()));
	return narrow(out);
}

std::string normalize_path_key(std::string_view path)
{
	std::string key = casefold(path);
	for (char &c : key)
		if (c == '/')
			c = '\\';
	while (key.size() > 3 && key.back() == '\\') // keep "c:\"
		key.pop_back();
	return key;
}

std::string exe_stem(std::string_view exe_path)
{
	return path_u8(u8path(exe_path).stem());
}

std::string exe_basename(std::string_view exe_path)
{
	return exe_path.empty() ? std::string() : casefold(path_u8(u8path(exe_path).filename()));
}

// ---- lists ----

static std::vector<std::pair<std::string, std::string>> parse_aliases(const std::vector<std::string> &list)
{
	std::vector<std::pair<std::string, std::string>> out;
	for (size_t i = 0; i < list.size(); i++) {
		auto [path, name] = split_rule(list[i]);
		if (path.empty() || name.empty())
			throw RuleError(RuleError::AliasFormat, i);
		path = expand_vars(path);
		if (contains_any(path, PATH_PROHIBITED) || contains_any(name, FILENAME_PROHIBITED))
			throw RuleError(RuleError::AliasCharacters, i);
		std::string key = normalize_path_key(path);
		for (auto &known : out)
			if (known.first == key)
				throw RuleError(RuleError::AliasPathExists, i);
		out.emplace_back(key, name);
	}
	return out;
}

void NamingRules::load_aliases(const std::vector<std::string> &list)
{
	aliases = parse_aliases(list);
}

void NamingRules::load_other_names(const std::vector<std::string> &list)
{
	std::set<std::string> names;
	for (size_t i = 0; i < list.size(); i++) {
		std::string value = trim(list[i]);
		if (value.empty())
			continue;
		if (contains_any(value, ">\\/:"))
			throw RuleError(RuleError::OtherNameCharacters, i);
		names.insert(casefold(value));
	}
	other_names = std::move(names);
}

void NamingRules::load_replacements(const std::vector<std::string> &list)
{
	std::map<std::string, std::string> out;
	for (size_t i = 0; i < list.size(); i++) {
		if (trim(list[i]).empty())
			continue;
		auto [raw, fixed] = split_rule(list[i]);
		if (raw.empty() || fixed.empty())
			throw RuleError(RuleError::ReplacementFormat, i);
		if (contains_any(raw, FILENAME_PROHIBITED) || contains_any(fixed, FILENAME_PROHIBITED))
			throw RuleError(RuleError::ReplacementCharacters, i);
		out[casefold(raw)] = fixed;
	}
	replacements = std::move(out);
}

std::vector<std::string> normalize_aliases(const std::vector<std::string> &list)
{
	std::vector<std::string> values;
	for (auto &item : list)
		if (std::string value = trim(item); !value.empty())
			values.push_back(value);
	parse_aliases(values);
	return values;
}

std::vector<std::string> normalize_other_names(const std::vector<std::string> &list)
{
	std::vector<std::string> values;
	for (size_t i = 0; i < list.size(); i++) {
		std::string value = trim(list[i]);
		if (value.empty())
			continue;
		if (contains_any(value, ">\\/:"))
			throw RuleError(RuleError::OtherNameCharacters, i);
		values.push_back(value);
	}
	return values;
}

std::vector<std::string> normalize_replacements(const std::vector<std::string> &list)
{
	NamingRules check;
	check.load_replacements(list);
	std::vector<std::string> values;
	for (auto &item : list) {
		if (trim(item).empty())
			continue;
		auto [raw, fixed] = split_rule(item);
		values.push_back(raw + " > " + fixed);
	}
	return values;
}

std::optional<std::string> NamingRules::alias_for(std::string_view exe_path) const
{
	std::string key = normalize_path_key(exe_path);
	while (!key.empty()) {
		for (auto &[path, name] : aliases)
			if (path == key)
				return name;
		size_t slash = key.find_last_of('\\');
		if (slash == std::string::npos)
			break;
		std::string parent = key.substr(0, slash);
		if (parent.size() == 2 && parent[1] == ':')
			parent += '\\'; // "c:" -> "c:\"
		if (parent == key)
			break;
		key = parent;
	}
	return std::nullopt;
}

std::string NamingRules::app_clip_name(std::string_view exe_path) const
{
	if (exe_path.empty())
		return FALLBACK_CLIP_NAME;
	if (auto alias = alias_for(exe_path))
		return *alias;
	std::string stem = exe_stem(exe_path);
	auto found = replacements.find(casefold(stem));
	return found != replacements.end() ? found->second : stem;
}

std::string NamingRules::folder_name(const std::string &clip_name, NamingMode mode, const std::string &app_folder) const
{
	if (mode != NamingMode::CurrentScene && other_names.count(casefold(clip_name)))
		return app_folder;
	return clip_name;
}

// ---- names ----

static bool reserved_device_name(std::string_view text)
{
	static const std::set<std::string> reserved = {"con",  "prn",  "aux",  "nul",  "com1", "com2", "com3", "com4",
						       "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3",
						       "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9", "conin$", "conout$",
						       "com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³"};
	return reserved.count(casefold(trim(text.substr(0, text.find('.'))))) != 0;
}

std::string sanitize_clip_component(std::string_view value, std::string_view fallback)
{
	std::string text = trim(value);
	for (char &c : text)
		if ((unsigned char)c < 0x20 || strchr("<>:\"/\\|?*%", c))
			c = '_';
	while (!text.empty() && (text.back() == ' ' || text.back() == '.'))
		text.pop_back();
	if (text.empty() || reserved_device_name(text))
		return std::string(fallback);
	return text;
}

bool valid_app_folder(std::string_view name)
{
	if (name.empty() || name.back() == '.' || name != trim(name) || contains_any(name, "<>:\"/\\|?*"))
		return false;
	for (unsigned char c : name)
		if (c < 0x20)
			return false;
	return widen(name).size() <= 255 && !reserved_device_name(name);
}

// One strftime code in the "C" locale. The C runtime aborts on a code it does not know, so only known ones reach it.
static std::string format_code(char code, const std::tm &local, int microsecond)
{
	if (code == '%')
		return "%";
	if (code == 'f')
		return std::format("{:06}", microsecond);
	if (code == 'z' || code == 'Z')
		return {}; // as in the script, whose time has no zone: both print nothing
	if (!strchr("aAwdbBmyYHIpMSzZjUW", code))
		throw FilenameError(FilenameError::Format);
	static _locale_t c_locale = _create_locale(LC_ALL, "C");
	wchar_t format[3] = {L'%', (wchar_t)code, 0};
	std::array<wchar_t, 128> out{};
	size_t size = _wcsftime_l(out.data(), out.size(), format, &local, c_locale);
	return narrow(std::wstring_view(out.data(), size));
}

std::string gen_filename(std::string_view base_name, std::string_view tmpl, const std::tm &local, int microsecond)
{
	if (tmpl.empty())
		throw FilenameError(FilenameError::Format);
	std::string text(tmpl);
	for (size_t at = 0; (at = text.find("%NAME", at)) != std::string::npos; at += base_name.size())
		text.replace(at, 5, base_name);

	std::string out;
	for (size_t i = 0; i < text.size(); i++) {
		if (text[i] != '%') {
			out += text[i];
			continue;
		}
		if (++i == text.size())
			throw FilenameError(FilenameError::Format); // a lone % at the end
		out += format_code(text[i], local, microsecond);
	}
	if (contains_any(out, FILENAME_PROHIBITED))
		throw FilenameError(FilenameError::ProhibitedCharacters);
	return out;
}

std::string gen_filename_now(std::string_view base_name, std::string_view tmpl)
{
	SYSTEMTIME st;
	GetLocalTime(&st);
	std::time_t now = std::time(nullptr);
	std::tm local{};
	localtime_s(&local, &now);
	return gen_filename(base_name, tmpl, local, st.wMilliseconds * 1000);
}

fs::path ensure_unique_filename(const fs::path &path)
{
	fs::path candidate = path;
	std::error_code ec;
	for (int counter = 1; fs::exists(candidate, ec); counter++)
		candidate = path.parent_path() /
			    (path.stem().native() + L" (" + std::to_wstring(counter) + L")" + path.extension().native());
	return candidate;
}

bool on_another_drive(const fs::path &first, const fs::path &second)
{
	std::string a = casefold(path_u8(first.root_name())), b = casefold(path_u8(second.root_name()));
	return !a.empty() && !b.empty() && a != b;
}

} // namespace mr
