// Clip names, file names and the naming rules (script: clipname_gen.py, script_helpers.py).
#pragma once
#include "util.h"

#include <ctime>
#include <map>
#include <set>
#include <stdexcept>

namespace mr {

enum class NamingMode { CurrentProcess = 0, MostRecordedProcess = 1, CurrentScene = 2 };

inline constexpr const char *FILENAME_PROHIBITED = "/\\:\"<>*?|%";
inline constexpr const char *PATH_PROHIBITED = "\"<>*?|%";
inline constexpr const char *DEFAULT_FILENAME_FORMAT = "%NAME_%d.%m.%Y_%H-%M-%S";

// A list entry that cannot be used; `index` is its position in the list the user edited.
struct RuleError : std::runtime_error {
	enum Kind {
		AliasFormat,
		AliasCharacters,
		AliasPathExists,
		OtherNameCharacters,
		ReplacementFormat,
		ReplacementCharacters
	};
	RuleError(Kind kind, size_t index) : std::runtime_error("invalid naming rule"), kind(kind), index(index) {}
	Kind kind;
	size_t index;
};

struct NamingRules {
	std::vector<std::pair<std::string, std::string>> aliases; // normalized path -> name, in list order
	std::set<std::string> other_names;                        // casefolded
	std::map<std::string, std::string> replacements;          // casefolded exe stem -> name

	// Each throws RuleError for the first bad entry and leaves the rules unchanged.
	void load_aliases(const std::vector<std::string> &list);
	void load_other_names(const std::vector<std::string> &list);
	void load_replacements(const std::vector<std::string> &list);

	std::optional<std::string> alias_for(std::string_view exe_path) const; // the exe itself, then its nearest folder
	std::string app_clip_name(std::string_view exe_path) const;            // alias > .exe fix > exe stem
	std::string folder_name(const std::string &clip_name, NamingMode mode, const std::string &app_folder = OTHER_FOLDER_NAME) const;
};

// The lists as they are saved: trimmed, empty entries dropped, replacements as "Raw > Fixed". Throw RuleError.
std::vector<std::string> normalize_aliases(const std::vector<std::string> &list);
std::vector<std::string> normalize_other_names(const std::vector<std::string> &list);
std::vector<std::string> normalize_replacements(const std::vector<std::string> &list);

std::string normalize_path_key(std::string_view path); // how alias paths are compared: backslashes, no case
std::string exe_stem(std::string_view exe_path);       // "C:\Games\TslGame.exe" -> "TslGame"
std::string exe_basename(std::string_view exe_path);   // file name, lower case; clip info never has full paths

std::string sanitize_clip_component(std::string_view value, std::string_view fallback = FALLBACK_CLIP_NAME);
bool valid_app_folder(std::string_view name);

struct FilenameError : std::runtime_error {
	enum Kind { Format, ProhibitedCharacters }; // script: ValueError, SyntaxError
	explicit FilenameError(Kind kind) : std::runtime_error("invalid file name format"), kind(kind) {}
	Kind kind;
};
// Template with %NAME and strftime codes (the ones in the settings help) -> file name without extension.
std::string gen_filename(std::string_view base_name, std::string_view tmpl, const std::tm &local, int microsecond = 0);
std::string gen_filename_now(std::string_view base_name, std::string_view tmpl);

fs::path ensure_unique_filename(const fs::path &path); // "name (1).mp4", "name (2).mp4"...
bool on_another_drive(const fs::path &first, const fs::path &second);

} // namespace mr
