// What happens to a saved clip on a worker thread: its info is stored, a short clip is cut with ffmpeg.
#pragma once
#include "clipinfo.h"

#include <atomic>

namespace mr {

inline constexpr double INFO_RETRY_S = 10.0; // OBS reports "stopped" before its file writer has finished
inline constexpr double INFO_RETRY_INTERVAL_S = 0.5;

// Stores the clip info inside a finished plain MP4, or else in <clip>.moment.json next to it. Retries for up to
// `retry_s` while the file is still being finished or held; `cancel` ends the wait (OBS is closing). Never throws.
// Returns where the info went: "mp4", "json", or "" (clip gone, or nothing could be written).
std::string write_clip_info(const fs::path &clip, ClipInfoInputs inputs, double retry_s, const std::atomic<bool> &cancel);

// Cuts the clip to its last `seconds` with ffmpeg (stream copy, from PATH), in place. False: the full clip is kept.
bool trim_clip_to_last_seconds(const fs::path &clip, double seconds, const std::atomic<bool> &cancel);

} // namespace mr
