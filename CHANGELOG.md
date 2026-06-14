# Changelog

All notable changes to Moment Replays are documented here.

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
