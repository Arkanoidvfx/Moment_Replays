#include "clipwrite.h"
#include "mp4.h"
#include "naming.h"

#include <windows.h>

namespace mr {

static json clip_payload(const fs::path &clip, ClipInfoInputs &inputs)
{
	// The replay buffer starts a clip on a keyframe, so a "35 s" clip is often 1-4 s shorter, and every `t`
	// must count from its real first frame.
	if (auto real = read_mp4_duration(clip))
		inputs.duration = *real;
	return build_moment_metadata(inputs);
}

static bool wait_or_cancel(double seconds, const std::atomic<bool> &cancel)
{
	for (double waited = 0; waited < seconds; waited += 0.05) {
		if (cancel)
			return false;
		Sleep(50);
	}
	return !cancel;
}

// True: stored, or the clip is gone (nothing more to do). False: use the sidecar.
static bool store_in_mp4(const fs::path &clip, ClipInfoInputs &inputs, double retry_s, const std::atomic<bool> &cancel)
{
	double deadline = now_mono() + retry_s;
	for (;;) {
		std::string reason;
		try {
			check_finished_mp4(clip);
			embed_clip_info(clip, encode_clip_info(clip_payload(clip, inputs)));
			logf("Clip info saved inside {}", path_u8(clip.filename()));
			return true;
		} catch (const Mp4Error &error) {
			if (error.kind == Mp4Error::NotFound) {
				log_line("The clip is gone; its info was not written.");
				return true;
			}
			if (error.kind == Mp4Error::Io) {
				logf("Cannot store the clip info inside the clip: {}", error.what());
				return false;
			}
			reason = error.what();
		}
		if (cancel || now_mono() >= deadline || !wait_or_cancel(INFO_RETRY_INTERVAL_S, cancel)) {
			logf("The clip info cannot be stored inside the clip ({}).", reason);
			return false;
		}
	}
}

std::string write_clip_info(const fs::path &clip, ClipInfoInputs inputs, double retry_s, const std::atomic<bool> &cancel)
{
	try {
		std::error_code ec;
		if (casefold(path_u8(clip.extension())) == ".mp4" && store_in_mp4(clip, inputs, retry_s, cancel))
			return fs::exists(clip, ec) ? "mp4" : "";
		if (!fs::exists(clip, ec)) {
			log_line("The clip is gone; its info was not written.");
			return "";
		}
		fs::path path = moment_metadata_path(clip);
		write_file_atomic(path, clip_payload(clip, inputs).dump(2) + "\n");
		logf("Clip info saved at {}", path_u8(path));
		return "json";
	} catch (const std::exception &error) {
		logf("Cannot write the clip info; the clip itself is saved. ({})", error.what());
		return "";
	}
}

bool trim_clip_to_last_seconds(const fs::path &clip, double seconds, const std::atomic<bool> &cancel)
{
	seconds = std::max(seconds, 1.0);
	auto beside = [&](const wchar_t *tag) {
		return ensure_unique_filename(clip.parent_path() / (clip.stem().native() + tag + clip.extension().native()));
	};
	fs::path temp = beside(L".half_tmp"), backup = beside(L".full_tmp");
	std::wstring command = std::format(L"ffmpeg -hide_banner -loglevel error -y -sseof -{:.3f} -i \"{}\" -map 0 -c copy "
					   L"-avoid_negative_ts make_zero \"{}\"",
					   seconds, clip.native(), temp.native());
	logf("Trimming clip to the last {:.1f}s using ffmpeg stream copy...", seconds);

	STARTUPINFOW startup{sizeof(startup)};
	PROCESS_INFORMATION process{};
	if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process)) {
		log_line("Cannot trim clip: ffmpeg was not found in PATH. Keeping the full clip.");
		return false;
	}
	DWORD code = 1;
	while (WaitForSingleObject(process.hProcess, 100) == WAIT_TIMEOUT) {
		if (cancel) { // OBS is closing: the full clip stays
			TerminateProcess(process.hProcess, 1);
			WaitForSingleObject(process.hProcess, 2000);
		}
	}
	GetExitCodeProcess(process.hProcess, &code);
	CloseHandle(process.hThread);
	CloseHandle(process.hProcess);

	std::error_code ec;
	if (code != 0 || !fs::exists(temp, ec) || fs::file_size(temp, ec) == 0) {
		log_line("ffmpeg could not produce a trimmed clip. Keeping the full clip.");
		fs::remove(temp, ec);
		return false;
	}
	fs::rename(clip, backup, ec);
	if (!ec) {
		fs::rename(temp, clip, ec);
		if (ec) {
			std::error_code undo;
			fs::rename(backup, clip, undo);
		} else {
			fs::remove(backup, ec);
			logf("Trimmed clip saved at {}", path_u8(clip));
			return true;
		}
	}
	log_line("Cannot replace the original clip with the trimmed version. Keeping the full clip.");
	fs::remove(temp, ec);
	return false;
}

} // namespace mr
