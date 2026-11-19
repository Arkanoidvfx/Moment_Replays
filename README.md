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
- **Moment metadata** — a `<clip>.moment.json` next to each clip/recording with
  the game, an app/scene timeline, your markers, audio tracks and encoder settings
  (read by Moment Player).
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
  that contains the moment lists it in its `.moment.json`.

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
  `auto_scene_desktop`, `auto_scene_game_source`) and *Save .moment.json next to clips*.
  Apps listed in the `Other` folder list never count as games.
- **Sounds** — enable/disable and pick a `.wav` file for each event.
- **Naming rules** — path-specific names, `.exe` name fixes, and the `Other` folder list.
- **Updates** — manual update check and a button to open the latest release.

Bundled sounds are pre-selected for convenience; replace them with your own
`.wav` files or turn notifications off entirely.

## Clip metadata (`.moment.json`)

Written next to the final clip as `<clip basename>.moment.json` (schema
`moment.clip/1`). `t` values are seconds from the clip start (±1 s: the app
timeline is sampled once per second).

```json
{"schema":"moment.clip/1","origin":"replay_buffer","saved_at":"2026-11-19T21:04:05+01:00","duration_s":35.0,
 "game":{"name":"Deadlock","exe":"deadlock.exe","captured_via":"game_capture"},
 "timeline":[{"t":0.0,"app":"Deadlock","scene":"Game"}],
 "annotations":[{"type":"marker","t":12.4,"label":"mark"}],
 "audio_tracks":[{"track":1,"name":"Mix"}],
 "recording_preset":{"encoder":"obs_nvenc_h264_tex","rate_control":"CQP","cq":23,"width":1920,"height":1080,"fps":30},
 "obs_version":"33.0.1","writer":"Moment Replays 1.6"}
```

`origin` is `replay_buffer`, `short_clip`, `recording` or `alt_recording`.
`recording_preset` fields are `null` when OBS doesn't report them (`cq` is only
set for CQP/CRF/ICQ rate control). Recordings that were already running when the
script loaded get no metadata (their start time is unknown).

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
С 1.6: автопереключение сцен Game/Desktop (по умолчанию выключено), файл
`.moment.json` рядом с каждым клипом для Moment Player и хоткей «Отметить
момент» (`F8`).
Для коротких клипов нужен `ffmpeg` в `PATH`.
