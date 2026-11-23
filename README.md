# Moment Replays

An OBS Studio script for flexible replay-buffer clip management on Windows.
It automatically renames and sorts your saved replay clips — by the app or
scene you were in — and adds path/`.exe` naming rules, sound notifications,
short clips, hard links, and a bilingual (English / Russian) settings UI.

> **Windows only.** The script uses Win32 APIs to detect the active application.

## Features

- **Automatic clip naming** — by the active app at save time, the app active for
  most of the buffer, or the current scene.
- **Per-app/scene folders** — each clip is sorted into a folder named after the app or scene.
- **Naming rules**
  - *Path-specific names*: map an exact `.exe` path or a parent folder to a clip name
    (handy for launchers or duplicate `.exe` names).
  - *Executable name fixes*: e.g. `TslGame > PUBG`, `VALORANT-Win64-Shipping > VALORANT`.
  - *Other folder*: route chosen apps (browsers, chat apps, …) into a single `Other` folder.
- **Sound notifications** on clip save success/failure and on recording start/stop.
- **Short clips** — a hotkey that keeps only the last *N%* of the replay buffer
  (trimmed losslessly with ffmpeg stream-copy).
- **Alternative save folder** — a hotkey that saves the next replay clip to a separate folder.
- **Alternative recording** — a hotkey that records a full OBS recording (not the replay buffer)
  straight into a separate folder of your choice, on any drive.
- **Hard links** — optionally mirror each clip into a links folder (same drive).
- **Auto scene (Game / Desktop)** — optional: switches to a `Game` scene once a
  `Game Capture` source has hooked your fullscreen game, and back to `Desktop`
  when you leave it. Off unless enabled and both scenes and the source exist.
- **Clip info** — the game, an app/scene timeline, your markers, audio tracks and
  encoder settings, stored inside each MP4 clip/recording for Moment Player (or in a
  `<clip>.moment.json` next to it when that isn't possible).
- **Key presses (opt-in)** — records when you press a fixed set of game keys and
  mouse buttons while your game is in front, so Moment Player can show them over the
  clip. Off by default; see below.
- **Mark moment** — a hotkey that marks the current moment; the next saved clip
  carries it as an annotation.
- **Bilingual UI** — English / Russian, switchable in the script settings.
- **Update checks** against GitHub releases.

## Requirements

- **OBS Studio** with Python scripting enabled (works across recent versions;
  the OBS 31+ config layout is handled).
- **Windows** — the script relies on Win32 APIs and `winsound`.
- **ffmpeg** available in `PATH` — only required for the *short clip* feature;
  everything else works without it.

## Installation

1. Download `Moment_Replays.py` together with the bundled `*.wav` sound files
   (keep them in the same folder).
2. In OBS: **Tools → Scripts**.
3. On the **Python Settings** tab, point OBS to a Python install if prompted.
4. On the **Scripts** tab, click **+** and select `Moment_Replays.py`.

## Hotkeys

The script works with OBS's normal **Save Replay** action — naming, sorting, and
notifications are applied automatically whenever a replay is saved.

It also registers five extra actions, bindable under **Settings → Hotkeys**:

- **Save short clip** — saves a replay trimmed to the last *N%* of the buffer.
- **Save buffer (alternative folder)** — saves the next replay clip to the alternative folder.
- **Open last saved video** — opens the most recently saved clip or recording in your default player.
- **Start/stop recording (alternative folder)** — records a full OBS recording into the
  configured *Recording folder* instead of the OBS default path.
- **Mark moment** — marks "this was cool" while you play; the next saved clip
  that contains the moment lists it in its clip info.

Defaults (applied only if the action was never bound): `Ctrl+F10` short clip,
`Alt+F10` alternative folder, `Ctrl+Alt+F10` open last video, `F8` mark moment.
Alternative recording has no default — bind it yourself (e.g. `Alt+F9`, next to
your normal record key). Change them freely in OBS hotkey settings.

> The two *alternative* hotkeys and the *Recording folder* only work when
> **Alternative recording modes** is enabled in the script settings.

## Settings

- **Clip paths** — base folder (defaults to the OBS recording path), alternative
  folder, short-clip length, and hard links.
- **Clip naming** — naming mode and the file-name template (`strftime` tokens + `%NAME`).
- **Moments** — *Auto-switch Game / Desktop scenes* (needs scenes `Game` and
  `Desktop` and a game capture source `Game Capture` in *any fullscreen* mode;
  other names can be set in `Moment_Replays.settings.json` via `auto_scene_game`,
  `auto_scene_desktop`, `auto_scene_game_source`), *Store clip info inside the clip*
  and *Record key presses* (off by default).
  Apps listed in the `Other` folder list never count as games. If the game
  capture hooks but stays black for ~2 s, the script falls back to `Desktop`,
  re-hooks once and keeps that game off `Game` for 60 s, so clips never end up
  black with sound. While another OBS is running, auto scene pauses (releases the
  game capture and stays on `Desktop`) so it never takes that OBS's game hook.
- **Sounds** — enable/disable and pick a `.wav` file for each event.
- **Naming rules** — path-specific names, `.exe` name fixes, and the `Other` folder list.
- **Updates** — manual update check and a button to open the latest release.

Bundled sounds are pre-selected for convenience; replace them with your own
`.wav` files or turn notifications off entirely.

## Clip info (`moment.clip/1`)

Stored inside the MP4 itself, as its standard `synopsis` tag (compact JSON followed by
spaces), so it survives copying, ffmpeg cuts and re-encodes; Explorer does not show it.
Other containers, and files that aren't a finished plain MP4, get the same JSON as
`<clip basename>.moment.json` next to the clip instead. If a recording is still being
finished when OBS reports it stopped, the script waits up to 10 s for it before
falling back.

`t` values are seconds from the clip's first frame and `duration_s` is the clip's real
length, read from the saved file (a replay starts on a keyframe, so it is often a few
seconds shorter than the buffer setting). A clip ends a few frames after its save or
stop was *requested*: the script takes that moment from its own hotkey, from OBS's *Save
Replay* key (the last press before the file was created), or from the new file's creation
time; for recordings, from the stop event. The app timeline is sampled once per second.

```json
{"schema":"moment.clip/1","origin":"replay_buffer","saved_at":"2026-11-19T21:04:05+01:00","duration_s":35.0,
 "game":{"name":"Deadlock","exe":"deadlock.exe","captured_via":"game_capture"},
 "timeline":[{"t":0.0,"app":"Deadlock","scene":"Game"}],
 "annotations":[{"type":"marker","t":12.4,"label":"mark"}],
 "audio_tracks":[{"track":1,"name":"Mix"}],
 "recording_preset":{"encoder":"obs_nvenc_h264_tex","rate_control":"CQP","cq":23,"width":1920,"height":1080,"fps":30},
 "obs_version":"33.0.1","writer":"Moment Replays 1.7"}
```

`origin` is `replay_buffer`, `short_clip`, `recording` or `alt_recording`.
`recording_preset` fields are `null` when OBS doesn't report them (`cq` is only
set for CQP/CRF/ICQ rate control). Recordings that were already running when the
script loaded get no clip info (their start time is unknown).

