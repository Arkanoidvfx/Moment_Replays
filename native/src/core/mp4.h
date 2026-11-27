// The two things the plugin does to MP4 files: read the real length, and store clip info in the standard
// `synopsis` tag (moov/udta/meta/ilst/ldes/data). A complete new moov is appended and the old one is retired
// afterwards by its 4-byte type, so the media never moves and an interrupted write leaves a clip that still plays.
#pragma once
#include "util.h"

#include <stdexcept>

namespace mr {

struct Mp4Error : std::runtime_error {
	enum Kind {
		NotFinished, // not a finished plain MP4 (still fragments, another layout): may become one, retry
		Locked,      // someone holds the file: retry
		NotFound,    // the clip is gone
		Io,          // full disk and the like: no retry
	};
	Mp4Error(Kind kind, const std::string &what) : std::runtime_error(what), kind(kind) {}
	Kind kind;
};

std::optional<double> read_mp4_duration(const fs::path &path); // seconds from moov/mvhd; nullopt for anything else
void check_finished_mp4(const fs::path &path);                  // throws Mp4Error
void embed_clip_info(const fs::path &path, std::string_view info); // throws Mp4Error; the clip is left as it was on error
std::optional<std::string> read_clip_info(const fs::path &path);   // the synopsis tag as stored, padding included

} // namespace mr
