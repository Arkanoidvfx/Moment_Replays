// Clip info "moment.clip/1" (contract: OBS_Profile_Export/docs/CLIP_INFO.md): the app/scene timeline, marks,
// the clip's end, key presses, and the JSON that goes into the MP4's synopsis tag or a .moment.json file.
#pragma once
#include "settings.h"

#include <deque>
#include <map>

namespace mr {

inline constexpr const char *MOMENT_SCHEMA = "moment.clip/1";
inline constexpr const char *MOMENT_METADATA_SUFFIX = ".moment.json";
inline constexpr size_t TIMELINE_LOG_MAXLEN = 10000;
inline constexpr size_t MARKERS_MAXLEN = 1000;
inline constexpr size_t INFO_TAG_PADDING = 256; // spaces after the JSON, so an editor can rewrite it in place
inline constexpr double REPLAY_END_FRAMES = 3.0; // a clip ends this many frames after its save was requested
inline constexpr double RECORDING_END_FRAMES = 1.5;
inline constexpr double CLIP_CREATED_LAG_S = 0.25; // replay file created minus clip end, until a key save shows the real value
inline constexpr double SAVE_KEY_MAX_LEAD_S = 5.0; // an older save-key press did not cause this file
inline constexpr double CREATED_MAX_AGE_S = 600.0;
inline constexpr const char *ANCHOR_HOTKEY = "plugin hotkey";
inline constexpr const char *ANCHOR_SAVE_KEY = "OBS save key";

// The fixed, ordered set of recorded keys.
const std::vector<std::pair<std::string, int>> &recorded_keys();

struct TimelineEntry {
	double ts; // wall time in the log, seconds from the clip's start once cut
	std::string app, exe, scene;
};
using Timeline = std::deque<TimelineEntry>;

// Keeps change points only, in time order.
void record_timeline_sample(Timeline &log, double ts, const std::string &app, const std::string &exe, const std::string &scene);
std::vector<TimelineEntry> cut_timeline(const Timeline &log, double clip_start, double clip_end);

struct Interval {
	double start;
	std::optional<double> end; // nullopt: still held / still in front
};
struct KeyLog {
	std::vector<Interval> focus;                        // while the game was in front
	std::map<std::string, std::vector<Interval>> keys; // per recorded key
};

struct RecordingPreset {
	std::optional<std::string> encoder, rate_control;
	std::optional<int> cq, width, height;
	std::optional<double> fps;
};

// Everything a clip's info is built from, taken on the UI thread at save time.
struct ClipInfoInputs {
	std::string origin; // replay_buffer | short_clip | recording | alt_recording
	double clip_end = 0;
	double duration = 0; // estimate, replaced by the file's real length when that can be read
	Timeline timeline_log;
	std::vector<double> markers;
	std::string game_scene;
	std::vector<std::pair<int, std::string>> audio_tracks;
	RecordingPreset preset;
	std::string obs_version;
	std::optional<KeyLog> key_log;
};

json build_moment_metadata(const ClipInfoInputs &inputs);
// {key: [down, up, ...]} in ms from the first frame, or null when no game was in front during the clip.
json build_clip_inputs(const KeyLog &key_log, double clip_start, double clip_end);
std::string encode_clip_info(const json &payload); // compact JSON + padding

struct ClipEnd {
	double time;
	std::string anchor; // how it was found
};
// The wall time of the clip's last moment: plugin hotkey request, OBS's own save key, the file's creation time
// minus `created_lag`, and only then the event time. `shift` = the frames OBS keeps after the request.
ClipEnd pick_clip_end(double now, std::optional<double> created_at, std::optional<double> requested_at,
		      const std::vector<double> &save_key_presses, double shift, double created_lag);
// The new created_lag if this save shows one (request known, file time sane).
std::optional<double> learn_created_lag(const ClipEnd &end, std::optional<double> created_at);

fs::path moment_metadata_path(const fs::path &clip);

} // namespace mr
