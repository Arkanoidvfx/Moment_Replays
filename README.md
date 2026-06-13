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
- **Alternative save folder** — a hotkey that saves the next clip to a separate folder.
- **Hard links** — optionally mirror each clip into a links folder (same drive).
- **Bilingual UI** — English / Russian, switchable in the script settings.
- **Update checks** against GitHub releases.

## Requirements

- **OBS Studio** with Python scripting enabled (works across recent versions;
  the OBS 31+ config layout is handled).
- **Windows** — the script relies on Win32 APIs and `winsound`.
- **ffmpeg** available in `PATH` — only required for the *short clip* feature;
  everything else works without it.

## Installation

1. Download `arkanoid_replays.py` together with the bundled `*.wav` sound files
   (keep them in the same folder).
2. In OBS: **Tools → Scripts**.
3. On the **Python Settings** tab, point OBS to a Python install if prompted.
4. On the **Scripts** tab, click **+** and select `arkanoid_replays.py`.

## Hotkeys

The script works with OBS's normal **Save Replay** action — naming, sorting, and
notifications are applied automatically whenever a replay is saved.

It also registers two extra actions, bindable under **Settings → Hotkeys**:

- **Save short clip** — saves a replay trimmed to the last *N%* of the buffer.
- **Save buffer (alternative folder)** — saves the next clip to the alternative folder.

Suggested defaults: `Ctrl+F10` for the short clip and `Alt+F10` for the
alternative folder — change them freely in OBS hotkey settings.

## Settings

- **Clip paths** — base folder (defaults to the OBS recording path), alternative
  folder, short-clip length, and hard links.
- **Clip naming** — naming mode and the file-name template (`strftime` tokens + `%NAME`).
- **Sounds** — enable/disable and pick a `.wav` file for each event.
- **Naming rules** — path-specific names, `.exe` name fixes, and the `Other` folder list.
- **Updates** — manual update check and a button to open the latest release.

Bundled sounds are pre-selected for convenience; replace them with your own
`.wav` files or turn notifications off entirely.

## License

[AGPL-3.0](LICENSE) © 2025 Moment

---

## Кратко (RU)

Скрипт для OBS Studio (только Windows): автоматически переименовывает и
раскладывает клипы replay-буфера по папкам с именем активного приложения или
сцены. Правила имён по пути/`.exe`, папка `Other`, звуковые уведомления,
короткие клипы (последние N% буфера через ffmpeg), hard links, интерфейс EN/RU
и проверка обновлений. Звуки идут в комплекте — их можно заменить или отключить.
Для коротких клипов нужен `ffmpeg` в `PATH`.
