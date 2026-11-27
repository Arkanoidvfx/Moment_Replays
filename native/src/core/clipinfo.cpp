#include "clipinfo.h"

#include <algorithm>
#include <cmath>
#include <ctime>

namespace mr {

const std::vector<std::pair<std::string, int>> &recorded_keys()
{
	static const std::vector<std::pair<std::string, int>> keys = [] {
		std::vector<std::pair<std::string, int>> out;
		for (char c : std::string("12345QWERTASDFGZXCV"))
			out.emplace_back(std::string(1, c), (int)c);
		for (auto &[name, vk] : std::initializer_list<std::pair<const char *, int>>{
			     {"SHIFT", 0x10}, {"CTRL", 0x11}, {"ALT", 0x12}, {"SPACE", 0x20}, {"TAB", 0x09},
			     {"LMB", 0x01},   {"RMB", 0x02},  {"MMB", 0x04}, {"MB4", 0x05},   {"MB5", 0x06}})
			out.emplace_back(name, vk);
		return out;
	}();
	return keys;
}

static double round2(double value)
{
	return std::round(value * 100.0) / 100.0;
}

void record_timeline_sample(Timeline &log, double ts, const std::string &app, const std::string &exe, const std::string &scene)
{
	if (!log.empty()) {
		auto &last = log.back();
		if (last.app == app && last.exe == exe && last.scene == scene)
			return;
		ts = std::max(ts, last.ts); // a scene change and the 1 s sample can race: stay ordered
	}
	log.push_back({ts, app, exe, scene});
	if (log.size() > TIMELINE_LOG_MAXLEN)
		log.pop_front();
}

std::vector<TimelineEntry> cut_timeline(const Timeline &log, double clip_start, double clip_end)
{
	std::vector<TimelineEntry> out;
	for (auto &entry : log) {
		if (entry.ts > clip_end)
			break;
		if (entry.ts <= clip_start)
			out = {{0.0, entry.app, entry.exe, entry.scene}}; // the last change before the clip is its t=0
		else
			out.push_back({round2(entry.ts - clip_start), entry.app, entry.exe, entry.scene});
	}
	return out;
}

static json summarize_game(const std::vector<TimelineEntry> &timeline, double duration, const std::string &game_scene)
{
	// (app, exe) -> seconds on screen, and per scene
	std::vector<std::pair<std::pair<std::string, std::string>, double>> app_time;
	std::map<std::pair<std::string, std::string>, std::vector<std::pair<std::string, double>>> scene_time;
	for (size_t i = 0; i < timeline.size(); i++) {
		double end = i + 1 < timeline.size() ? timeline[i + 1].ts : duration;
		double span = std::max(end - timeline[i].ts, 0.0);
		std::pair<std::string, std::string> key{timeline[i].app, timeline[i].exe};
		auto app = std::find_if(app_time.begin(), app_time.end(), [&](auto &item) { return item.first == key; });
		if (app == app_time.end())
			app_time.emplace_back(key, span);
		else
			app->second += span;
		auto &scenes = scene_time[key];
		auto scene = std::find_if(scenes.begin(), scenes.end(), [&](auto &item) { return item.first == timeline[i].scene; });
		if (scene == scenes.end())
			scenes.emplace_back(timeline[i].scene, span);
		else
			scene->second += span;
	}
	if (app_time.empty())
		return {{"name", FALLBACK_CLIP_NAME}, {"exe", ""}, {"captured_via", "display_capture"}};

	// first of the longest, like Python's max()
	auto longest = [](auto &items) {
		auto best = items.begin();
		for (auto it = items.begin(); it != items.end(); ++it)
			if (it->second > best->second)
				best = it;
		return best;
	};
	auto top = longest(app_time)->first;
	std::string top_scene = longest(scene_time[top])->first;
	bool via_game = !game_scene.empty() && top_scene == game_scene;
	return {{"name", top.first}, {"exe", top.second}, {"captured_via", via_game ? "game_capture" : "display_capture"}};
}

static std::string local_iso(double wall)
{
	std::time_t seconds = (std::time_t)std::floor(wall);
	std::tm local{}, utc{};
	localtime_s(&local, &seconds);
	gmtime_s(&utc, &seconds);
	long offset = (long)std::difftime(_mkgmtime(&local), _mkgmtime(&utc));
	return std::format("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}{}{:02}:{:02}", local.tm_year + 1900, local.tm_mon + 1,
			   local.tm_mday, local.tm_hour, local.tm_min, local.tm_sec, offset < 0 ? '-' : '+',
			   std::abs(offset) / 3600, std::abs(offset) % 3600 / 60);
}

json build_clip_inputs(const KeyLog &key_log, double clip_start, double clip_end)
{
	bool in_front = std::any_of(key_log.focus.begin(), key_log.focus.end(), [&](const Interval &span) {
		return span.start < clip_end && (!span.end || *span.end > clip_start);
	});
	if (!in_front)
		return nullptr;
	long long length_ms = std::llround((clip_end - clip_start) * 1000);
	json inputs = json::object();
	for (auto &[name, vk] : recorded_keys()) {
		(void)vk;
		json times = json::array();
		if (auto found = key_log.keys.find(name); found != key_log.keys.end()) {
			for (auto &press : found->second) {
				double down = std::max(press.start, clip_start);
				double up = press.end ? std::min(*press.end, clip_end) : clip_end;
				if (up > down) {
					times.push_back(std::llround((down - clip_start) * 1000));
					times.push_back(std::min(std::llround((up - clip_start) * 1000), length_ms));
				}
			}
		}
		inputs[name] = times;
	}
	return inputs;
}

template<class T> static json or_null(const std::optional<T> &value)
{
	return value ? json(*value) : json(nullptr);
}

json build_moment_metadata(const ClipInfoInputs &in)
{
	double duration = std::max(in.duration, 0.0);
	double clip_start = in.clip_end - duration;
	auto timeline = cut_timeline(in.timeline_log, clip_start, in.clip_end);

	json payload = json::object();
	payload["schema"] = MOMENT_SCHEMA;
	payload["origin"] = in.origin;
	payload["saved_at"] = local_iso(in.clip_end);
	payload["duration_s"] = round2(duration);
	payload["game"] = summarize_game(timeline, duration, in.game_scene);
	payload["timeline"] = json::array();
	for (auto &entry : timeline)
		payload["timeline"].push_back({{"t", entry.ts}, {"app", entry.app}, {"scene", entry.scene}});
	payload["annotations"] = json::array();
	std::vector<double> markers = in.markers;
	std::sort(markers.begin(), markers.end());
	for (double marker : markers)
		if (clip_start <= marker && marker <= in.clip_end)
			payload["annotations"].push_back({{"type", "marker"}, {"t", round2(marker - clip_start)}, {"label", "mark"}});
	payload["audio_tracks"] = json::array();
	for (auto &[track, name] : in.audio_tracks)
		payload["audio_tracks"].push_back({{"track", track}, {"name", name}});

	json fps = nullptr;
	if (in.preset.fps)
		fps = *in.preset.fps == std::floor(*in.preset.fps) ? json((long long)*in.preset.fps)
								    : json(std::round(*in.preset.fps * 1000.0) / 1000.0);
	payload["recording_preset"] = {{"encoder", or_null(in.preset.encoder)}, {"rate_control", or_null(in.preset.rate_control)},
				       {"cq", or_null(in.preset.cq)},           {"width", or_null(in.preset.width)},
				       {"height", or_null(in.preset.height)},   {"fps", fps}};
	payload["obs_version"] = in.obs_version;
	payload["writer"] = std::string("Moment Replays ") + VERSION;
	if (in.key_log) {
		json inputs = build_clip_inputs(*in.key_log, clip_start, in.clip_end);
		if (!inputs.is_null())
			payload["inputs"] = inputs; // last field of the JSON
	}
	return payload;
}

std::string encode_clip_info(const json &payload)
{
	return payload.dump() + std::string(INFO_TAG_PADDING, ' ');
}

ClipEnd pick_clip_end(double now, std::optional<double> created_at, std::optional<double> requested_at,
		      const std::vector<double> &save_key_presses, double shift, double created_lag)
{
	if (created_at && !(now - CREATED_MAX_AGE_S <= *created_at && *created_at <= now + 1))
		created_at.reset(); // a wrong clock or a file from some other time
	double limit = created_at.value_or(now);
	if (requested_at && limit - 30 <= *requested_at && *requested_at <= limit + 0.1)
		return {*requested_at + shift, ANCHOR_HOTKEY};
	std::optional<double> recent; // the last press wins: OBS overwrites a pending save's time
	for (double press : save_key_presses)
		if (limit - SAVE_KEY_MAX_LEAD_S <= press && press <= limit && (!recent || press > *recent))
			recent = press;
	if (recent)
		return {*recent + shift, ANCHOR_SAVE_KEY};
	if (created_at)
		return {*created_at - created_lag, "file creation time"};
	return {now, "save event"};
}

std::optional<double> learn_created_lag(const ClipEnd &end, std::optional<double> created_at)
{
	if ((end.anchor == ANCHOR_HOTKEY || end.anchor == ANCHOR_SAVE_KEY) && created_at) {
		double lag = *created_at - end.time;
		if (0 < lag && lag <= SAVE_KEY_MAX_LEAD_S)
			return lag;
	}
	return std::nullopt;
}

fs::path moment_metadata_path(const fs::path &clip)
{
	return clip.parent_path() / (clip.stem().native() + widen(MOMENT_METADATA_SUFFIX));
}

} // namespace mr
