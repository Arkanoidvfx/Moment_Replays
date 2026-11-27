// Notification sounds at the volume from the settings. Scaled copies live in memory: no temp files.
#pragma once
#include "util.h"

namespace mr {

// A 16-bit PCM WAV with the volume scaled to `percent`. nullopt for anything that is not integer PCM.
std::optional<std::string> scale_wav(std::string_view wav, int percent);

void play_sound(const std::string &path, int percent); // async; 0 = silent, 100 = the file as is
void stop_sound();
// Tests and throwaway OBS runs: nothing is ever played (also set by the MOMENT_REPLAYS_MUTE environment variable).
extern bool sounds_muted;

} // namespace mr
