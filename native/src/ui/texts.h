// UI texts. The English text is the key: T("Clips folder") gives it in the chosen language, or as it is.
// Other languages come from data/locale/<code>.json ({"English text": "translation"}).
#pragma once
#include "core/util.h"

#include <QString>

namespace mr {

const std::vector<std::pair<std::string, std::string>> &languages(); // code, own name; the codes are saved: never rename
void load_language(const std::string &code, const fs::path &data_dir);
QString T(const char *english);
std::string hotkey_description(const std::string &name); // "[Moment Replays] Save short clip", in the loaded language
const char *hotkey_title(const std::string &name);       // the English text

} // namespace mr
