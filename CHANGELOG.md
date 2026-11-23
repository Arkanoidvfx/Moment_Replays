# Changelog

All notable changes to Moment Replays are documented here.

## v1.7
- **Clip info inside the MP4** — the game, timeline, markers, audio tracks and encoder
  settings (schema `moment.clip/1`) are now stored in the clip itself, in its standard
  `synopsis` tag, instead of a separate file. The media data is never moved, and a write
  that is cut off or fails leaves the clip playing as before. Anything that isn't a
  finished plain MP4 still gets `<clip>.moment.json`, as in 1.6. Recordings are handled
  after OBS has finished writing the file (up to 10 s). Toggle: *Store clip info inside
  the clip* (on by default).
- **Accurate clip times** — a clip now ends when its save was *requested*, not when OBS
  reported it saved (0.2–0.4 s later with NVENC, more with x264 lookahead), so `F8` marks
  no longer sit too early. The request time comes from the script's own hotkeys, OBS's
  *Save Replay* key, or the new file's creation time; recordings use the stop request.
- **Key presses (opt-in, off by default)** — the press times of a fixed set of game keys
  and mouse buttons, recorded only while a game is the window in front and stored inside
  the clip for Moment Player. See the README for exactly what and when.

## v1.6
- **Auto scene (Game / Desktop)** — optional replacement for an Advanced Scene
  Switcher macro. Shows the `Game` scene once the `Game Capture` source
  (game capture, *any fullscreen* mode) has hooked the fullscreen foreground
  game, and goes back to `Desktop` on unhook or ~1.5 s after the game loses
  focus/fullscreen. The capture is kept hookable while `Desktop` is on air, so
  the switch never shows black frames. Off by default; it only runs when the
  setting is on **and** both scenes and the source exist. Existing settings
  files are migrated with it **off** (settings schema 6).
  - **Black-capture fallback:** a game that hooks but delivers only black
    frames (anti-cheat, HDR, hybrid GPUs, swapchain recreate after alt-tab)
    is detected from a tiny GPU readback of the capture once per second. Black
    for ~2 s on `Game` → back to `Desktop` (Display Capture still shows the
    game), one automatic re-hook, and a 60 s per-game cooldown so scenes can't
    flap. `Game` is only entered once the capture shows a non-black frame, so a
    black loading screen just delays it.
  - **Another OBS running:** only one OBS can hold a game's hook. While any
    other `obs64.exe` runs (checked every ~2.5 s, read-only), auto scene
    releases the game capture so it unhooks, leaves `Game` for `Desktop` and
    never enters `Game`; it resumes on its own once that OBS exits.
- **`.moment.json` metadata** next to every saved clip and recording (replay
  buffer, short clip, alternative folder, recordings, alternative recordings):
  the game, an app/scene timeline, markers, recorded audio tracks and the
  encoder preset — for Moment Player. Written atomically; a metadata error
  never affects the clip. Contains no absolute paths or window titles.
  Toggle: *Save .moment.json next to clips* (on by default).
- **Mark moment** hotkey (default `F8`) — drops a marker; on save, markers
  inside the clip become annotations. Plays a short blip of the success sound.
- **Open last saved video** now defaults to `Ctrl+Alt+F10` (only when it was
  never bound before).

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
