# Changelog

All notable changes to Moment Replays are documented here.

## v1.5
- New **Alternative recording** hotkey: records a full OBS recording (not the
  replay buffer) directly into a separate *Recording folder* chosen in the script
  settings — on any drive. Works by switching the OBS recording path only for that
  recording and restoring it immediately, so normal recordings are never affected
  (no file moving, so OBS remux/auto-split keep working). Bind it next to your
  normal record key (e.g. `Alt+F9`). Requires **Alternative recording modes** enabled.

## v1.4
- Renamed the script file `arkanoid_replays.py` → `Moment_Replays.py`. Existing
  settings are preserved: the settings file is now `Moment_Replays.settings.json`,
  and the old `arkanoid_replays.settings.json` is still read as a fallback.
- Repository slimmed down for distribution (internal tooling kept out of the
  published tree).

## v1.3
- **Open last saved video** now cooperates with in-progress saves: pressing the
  hotkey while a replay is still being saved (or a short clip is still being
  trimmed) waits for the save to finish and opens the just-created clip instead
  of the previous one. Non-blocking — it never freezes OBS — with a safety
  timeout so the request can't get stuck.

## v1.2
- **Cross-platform safety:** the script no longer hard-crashes on import on
  non-Windows OBS. It loads but disables its active features with a clear log
  message (the add-on is Windows-only by design).
- **Tests:** added a standard-library unit-test suite under `tests/`
  (run with `python -m unittest discover -s tests`).
- **Cleanup:** removed dead "force naming mode" replay-buffer machinery and
  unused hotkey ids; replaced a magic property name; hardened the
  *Open last saved video* file selection against a file-vanish race.

## v1.1
- **Open last saved video** hotkey — opens the newest of the last saved clip,
  OBS's last recording, or last replay, in your default player. Unbound by default.

## v1.0
- First public release: automatic app/scene-based clip naming, path & `.exe`
  naming rules, `Other`-folder routing, sound notifications, short clips
  (ffmpeg), hard links, EN/RU UI, and GitHub release update checks.