### Key presses (`inputs`)

With *Record key presses* on, the JSON ends with `"inputs"`: for each recorded key, its
presses in whole milliseconds from the clip's first frame as `[down, up, down, up, ...]`.
A key held at the start begins at 0; one held at the end ends at the clip's length. An
empty list means recorded but not pressed; the field is absent when recording was off or
no game was in front.

- Recorded: `1 2 3 4 5 Q W E R T A S D F G Z X C V SHIFT CTRL ALT SPACE TAB LMB RMB MMB
  MB4 MB5`. Not the whole keyboard, on purpose.
- Only while a replay buffer or recording runs, and only while your game is the window in
  front: it covers its whole monitor (like auto scene's rule) or is the exe your game
  capture has hooked. Anything else in front (Discord, a browser, the desktop, OBS)
  records nothing and counts as all keys released.
- The script only reads key states (about 250 times a second); it hooks nothing and
  touches no other process. Presses stay in memory until a clip is saved, then travel
  inside that clip. They are never logged.
- Limits: text typed in a game's own chat uses some of these keys; a game running as
  administrator hides its keys from OBS; the mouse wheel isn't recorded.

See [CHANGELOG.md](CHANGELOG.md) for the version history.

## License

[AGPL-3.0](LICENSE) © 2025 Moment

---

## Кратко (RU)

Скрипт для OBS Studio (только Windows): автоматически переименовывает и
раскладывает клипы replay-буфера по папкам с именем активного приложения или
сцены. Правила имён по пути/`.exe`, папка `Other`, звуковые уведомления,
короткие клипы (последние N% буфера через ffmpeg), hard links, интерфейс EN/RU
и проверка обновлений. Звуки идут в комплекте — их можно заменить или отключить.
С 1.6: автопереключение сцен Game/Desktop (по умолчанию выключено) и хоткей
«Отметить момент» (`F8`). С 1.7: данные о клипе хранятся внутри самого MP4
(иначе — `.moment.json` рядом), точное время меток и клипов, запись нажатий клавиш
(по умолчанию выключено).
Для коротких клипов нужен `ffmpeg` в `PATH`.
