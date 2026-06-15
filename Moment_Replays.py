#  Moment Replays is an OBS script that allows more flexible replay buffer management:
#  set the clip name depending on the current window, set the file name format, etc.
#  Copyright (C) 2025 Moment
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.

import sys
import ctypes
import re
import json
import traceback
import urllib.error
import urllib.request
import webbrowser
import os
import subprocess
import winsound
from enum import Enum
from threading import Lock
from threading import Thread
from pathlib import Path
from collections import deque
from datetime import datetime
from ctypes import wintypes
from contextlib import suppress
from typing import Any

if __name__ != '__main__':
    import obspython as obs


# -------------------- globals.py --------------------
IS_WINDOWS = sys.platform == "win32"
user32 = ctypes.windll.user32 if IS_WINDOWS else None


class CONSTANTS:
    VERSION = "1.4"
    OBS_VERSION_STRING = obs.obs_get_version_string()
    OBS_VERSION_RE = re.compile(r'(\d+)\.(\d+)\.(\d+)')
    OBS_VERSION = [int(i) for i in OBS_VERSION_RE.match(OBS_VERSION_STRING).groups()]
    CLIPS_FORCE_MODE_LOCK = Lock()
    UPDATE_CHECK_LOCK = Lock()
    FORCED_SAVE_TIMEOUT_MS = 30000
    OPEN_LAST_VIDEO_WAIT_INTERVAL_MS = 250
    FILENAME_PROHIBITED_CHARS = r'/\:"<>*?|%'
    PATH_PROHIBITED_CHARS = r'"<>*?|%'
    DEFAULT_FILENAME_FORMAT = "%NAME_%d.%m.%Y_%H-%M-%S"
    DEFAULT_FALLBACK_CLIP_NAME = "UnknownApp"
    SCRIPT_DIR = Path(__file__).resolve().parent
    LEGACY_PERSONAL_BASE_PATH = Path(r"D:\Shadow Play\OBS")
    DEFAULT_CLIPS_BASE_PATH = Path.home() / "Videos"
    DEFAULT_OVERRIDE_PATH = DEFAULT_CLIPS_BASE_PATH / "Alternative"
    DEFAULT_LINKS_PATH = DEFAULT_CLIPS_BASE_PATH / "_links"
    LEGACY_DEFAULT_SUCCESS_SOUND_PATH = LEGACY_PERSONAL_BASE_PATH / "Success_VideoClip.wav"
    DEFAULT_SUCCESS_SOUND_PATH = SCRIPT_DIR / "Replay_Saved.wav"
    DEFAULT_FAILURE_SOUND_PATH = SCRIPT_DIR / "Replay_Failed.wav"
    DEFAULT_RECORDING_START_SOUND_PATH = SCRIPT_DIR / "Recording_Started.wav"
    DEFAULT_RECORDING_STOP_SOUND_PATH = SCRIPT_DIR / "Recording_Stoped.wav"
    SETTINGS_PERSIST_PATH = Path(__file__).with_name("Moment_Replays.settings.json")
    LEGACY_SETTINGS_PERSIST_PATH = Path(__file__).with_name("arkanoid_replays.settings.json")
    SETTINGS_SCHEMA_VERSION = 5
    LEGACY_APP_RULES_PERSIST_PATH = Path(__file__).with_name("arkanoid_replays.app_rules.json")
    GITHUB_PROJECT_URL = "https://github.com/Arkanoidvfx/Moment_Replays"
    GITHUB_LATEST_RELEASE_URL = f"{GITHUB_PROJECT_URL}/releases/latest"
    GITHUB_LATEST_RELEASE_API_URL = "https://api.github.com/repos/Arkanoidvfx/Moment_Replays/releases/latest"
    UPDATE_CHECK_TIMEOUT = 5
    OTHER_FOLDER_NAME = "Other"
    SAFE_CLIP_NAME_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*%]')
    RESERVED_WINDOWS_NAMES = frozenset(
        ("con", "prn", "aux", "nul") +
        tuple(f"com{i}" for i in range(1, 10)) +
        tuple(f"lpt{i}" for i in range(1, 10))
    )
    DEFAULT_ALIASES = (
        {"value": "C:\\Windows\\explorer.exe > Desktop", "selected": False, "hidden": False},
        {"value": f"{sys.executable} > OBS", "selected": False, "hidden": False}
    )
    DEFAULT_OTHER_APP_NAMES = (
        "chrome",
        "OBS",
        "ChatGPT",
        "SunBrowser",
        "ms-teams",
        "Discord",
        "Telegram",
        "steam",
        "msedge",
        "firefox",
        "opera",
        "WhatsApp",
        "Spotify",
        "slack",
        "Zoom",
    )
    DEFAULT_APP_NAME_REPLACEMENTS = (
        "VALORANT-Win64-Shipping > VALORANT",
        "TslGame > PUBG",
    )


class VARIABLES:
    clip_exe_history: deque[Path, ...] | None = None
    clip_exe_counts: dict[Path, int] = {}
    aliases: dict[Path, str] = {}
    other_names: set[str] = set()
    name_replacements: dict[str, str] = {}
    script_settings = None
    hotkey_ids: dict = {}
    force_override_save = False
    half_buffer_save = False
    forced_save_watchdog_armed = False
    forced_save_watchdog_timeout_ms = 0
    cached_active_window_pid: int | None = None
    cached_active_exe: Path | None = None
    last_created_clip_folder: Path | None = None
    last_links_folder: Path | None = None
    last_saved_clip_path: Path | None = None
    save_in_progress = False
    open_last_video_requested = False
    open_last_video_wait_ticks = 0
    sidecar_persist_enabled = False
    update_check_in_progress = False
    update_status_props = None
    update_status_refresh_timer_active = False
    latest_release_url = CONSTANTS.GITHUB_LATEST_RELEASE_URL
    update_status_text = ""
    update_status_key = "update_status_initial"
    update_status_args = {"version": CONSTANTS.VERSION}
    interface_language_refreshing = False


class ConfigTypes(Enum):
    PROFILE = 0
    APP = 1
    USER = 2


class ClipNamingModes(Enum):
    CURRENT_PROCESS = 0
    MOST_RECORDED_PROCESS = 1
    CURRENT_SCENE = 2


class PropertiesNames:
    # UI settings
    PROP_INTERFACE_LANGUAGE = "interface_language"

    # Prop groups
    GR_CLIPS_PATH_SETTINGS = "clips_path_settings"
    GR_CLIP_NAMING_SETTINGS = "clip_naming_settings"
    GR_SOUND_NOTIFICATION_SETTINGS = "sound_notification_settings"
    GR_ALIASES_SETTINGS = "aliases_settings"
    GR_UPDATE_SETTINGS = "update_settings"

    # Clips path settings
    PROP_CLIPS_BASE_PATH = "clips_base_path"
    TXT_CLIPS_BASE_PATH_WARNING = "clips_base_path_warning"
    PROP_SHOW_OVERRIDE_FOLDER_SETTINGS = "show_override_folder_settings"
    PROP_CLIPS_OVERRIDE_PATH = "clips_override_path"
    TXT_CLIPS_OVERRIDE_PATH_WARNING = "clips_override_path_warning"
    PROP_SHOW_CLIP_NAMING_SETTINGS = "show_clip_naming_settings"
    PROP_CLIPS_NAMING_MODE = "clips_naming_mode"
    TXT_CLIPS_HOTKEY_TIP = "clips_hotkey_tip"
    PROP_CLIPS_FILENAME_TEMPLATE = "clips_filename_template"
    TXT_CLIPS_FILENAME_TEMPLATE_ERR = "clips_filename_template_err"
    PROP_CLIPS_SAVE_TO_FOLDER = "clips_save_to_folder"
    TXT_CLIPS_SAVE_TO_FOLDER_DESC = "clips_save_to_folder_desc"
    PROP_CLIPS_CREATE_LINKS = "clips_create_links"
    TXT_CLIPS_CREATE_LINKS_DESC = "clips_create_links_desc"
    PROP_CLIPS_LINKS_FOLDER_PATH = "clips_links_folder_path"
    TXT_CLIPS_LINKS_FOLDER_PATH_WARNING = "clips_links_folder_path_warning"

    # Sound notification settings
    PROP_NOTIFY_CLIPS_ON_SUCCESS = "notify_clips_on_success"
    PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH = "notify_clips_on_success_path"
    PROP_NOTIFY_CLIPS_ON_FAILURE = "notify_clips_on_failure"
    PROP_NOTIFY_CLIPS_ON_FAILURE_PATH = "notify_clips_on_failure_path"
    PROP_NOTIFY_RECORDING_ON_START = "notify_recording_on_start"
    PROP_NOTIFY_RECORDING_ON_START_PATH = "notify_recording_on_start_path"
    PROP_NOTIFY_RECORDING_ON_STOP = "notify_recording_on_stop"
    PROP_NOTIFY_RECORDING_ON_STOP_PATH = "notify_recording_on_stop_path"

    # Aliases settings
    PROP_ALIASES_LIST = "aliases_list"
    TXT_ALIASES_DESC = "aliases_desc"
    TXT_ALIASES_FORMAT = "aliases_format_text"

    # Aliases parsing error texts
    TXT_ALIASES_PATH_EXISTS = "aliases_path_exists_err"
    TXT_ALIASES_INVALID_FORMAT = "aliases_invalid_format_err"
    TXT_ALIASES_INVALID_CHARACTERS = "aliases_invalid_characters_err"

    # Export / Import aliases section
    PROP_ALIASES_EXPORT_PATH = "aliases_export_path"
    BTN_ALIASES_EXPORT = "aliases_export_btn"
    PROP_ALIASES_IMPORT_PATH = "aliases_import_path"
    BTN_ALIASES_IMPORT = "aliases_import_btn"

    # App name rules
    TXT_APP_NAME_RULES_DESC = "app_name_rules_desc"
    TXT_APP_OTHER_NAMES_TITLE = "app_other_names_title"
    PROP_APP_OTHER_NAMES = "app_other_names"
    TXT_APP_OTHER_NAMES_DESC = "app_other_names_desc"
    TXT_APP_OTHER_NAMES_INVALID = "app_other_names_invalid_err"
    PROP_APP_NAME_REPLACEMENTS = "app_name_replacements"
    TXT_APP_NAME_REPLACEMENTS_DESC = "app_name_replacements_desc"
    TXT_APP_NAME_REPLACEMENTS_INVALID_FORMAT = "app_name_replacements_invalid_format_err"
    TXT_APP_NAME_REPLACEMENTS_INVALID_CHARACTERS = "app_name_replacements_invalid_characters_err"

    # Update section
    TXT_UPDATE_STATUS = "update_status"
    BTN_CHECK_UPDATES = "check_updates_btn"
    BTN_OPEN_LATEST_RELEASE = "open_latest_release_btn"

    # Other section
    PROP_SHORT_BUFFER_PERCENT = "short_buffer_percent"
    TXT_SHORT_BUFFER_PERCENT_DESC = "short_buffer_percent_desc"

    # Hotkeys
    HK_SAVE_BUFFER_HALF = "save_buffer_half"
    HK_SAVE_BUFFER_OVERRIDE = "save_buffer_override_folder"
    HK_OPEN_LAST_VIDEO = "open_last_video"

PN = PropertiesNames

PERSISTED_STRING_DEFAULTS = {
    PN.PROP_INTERFACE_LANGUAGE: "en",
    PN.PROP_CLIPS_BASE_PATH: "",
    PN.PROP_CLIPS_OVERRIDE_PATH: "",
    PN.PROP_CLIPS_FILENAME_TEMPLATE: CONSTANTS.DEFAULT_FILENAME_FORMAT,
    PN.PROP_CLIPS_LINKS_FOLDER_PATH: str(CONSTANTS.DEFAULT_LINKS_PATH),
    PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH: str(CONSTANTS.DEFAULT_SUCCESS_SOUND_PATH),
    PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH: str(CONSTANTS.DEFAULT_FAILURE_SOUND_PATH),
    PN.PROP_NOTIFY_RECORDING_ON_START_PATH: str(CONSTANTS.DEFAULT_RECORDING_START_SOUND_PATH),
    PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH: str(CONSTANTS.DEFAULT_RECORDING_STOP_SOUND_PATH),
    PN.PROP_ALIASES_IMPORT_PATH: "",
    PN.PROP_ALIASES_EXPORT_PATH: "",
}

PERSISTED_BOOL_DEFAULTS = {
    PN.PROP_CLIPS_SAVE_TO_FOLDER: True,
    PN.PROP_CLIPS_CREATE_LINKS: False,
    PN.GR_SOUND_NOTIFICATION_SETTINGS: True,
    PN.PROP_NOTIFY_CLIPS_ON_SUCCESS: True,
    PN.PROP_NOTIFY_CLIPS_ON_FAILURE: True,
    PN.PROP_NOTIFY_RECORDING_ON_START: False,
    PN.PROP_NOTIFY_RECORDING_ON_STOP: False,
    PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS: True,
    PN.PROP_SHOW_CLIP_NAMING_SETTINGS: False,
}

PERSISTED_INT_DEFAULTS = {
    PN.PROP_CLIPS_NAMING_MODE: ClipNamingModes.MOST_RECORDED_PROCESS.value,
    PN.PROP_SHORT_BUFFER_PERCENT: 40,
}

PERSISTED_LIST_DEFAULTS = {
    PN.PROP_ALIASES_LIST: [item["value"] for item in CONSTANTS.DEFAULT_ALIASES],
    PN.PROP_APP_OTHER_NAMES: list(CONSTANTS.DEFAULT_OTHER_APP_NAMES),
    PN.PROP_APP_NAME_REPLACEMENTS: list(CONSTANTS.DEFAULT_APP_NAME_REPLACEMENTS),
}

DEFAULT_SOUND_PATHS = {
    PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH: str(CONSTANTS.DEFAULT_SUCCESS_SOUND_PATH),
    PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH: str(CONSTANTS.DEFAULT_FAILURE_SOUND_PATH),
    PN.PROP_NOTIFY_RECORDING_ON_START_PATH: str(CONSTANTS.DEFAULT_RECORDING_START_SOUND_PATH),
    PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH: str(CONSTANTS.DEFAULT_RECORDING_STOP_SOUND_PATH),
}

LEGACY_DEFAULT_SOUND_PATHS = {
    PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH: {"", str(CONSTANTS.LEGACY_DEFAULT_SUCCESS_SOUND_PATH)},
    PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH: {"", str(CONSTANTS.LEGACY_PERSONAL_BASE_PATH)},
    PN.PROP_NOTIFY_RECORDING_ON_START_PATH: {"", str(CONSTANTS.LEGACY_PERSONAL_BASE_PATH)},
    PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH: {"", str(CONSTANTS.LEGACY_PERSONAL_BASE_PATH)},
}


UI_TEXT = {
    "en": {
        "script_description_summary": (
            "Save replay clips with app or scene names, path and .exe rules, Other folder routing, "
            "sounds, short clips, and update checks."
        ),
        "interface_language": "Interface language",
        "hotkey_settings_tip": "All hotkeys can be changed in OBS Settings -> Hotkeys.",
        "group_clip_paths": "Clip paths",
        "group_clip_naming": "Clip naming",
        "group_sound_notifications": "Sounds",
        "group_app_naming_rules": "Naming rules",
        "group_updates": "Updates",
        "base_folder": "Base folder",
        "same_drive_warning": "Use the same drive as the OBS recording path.",
        "show_override_folder_settings": "Alternative recording modes",
        "override_folder": "Alternative save folder",
        "short_clip_duration": "Shortened clip",
        "short_clip_duration_desc": (
            "The short-clip hotkey keeps the last N% of the replay buffer. Example: 40% of 1 minute = 24 seconds. "
            "Requires ffmpeg available in PATH."
        ),
        "create_hard_links": "Create hard links",
        "create_hard_links_desc": (
            "Creates a second file entry for the same video data. Requires the same drive."
        ),
        "links_folder": "Links folder",
        "clip_name": "Clip name",
        "clip_name_active_app": "Active app at save time",
        "clip_name_most_recorded_app": "App active for most of the replay",
        "clip_name_current_scene": "Current scene",
        "file_name": "File name",
        "invalid_file_name_format": "<font color=\"red\"><pre> Invalid file name format.</pre></font>",
        "play_on_success": "Play on success",
        "play_on_success_path": "Success sound",
        "play_on_failure": "Play on failure",
        "play_on_failure_path": "Failure sound",
        "play_recording_start": "Play on recording start",
        "play_recording_start_path": "Recording start sound",
        "play_recording_stop": "Play on recording stop",
        "play_recording_stop_path": "Recording stop sound",
        "import_rules_file": "Rules import file",
        "export_rules_folder": "Rules export folder",
        "path_specific_names_desc": (
            "<b>Path-specific names</b><br/>"
            "Exact .exe path or parent folder to clip name."
        ),
        "alias_invalid_chars": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Invalid characters in path or clip name.</span><br/>"
            "<span style=\"color: orange\">Clip name cannot contain "
            "<code>&lt; &gt; / \\ | * ? : \" %</code>.<br/>"
            "Path cannot contain <code>&lt; &gt; | * ? \" %</code>.</span>"
            "</div>"
        ),
        "alias_path_exists": "<div style=\"font-size: 13px; color: red\">This path is already in the list.</div>",
        "alias_invalid_format": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Invalid alias format.</span><br/>"
            "<span style=\"color: orange\">Use: DISK:\\path\\to\\folder\\or\\executable &gt; ClipName</span><br/>"
            "<span style=\"color: lightgreen\">Example: C:\\Program Files\\Minecraft &gt; Minecraft</span>"
            "</div>"
        ),
        "aliases_format_desc": (
            "Format: DISK:\\path\\to\\folder\\or\\executable > ClipName\n"
            "Use for launchers, duplicate .exe names, or folder-wide rules.\n"
            "Example: {python_exe} > OBS"
        ),
        "import_path_specific_names": "Import path-specific names",
        "export_path_specific_names": "Export path-specific names",
        "exe_name_fixes_desc": (
            "<b>Executable name fixes</b>"
        ),
        "replacement_invalid_chars": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Invalid characters in app name replacement.</span><br/>"
            "<span style=\"color: orange\">Replacement name cannot contain "
            "<code>&lt; &gt; / \\ | * ? : \" %</code>.</span>"
            "</div>"
        ),
        "replacement_invalid_format": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Invalid replacement format.</span><br/>"
            "<span style=\"color: orange\">Use: RawName &gt; FixedName</span><br/>"
            "<span style=\"color: lightgreen\">Example: TslGame &gt; PUBG</span>"
            "</div>"
        ),
        "replacement_format_desc": "RawExeName > ClipName",
        "send_to_other_desc": (
            "<b>Send to {other_folder}</b><br/>"
            "Final clip names in this list are saved to the {other_folder} folder."
        ),
        "other_names_invalid": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Use app names only.</span><br/>"
            "<span style=\"color: orange\">No paths, no separators like <code>&gt; / \\ :</code>.</span>"
            "</div>"
        ),
        "apps_saved_to_other": "Apps saved to folder {other_folder}",
        "other_names_desc": "Exact final clip-name match, case-insensitive. Example: chrome",
        "check_updates": "Check for updates",
        "open_latest_release": "Open latest release",
        "update_status_initial": "Current version: {version}. Update check has not run yet.",
        "update_status_running": "Update check is already running.",
        "update_status_checking": (
            "Checking for updates...<br/>"
            "Current version: <span style=\"font-size: 1.2em;\"><b>{version}</b></span>"
        ),
        "update_status_available": "Update available: {latest_version} (current: {version}). Open the latest release to update.",
        "update_status_current": "Current version {version} is up to date. Latest release: {latest_version}.",
        "update_status_no_release": "No GitHub release is published yet. Current version: {version}.",
        "update_status_http_error": "Update check failed: GitHub returned HTTP {code}.",
        "update_status_failed": "Update check failed: {error}",
        "update_status_thread_failed": "Cannot start update check thread.",
    },
    "ru": {
        "script_description_summary": (
            "Сохраняет replay-клипы с именами по приложениям или сценам, правилами по путям и .exe, "
            "папкой Other, звуками, короткими клипами и проверкой обновлений."
        ),
        "interface_language": "Язык интерфейса",
        "hotkey_settings_tip": "Все хоткеи можно изменить в OBS: Settings -> Hotkeys.",
        "group_clip_paths": "Папки клипов",
        "group_clip_naming": "Имена клипов",
        "group_sound_notifications": "Звуки",
        "group_app_naming_rules": "Правила имен",
        "group_updates": "Обновление",
        "base_folder": "Основная папка",
        "same_drive_warning": "Должно быть на том же диске, что и путь записи OBS.",
        "show_override_folder_settings": "Альтернативные режимы записи",
        "override_folder": "Папка альтернативного сохранения",
        "short_clip_duration": "Укороченный клип",
        "short_clip_duration_desc": (
            "Хоткей короткого клипа оставляет последние N% replay buffer. Пример: 40% от 1 минуты = 24 секунды. "
            "Требуется ffmpeg в PATH."
        ),
        "create_hard_links": "Создавать hard links",
        "create_hard_links_desc": (
            "Создает вторую запись файла для тех же видеоданных. Требует тот же диск."
        ),
        "links_folder": "Папка ссылок",
        "clip_name": "Имя клипа",
        "clip_name_active_app": "Активное приложение в момент сохранения",
        "clip_name_most_recorded_app": "Приложение, активное большую часть replay",
        "clip_name_current_scene": "Текущая сцена",
        "file_name": "Имя файла",
        "invalid_file_name_format": "<font color=\"red\"><pre> Неверный формат имени файла.</pre></font>",
        "play_on_success": "Звук при успешном сохранении",
        "play_on_success_path": "Звук успеха",
        "play_on_failure": "Звук при ошибке сохранения",
        "play_on_failure_path": "Звук ошибки",
        "play_recording_start": "Звук при старте записи",
        "play_recording_start_path": "Звук старта записи",
        "play_recording_stop": "Звук при остановке записи",
        "play_recording_stop_path": "Звук остановки записи",
        "import_rules_file": "Файл импорта правил",
        "export_rules_folder": "Папка экспорта правил",
        "path_specific_names_desc": (
            "<b>Имена по пути</b><br/>"
            "Точный путь .exe или родительская папка -> имя клипа."
        ),
        "alias_invalid_chars": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Недопустимые символы в пути или имени клипа.</span><br/>"
            "<span style=\"color: orange\">Имя клипа не может содержать "
            "<code>&lt; &gt; / \\ | * ? : \" %</code>.<br/>"
            "Путь не может содержать <code>&lt; &gt; | * ? \" %</code>.</span>"
            "</div>"
        ),
        "alias_path_exists": "<div style=\"font-size: 13px; color: red\">Этот путь уже есть в списке.</div>",
        "alias_invalid_format": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Неверный формат правила.</span><br/>"
            "<span style=\"color: orange\">Используй: DISK:\\path\\to\\folder\\or\\executable &gt; ClipName</span><br/>"
            "<span style=\"color: lightgreen\">Пример: C:\\Program Files\\Minecraft &gt; Minecraft</span>"
            "</div>"
        ),
        "aliases_format_desc": (
            "Формат: DISK:\\path\\to\\folder\\or\\executable > ClipName\n"
            "Для лаунчеров, одинаковых .exe или правил на всю папку.\n"
            "Пример: {python_exe} > OBS"
        ),
        "import_path_specific_names": "Импортировать имена по путям",
        "export_path_specific_names": "Экспортировать имена по путям",
        "exe_name_fixes_desc": (
            "<b>Исправления имен .exe</b>"
        ),
        "replacement_invalid_chars": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Недопустимые символы в замене имени приложения.</span><br/>"
            "<span style=\"color: orange\">Новое имя не может содержать "
            "<code>&lt; &gt; / \\ | * ? : \" %</code>.</span>"
            "</div>"
        ),
        "replacement_invalid_format": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Неверный формат замены.</span><br/>"
            "<span style=\"color: orange\">Используй: RawName &gt; FixedName</span><br/>"
            "<span style=\"color: lightgreen\">Пример: TslGame &gt; PUBG</span>"
            "</div>"
        ),
        "replacement_format_desc": "RawExeName > ClipName",
        "send_to_other_desc": (
            "<b>Отправлять в {other_folder}</b><br/>"
            "Финальные имена клипов из списка сохраняются в папку {other_folder}."
        ),
        "other_names_invalid": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Используй только имена приложений.</span><br/>"
            "<span style=\"color: orange\">Без путей и разделителей вроде <code>&gt; / \\ :</code>.</span>"
            "</div>"
        ),
        "apps_saved_to_other": "Приложения, сохраняемые в папку {other_folder}",
        "other_names_desc": "Точное совпадение финального имени клипа, без учета регистра. Пример: chrome",
        "check_updates": "Проверить обновления",
        "open_latest_release": "Открыть последний релиз",
        "update_status_initial": "Текущая версия: {version}. Проверка обновлений еще не запускалась.",
        "update_status_running": "Проверка обновлений уже выполняется.",
        "update_status_checking": (
            "Проверка обновлений...<br/>"
            "Текущая версия: <span style=\"font-size: 1.2em;\"><b>{version}</b></span>"
        ),
        "update_status_available": "Доступно обновление: {latest_version} (текущая: {version}). Открой последний релиз для обновления.",
        "update_status_current": "Текущая версия {version} актуальна. Последний релиз: {latest_version}.",
        "update_status_no_release": "GitHub release еще не опубликован. Текущая версия: {version}.",
        "update_status_http_error": "Проверка обновлений не удалась: GitHub вернул HTTP {code}.",
        "update_status_failed": "Проверка обновлений не удалась: {error}",
        "update_status_thread_failed": "Не удалось запустить поток проверки обновлений.",
    },
}


def get_ui_language(data=None) -> str:
    data = data if data is not None else VARIABLES.script_settings
    if data is not None:
        with suppress(Exception):
            lang = obs.obs_data_get_string(data, PN.PROP_INTERFACE_LANGUAGE)
            if lang in UI_TEXT:
                return lang
    with suppress(Exception):
        with open(get_existing_persisted_settings_path(), "r", encoding="utf-8") as f:
            lang = json.load(f).get(PN.PROP_INTERFACE_LANGUAGE)
            if lang in UI_TEXT:
                return lang
    return "en"


def tr(key: str, data=None, lang: str | None = None, **kwargs) -> str:
    lang = lang if lang in UI_TEXT else get_ui_language(data)
    text = UI_TEXT.get(lang, UI_TEXT["en"]).get(key, UI_TEXT["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text


def get_update_status_text(data=None) -> str:
    if VARIABLES.update_status_key:
        return tr(VARIABLES.update_status_key, data=data, **VARIABLES.update_status_args)
    return VARIABLES.update_status_text or tr("update_status_initial", data=data, version=CONSTANTS.VERSION)


# -------------------- exceptions.py --------------------
class AliasParsingError(Exception):
    """
    Base exception for all alias related exceptions.
    """
    def __init__(self, index):
        """
        :param index: alias index.
        """
        super(Exception).__init__()
        self.index = index


class AliasPathAlreadyExists(AliasParsingError):
    """
    Exception raised when an alias is already exists.
    """


class AliasInvalidCharacters(AliasParsingError):
    """
    Exception raised when an alias has invalid characters.
    """


class AliasInvalidFormat(AliasParsingError):
    """
    Exception raised when an alias is invalid format.
    """


class AppRuleParsingError(Exception):
    """
    Base exception for app name rule parsing errors.
    """
    def __init__(self, index):
        super(Exception).__init__()
        self.index = index


class OtherNameInvalidCharacters(AppRuleParsingError):
    """
    Exception raised when an `Other` app name is invalid.
    """


class NameReplacementInvalidFormat(AppRuleParsingError):
    """
    Exception raised when an app name replacement has invalid format.
    """


class NameReplacementInvalidCharacters(AppRuleParsingError):
    """
    Exception raised when an app name replacement contains invalid characters.
    """


# -------------------- updates_check.py --------------------
def parse_version_parts(value: str) -> tuple[int, ...]:
    value = str(value).strip()
    if value.lower().startswith("v"):
        value = value[1:]
    return tuple(int(part) for part in re.findall(r"\d+", value))


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = parse_version_parts(candidate)
    current_parts = parse_version_parts(current)
    if not candidate_parts or not current_parts:
        return False

    size = max(len(candidate_parts), len(current_parts))
    candidate_parts = candidate_parts + (0,) * (size - len(candidate_parts))
    current_parts = current_parts + (0,) * (size - len(current_parts))
    return candidate_parts > current_parts


def set_update_status_text(message: str, *, log: bool = True) -> None:
    VARIABLES.update_status_key = ""
    VARIABLES.update_status_args = {}
    VARIABLES.update_status_text = message
    if log:
        _print(message)


def set_update_status_key(key: str, *, log: bool = True, lang: str | None = None, **kwargs) -> None:
    VARIABLES.update_status_key = key
    VARIABLES.update_status_args = dict(kwargs)
    VARIABLES.update_status_text = ""
    if log:
        _print(tr(key, lang=lang, **kwargs))


def fetch_latest_release_info() -> tuple[str, str]:
    request = urllib.request.Request(
        CONSTANTS.GITHUB_LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Moment-Replays/{CONSTANTS.VERSION}",
        }
    )
    with urllib.request.urlopen(request, timeout=CONSTANTS.UPDATE_CHECK_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an invalid release payload.")

    version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    release_url = str(payload.get("html_url") or CONSTANTS.GITHUB_LATEST_RELEASE_URL).strip()
    if not version:
        raise ValueError("GitHub release does not include a version tag.")
    return version, release_url


def check_for_updates(source: str = "manual", lang: str | None = None, *, lock_acquired: bool = False) -> bool:
    if not lock_acquired and not CONSTANTS.UPDATE_CHECK_LOCK.acquire(blocking=False):
        set_update_status_key("update_status_running", lang=lang)
        return False

    VARIABLES.update_check_in_progress = True
    try:
        set_update_status_key("update_status_checking", version=CONSTANTS.VERSION, lang=lang)
        latest_version, release_url = fetch_latest_release_info()
        VARIABLES.latest_release_url = release_url

        if is_newer_version(latest_version, CONSTANTS.VERSION):
            set_update_status_key(
                "update_status_available",
                latest_version=latest_version,
                version=CONSTANTS.VERSION,
                lang=lang
            )
        else:
            set_update_status_key(
                "update_status_current",
                latest_version=latest_version,
                version=CONSTANTS.VERSION,
                lang=lang
            )
        return True

    except urllib.error.HTTPError as e:
        if e.code == 404:
            set_update_status_key("update_status_no_release", version=CONSTANTS.VERSION, lang=lang)
        else:
            set_update_status_key("update_status_http_error", code=e.code, lang=lang)
        return False
    except Exception as e:
        set_update_status_key("update_status_failed", error=e, lang=lang)
        return False
    finally:
        VARIABLES.update_check_in_progress = False
        with suppress(RuntimeError):
            CONSTANTS.UPDATE_CHECK_LOCK.release()


def start_update_check_thread(source: str = "automatic", props=None) -> bool:
    lang = get_ui_language()
    if props is not None:
        VARIABLES.update_status_props = props

    if not CONSTANTS.UPDATE_CHECK_LOCK.acquire(blocking=False):
        set_update_status_key("update_status_running", lang=lang)
        if props is not None:
            update_update_status_property(props)
        return False

    VARIABLES.update_check_in_progress = True
    set_update_status_key("update_status_checking", version=CONSTANTS.VERSION, lang=lang)
    if props is not None:
        update_update_status_property(props)
        schedule_update_status_refresh(props)

    try:
        Thread(target=check_for_updates, args=(source, lang), kwargs={"lock_acquired": True}, daemon=True).start()
    except Exception:
        set_update_status_key("update_status_thread_failed", lang=lang)
        _print(traceback.format_exc())
        VARIABLES.update_check_in_progress = False
        with suppress(RuntimeError):
            CONSTANTS.UPDATE_CHECK_LOCK.release()
        return False
    return True


# -------------------- properties.py --------------------
variables_tip = """<table>
<tr><th align='left'>%NAME</th><td> - name of the clip.</td></tr>

<tr><th align='left'>%a</th><td> - Weekday as locale’s abbreviated name.<br/>
Example: Sun, Mon, …, Sat (en_US); So, Mo, …, Sa (de_DE)</td></tr>

<tr><th align='left'>%A</th><td> - Weekday as locale’s full name.<br/>
Example: Sunday, Monday, …, Saturday (en_US); Sonntag, Montag, …, Samstag (de_DE)</td></tr>

<tr><th align='left'>%w</th><td> - Weekday as a decimal number, where 0 is Sunday and 6 is Saturday.<br/>
Example: 0, 1, …, 6</td></tr>

<tr><th align='left'>%d</th><td> - Day of the month as a zero-padded decimal number.<br/>
Example: 01, 02, …, 31</td></tr>

<tr><th align='left'>%b</th><td> - Month as locale’s abbreviated name.<br/>
Example: Jan, Feb, …, Dec (en_US); Jan, Feb, …, Dez (de_DE)</td></tr>

<tr><th align='left'>%B</th><td> - Month as locale’s full name.<br/>
Example: January, February, …, December (en_US); Januar, Februar, …, Dezember (de_DE)</td></tr>

<tr><th align='left'>%m</th><td> - Month as a zero-padded decimal number.<br/>
Example: 01, 02, …, 12</td></tr>

<tr><th align='left'>%y</th><td> - Year without century as a zero-padded decimal number.<br/>
Example: 00, 01, …, 99</td></tr>

<tr><th align='left'>%Y</th><td> - Year with century as a decimal number.<br/>
Example: 0001, 0002, …, 2013, 2014, …, 9998, 9999</td></tr>

<tr><th align='left'>%H</th><td> - Hour (24-hour clock) as a zero-padded decimal number.<br/>
Example: 00, 01, …, 23</td></tr>

<tr><th align='left'>%I</th><td> - Hour (12-hour clock) as a zero-padded decimal number.<br/>
Example: 01, 02, …, 12</td></tr>

<tr><th align='left'>%p</th><td> - Locale’s equivalent of either AM or PM.<br/>
Example: AM, PM (en_US); am, pm (de_DE)</td></tr>

<tr><th align='left'>%M</th><td> - Minute as a zero-padded decimal number.<br/>
Example: 00, 01, …, 59</td></tr>

<tr><th align='left'>%S</th><td> - Second as a zero-padded decimal number.<br/>
Example: 00, 01, …, 59</td></tr>

<tr><th align='left'>%f</th><td> - Microsecond as a decimal number, zero-padded to 6 digits.<br/>
Example: 000000, 000001, …, 999999</td></tr>

<tr><th align='left'>%z</th><td> - UTC offset in the form ±HHMM[SS[.ffffff]]<br/>
Example: +0000, -0400, +1030, +063415, -030712.345216</td></tr>

<tr><th align='left'>%Z</th><td> - Time zone name<br/>
Example: UTC, GMT</td></tr>

<tr><th align='left'>%j</th><td> - Day of the year as a zero-padded decimal number.<br/>
Example: 001, 002, …, 366</td></tr>

<tr><th align='left'>%U</th><td> - Week number of the year (Sunday as the first day of the week) as a zero-padded decimal number. All days in a new year preceding the first Sunday are considered to be in week 0.<br/>
Example: 00, 01, …, 53</td></tr>

<tr><th align='left'>%W</th><td> - Week number of the year (Monday as the first day of the week) as a zero-padded decimal number. All days in a new year preceding the first Monday are considered to be in week 0.<br/>
Example: 00, 01, …, 53</td></tr>

<tr><th align='left'>%%</th><td> - A literal '%' character.</td></tr>
</table>"""

variables_tip_ru = """<table>
<tr><th align='left'>%NAME</th><td> - имя клипа.</td></tr>

<tr><th align='left'>%a</th><td> - сокращенное название дня недели по локали.<br/>
Пример: Sun, Mon, …, Sat (en_US)</td></tr>

<tr><th align='left'>%A</th><td> - полное название дня недели по локали.<br/>
Пример: Sunday, Monday, …, Saturday (en_US)</td></tr>

<tr><th align='left'>%w</th><td> - день недели числом, где 0 — воскресенье, 6 — суббота.<br/>
Пример: 0, 1, …, 6</td></tr>

<tr><th align='left'>%d</th><td> - день месяца двумя цифрами.<br/>
Пример: 01, 02, …, 31</td></tr>

<tr><th align='left'>%b</th><td> - сокращенное название месяца по локали.<br/>
Пример: Jan, Feb, …, Dec (en_US)</td></tr>

<tr><th align='left'>%B</th><td> - полное название месяца по локали.<br/>
Пример: January, February, …, December (en_US)</td></tr>

<tr><th align='left'>%m</th><td> - месяц двумя цифрами.<br/>
Пример: 01, 02, …, 12</td></tr>

<tr><th align='left'>%y</th><td> - год без века двумя цифрами.<br/>
Пример: 00, 01, …, 99</td></tr>

<tr><th align='left'>%Y</th><td> - год полностью.<br/>
Пример: 2025, 2026</td></tr>

<tr><th align='left'>%H</th><td> - час в 24-часовом формате двумя цифрами.<br/>
Пример: 00, 01, …, 23</td></tr>

<tr><th align='left'>%I</th><td> - час в 12-часовом формате двумя цифрами.<br/>
Пример: 01, 02, …, 12</td></tr>

<tr><th align='left'>%p</th><td> - AM или PM по локали.<br/>
Пример: AM, PM (en_US)</td></tr>

<tr><th align='left'>%M</th><td> - минуты двумя цифрами.<br/>
Пример: 00, 01, …, 59</td></tr>

<tr><th align='left'>%S</th><td> - секунды двумя цифрами.<br/>
Пример: 00, 01, …, 59</td></tr>

<tr><th align='left'>%f</th><td> - микросекунды, 6 цифр.<br/>
Пример: 000000, 000001, …, 999999</td></tr>

<tr><th align='left'>%z</th><td> - UTC-смещение в формате ±HHMM[SS[.ffffff]].<br/>
Пример: +0000, -0400, +1030</td></tr>

<tr><th align='left'>%Z</th><td> - название часового пояса.<br/>
Пример: UTC, GMT</td></tr>

<tr><th align='left'>%j</th><td> - день года тремя цифрами.<br/>
Пример: 001, 002, …, 366</td></tr>

<tr><th align='left'>%U</th><td> - номер недели года, если неделя начинается в воскресенье.<br/>
Пример: 00, 01, …, 53</td></tr>

<tr><th align='left'>%W</th><td> - номер недели года, если неделя начинается в понедельник.<br/>
Пример: 00, 01, …, 53</td></tr>

<tr><th align='left'>%%</th><td> - символ %.</td></tr>
</table>"""


def get_variables_tip() -> str:
    return variables_tip_ru if get_ui_language() == "ru" else variables_tip


def setup_interface_settings(props):
    language_prop = obs.obs_properties_add_list(
        props=props,
        name=PN.PROP_INTERFACE_LANGUAGE,
        description=tr("interface_language"),
        type=obs.OBS_COMBO_TYPE_LIST,
        format=obs.OBS_COMBO_FORMAT_STRING
    )
    obs.obs_property_list_add_string(p=language_prop, name="English", val="en")
    obs.obs_property_list_add_string(p=language_prop, name="Russian", val="ru")
    obs.obs_property_set_modified_callback(language_prop, update_interface_language_callback)
    obs.obs_properties_add_text(
        props=props,
        name=PN.TXT_CLIPS_HOTKEY_TIP,
        description=tr("hotkey_settings_tip"),
        type=obs.OBS_TEXT_INFO
    )


def get_group_content(props, group_name: str):
    group_prop = obs.obs_properties_get(props, group_name)
    group_content = getattr(obs, "obs_property_group_content", None)
    if group_prop is None or group_content is None:
        return None
    with suppress(Exception):
        return group_content(group_prop)
    return None


def set_property_description(props, prop_name: str, description: str) -> None:
    if props is None:
        return
    prop = obs.obs_properties_get(props, prop_name)
    if prop is not None:
        obs.obs_property_set_description(prop, description)


def refresh_clip_naming_mode_options(props, data=None) -> None:
    prop = obs.obs_properties_get(props, PN.PROP_CLIPS_NAMING_MODE) if props is not None else None
    if prop is None:
        return

    obs.obs_property_list_clear(prop)
    obs.obs_property_list_add_int(
        p=prop,
        name=tr("clip_name_active_app", data=data),
        val=ClipNamingModes.CURRENT_PROCESS.value
    )
    obs.obs_property_list_add_int(
        p=prop,
        name=tr("clip_name_most_recorded_app", data=data),
        val=ClipNamingModes.MOST_RECORDED_PROCESS.value
    )
    obs.obs_property_list_add_int(
        p=prop,
        name=tr("clip_name_current_scene", data=data),
        val=ClipNamingModes.CURRENT_SCENE.value
    )


def refresh_localized_properties(props, data=None) -> None:
    set_property_description(props, PN.PROP_INTERFACE_LANGUAGE, tr("interface_language", data=data))
    set_property_description(props, PN.TXT_CLIPS_HOTKEY_TIP, tr("hotkey_settings_tip", data=data))
    set_property_description(props, PN.GR_UPDATE_SETTINGS, tr("group_updates", data=data))
    set_property_description(props, PN.GR_CLIPS_PATH_SETTINGS, tr("group_clip_paths", data=data))
    set_property_description(props, PN.GR_CLIP_NAMING_SETTINGS, tr("group_clip_naming", data=data))
    set_property_description(props, PN.GR_SOUND_NOTIFICATION_SETTINGS, tr("group_sound_notifications", data=data))
    set_property_description(props, PN.GR_ALIASES_SETTINGS, tr("group_app_naming_rules", data=data))

    updates = get_group_content(props, PN.GR_UPDATE_SETTINGS)
    set_property_description(updates, PN.TXT_UPDATE_STATUS, get_update_status_text(data))
    set_property_description(updates, PN.BTN_CHECK_UPDATES, tr("check_updates", data=data))
    set_property_description(updates, PN.BTN_OPEN_LATEST_RELEASE, tr("open_latest_release", data=data))

    clip_paths = get_group_content(props, PN.GR_CLIPS_PATH_SETTINGS)
    set_property_description(clip_paths, PN.PROP_CLIPS_BASE_PATH, tr("base_folder", data=data))
    set_property_description(clip_paths, PN.TXT_CLIPS_BASE_PATH_WARNING, tr("same_drive_warning", data=data))
    set_property_description(clip_paths, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS,
                             tr("show_override_folder_settings", data=data))
    set_property_description(clip_paths, PN.PROP_CLIPS_OVERRIDE_PATH, tr("override_folder", data=data))
    set_property_description(clip_paths, PN.TXT_CLIPS_OVERRIDE_PATH_WARNING, tr("same_drive_warning", data=data))
    set_property_description(clip_paths, PN.PROP_SHORT_BUFFER_PERCENT, tr("short_clip_duration", data=data))
    set_property_description(clip_paths, PN.TXT_SHORT_BUFFER_PERCENT_DESC, tr("short_clip_duration_desc", data=data))
    set_property_description(clip_paths, PN.PROP_CLIPS_CREATE_LINKS, tr("create_hard_links", data=data))
    set_property_description(clip_paths, PN.TXT_CLIPS_CREATE_LINKS_DESC, tr("create_hard_links_desc", data=data))
    set_property_description(clip_paths, PN.PROP_CLIPS_LINKS_FOLDER_PATH, tr("links_folder", data=data))
    set_property_description(clip_paths, PN.TXT_CLIPS_LINKS_FOLDER_PATH_WARNING, tr("same_drive_warning", data=data))

    clip_naming = get_group_content(props, PN.GR_CLIP_NAMING_SETTINGS)
    set_property_description(clip_naming, PN.PROP_CLIPS_NAMING_MODE, tr("clip_name", data=data))
    set_property_description(clip_naming, PN.PROP_CLIPS_FILENAME_TEMPLATE, tr("file_name", data=data))
    set_property_description(clip_naming, PN.TXT_CLIPS_FILENAME_TEMPLATE_ERR,
                             tr("invalid_file_name_format", data=data))
    refresh_clip_naming_mode_options(clip_naming, data)
    filename_prop = obs.obs_properties_get(clip_naming, PN.PROP_CLIPS_FILENAME_TEMPLATE) if clip_naming is not None else None
    if filename_prop is not None:
        obs.obs_property_set_long_description(filename_prop, variables_tip_ru if get_ui_language(data) == "ru" else variables_tip)

    notifications = get_group_content(props, PN.GR_SOUND_NOTIFICATION_SETTINGS)
    set_property_description(notifications, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS, tr("play_on_success", data=data))
    set_property_description(notifications, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH, tr("play_on_success_path", data=data))
    set_property_description(notifications, PN.PROP_NOTIFY_CLIPS_ON_FAILURE, tr("play_on_failure", data=data))
    set_property_description(notifications, PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH, tr("play_on_failure_path", data=data))
    set_property_description(notifications, PN.PROP_NOTIFY_RECORDING_ON_START, tr("play_recording_start", data=data))
    set_property_description(notifications, PN.PROP_NOTIFY_RECORDING_ON_START_PATH,
                             tr("play_recording_start_path", data=data))
    set_property_description(notifications, PN.PROP_NOTIFY_RECORDING_ON_STOP, tr("play_recording_stop", data=data))
    set_property_description(notifications, PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH,
                             tr("play_recording_stop_path", data=data))

    app_rules = get_group_content(props, PN.GR_ALIASES_SETTINGS)
    set_property_description(app_rules, PN.TXT_ALIASES_DESC, tr("path_specific_names_desc", data=data))
    set_property_description(app_rules, PN.TXT_ALIASES_INVALID_CHARACTERS, tr("alias_invalid_chars", data=data))
    set_property_description(app_rules, PN.TXT_ALIASES_PATH_EXISTS, tr("alias_path_exists", data=data))
    set_property_description(app_rules, PN.TXT_ALIASES_INVALID_FORMAT, tr("alias_invalid_format", data=data))
    set_property_description(app_rules, PN.TXT_ALIASES_FORMAT, tr("aliases_format_desc", data=data, python_exe=sys.executable))
    set_property_description(app_rules, PN.PROP_ALIASES_IMPORT_PATH, tr("import_rules_file", data=data))
    set_property_description(app_rules, PN.BTN_ALIASES_IMPORT, tr("import_path_specific_names", data=data))
    set_property_description(app_rules, PN.PROP_ALIASES_EXPORT_PATH, tr("export_rules_folder", data=data))
    set_property_description(app_rules, PN.BTN_ALIASES_EXPORT, tr("export_path_specific_names", data=data))
    set_property_description(app_rules, PN.TXT_APP_NAME_RULES_DESC, tr("exe_name_fixes_desc", data=data))
    set_property_description(app_rules, PN.TXT_APP_NAME_REPLACEMENTS_INVALID_CHARACTERS,
                             tr("replacement_invalid_chars", data=data))
    set_property_description(app_rules, PN.TXT_APP_NAME_REPLACEMENTS_INVALID_FORMAT,
                             tr("replacement_invalid_format", data=data))
    set_property_description(app_rules, PN.TXT_APP_NAME_REPLACEMENTS_DESC, tr("replacement_format_desc", data=data))
    set_property_description(app_rules, PN.TXT_APP_OTHER_NAMES_TITLE,
                             tr("send_to_other_desc", data=data, other_folder=CONSTANTS.OTHER_FOLDER_NAME))
    set_property_description(app_rules, PN.TXT_APP_OTHER_NAMES_INVALID, tr("other_names_invalid", data=data))
    set_property_description(app_rules, PN.PROP_APP_OTHER_NAMES,
                             tr("apps_saved_to_other", data=data, other_folder=CONSTANTS.OTHER_FOLDER_NAME))
    set_property_description(app_rules, PN.TXT_APP_OTHER_NAMES_DESC, tr("other_names_desc", data=data))


def setup_clip_paths_settings(group_obj):
    add_int_slider = getattr(obs, "obs_properties_add_int_slider", None)

    # ----- Clips base path -----
    base_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_CLIPS_BASE_PATH,
        description=tr("base_folder"),
        type=obs.OBS_PATH_DIRECTORY,
        filter=None,
        default_path=str(CONSTANTS.DEFAULT_CLIPS_BASE_PATH)
    )

    t = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_CLIPS_BASE_PATH_WARNING,
        description=tr("same_drive_warning"),
        type=obs.OBS_TEXT_INFO
    )

    obs.obs_property_text_set_info_type(t, obs.OBS_TEXT_INFO_WARNING)

    show_override_folder_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS,
        description=tr("show_override_folder_settings")
    )

    # ----- Override save path -----
    override_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_CLIPS_OVERRIDE_PATH,
        description=tr("override_folder"),
        type=obs.OBS_PATH_DIRECTORY,
        filter=None,
        default_path=str(CONSTANTS.DEFAULT_OVERRIDE_PATH)
    )

    override_warn = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_CLIPS_OVERRIDE_PATH_WARNING,
        description=tr("same_drive_warning"),
        type=obs.OBS_TEXT_INFO
    )

    obs.obs_property_text_set_info_type(override_warn, obs.OBS_TEXT_INFO_WARNING)
    obs.obs_property_set_visible(
        override_path_prop,
        obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS)
    )
    obs.obs_property_set_visible(
        override_warn,
        obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS)
    )

    # ----- Short clip length -----
    if add_int_slider is not None:
        short_buffer_prop = add_int_slider(
            props=group_obj,
            name=PN.PROP_SHORT_BUFFER_PERCENT,
            description=tr("short_clip_duration"),
            min=5, max=100,
            step=5
        )
    else:
        short_buffer_prop = obs.obs_properties_add_int(
            props=group_obj,
            name=PN.PROP_SHORT_BUFFER_PERCENT,
            description=tr("short_clip_duration"),
            min=5, max=100,
            step=5
        )
    short_buffer_desc = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_SHORT_BUFFER_PERCENT_DESC,
        description=tr("short_clip_duration_desc"),
        type=obs.OBS_TEXT_INFO
    )
    obs.obs_property_set_visible(
        short_buffer_prop,
        obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS)
    )
    obs.obs_property_set_visible(
        short_buffer_desc,
        obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS)
    )

    # ----- Create links -----
    create_links_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_CLIPS_CREATE_LINKS,
        description=tr("create_hard_links"),
    )
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_CLIPS_CREATE_LINKS_DESC,
        description=tr("create_hard_links_desc"),
        type=obs.OBS_TEXT_INFO
    )

    links_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_CLIPS_LINKS_FOLDER_PATH,
        description=tr("links_folder"),
        type=obs.OBS_PATH_DIRECTORY,
        filter=None,
        default_path=str(CONSTANTS.DEFAULT_LINKS_PATH)
    )
    links_path_warn = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_CLIPS_LINKS_FOLDER_PATH_WARNING,
        description=tr("same_drive_warning"),
        type=obs.OBS_TEXT_INFO
    )
    obs.obs_property_text_set_info_type(links_path_warn, obs.OBS_TEXT_INFO_WARNING)

    obs.obs_property_set_visible(links_path_prop,
                                 obs.obs_data_get_bool(VARIABLES.script_settings,
                                                       PN.PROP_CLIPS_CREATE_LINKS))
    obs.obs_property_set_visible(links_path_warn,
                                 obs.obs_data_get_bool(VARIABLES.script_settings,
                                                       PN.PROP_CLIPS_CREATE_LINKS))

    # ----- Callbacks -----
    obs.obs_property_set_modified_callback(base_path_prop, check_base_path_callback)
    obs.obs_property_set_modified_callback(show_override_folder_prop, update_override_path_prop_visibility)
    obs.obs_property_set_modified_callback(override_path_prop, check_override_path_callback)
    obs.obs_property_set_modified_callback(short_buffer_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(create_links_prop, update_links_path_prop_visibility)
    obs.obs_property_set_modified_callback(links_path_prop, check_clips_links_folder_path_callback)


def setup_clip_naming_settings(group_obj):
    clip_naming_mode_prop = obs.obs_properties_add_list(
        props=group_obj,
        name=PN.PROP_CLIPS_NAMING_MODE,
        description=tr("clip_name"),
        type=obs.OBS_COMBO_TYPE_RADIO,
        format=obs.OBS_COMBO_FORMAT_INT
    )
    obs.obs_property_list_add_int(
        p=clip_naming_mode_prop,
        name=tr("clip_name_active_app"),
        val=ClipNamingModes.CURRENT_PROCESS.value
    )
    obs.obs_property_list_add_int(
        p=clip_naming_mode_prop,
        name=tr("clip_name_most_recorded_app"),
        val=ClipNamingModes.MOST_RECORDED_PROCESS.value
    )
    obs.obs_property_list_add_int(
        p=clip_naming_mode_prop,
        name=tr("clip_name_current_scene"),
        val=ClipNamingModes.CURRENT_SCENE.value
    )

    filename_format_prop = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.PROP_CLIPS_FILENAME_TEMPLATE,
        description=tr("file_name"),
        type=obs.OBS_TEXT_DEFAULT
    )
    obs.obs_property_set_long_description(
        filename_format_prop,
        get_variables_tip())

    filename_error_text = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_CLIPS_FILENAME_TEMPLATE_ERR,
        description=tr("invalid_file_name_format"),
        type=obs.OBS_TEXT_INFO
    )
    obs.obs_property_set_visible(filename_error_text, False)

    obs.obs_property_set_visible(clip_naming_mode_prop, True)
    obs.obs_property_set_visible(filename_format_prop, True)
    obs.obs_property_set_visible(filename_error_text, False)

    obs.obs_property_set_modified_callback(clip_naming_mode_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(filename_format_prop, check_filename_template_callback)


def setup_notifications_settings(group_obj):
    notification_success_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_NOTIFY_CLIPS_ON_SUCCESS,
        description=tr("play_on_success")
    )
    success_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH,
        description=tr("play_on_success_path"),
        type=obs.OBS_PATH_FILE,
        filter=None,
        default_path=str(CONSTANTS.DEFAULT_SUCCESS_SOUND_PATH)
    )

    notification_failure_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_NOTIFY_CLIPS_ON_FAILURE,
        description=tr("play_on_failure")
    )
    failure_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH,
        description=tr("play_on_failure_path"),
        type=obs.OBS_PATH_FILE,
        filter=None,
        default_path=str(CONSTANTS.DEFAULT_FAILURE_SOUND_PATH)
    )
    recording_start_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_NOTIFY_RECORDING_ON_START,
        description=tr("play_recording_start")
    )
    recording_start_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_NOTIFY_RECORDING_ON_START_PATH,
        description=tr("play_recording_start_path"),
        type=obs.OBS_PATH_FILE,
        filter=None,
        default_path=str(CONSTANTS.DEFAULT_RECORDING_START_SOUND_PATH)
    )
    recording_stop_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_NOTIFY_RECORDING_ON_STOP,
        description=tr("play_recording_stop")
    )
    recording_stop_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH,
        description=tr("play_recording_stop_path"),
        type=obs.OBS_PATH_FILE,
        filter=None,
        default_path=str(CONSTANTS.DEFAULT_RECORDING_STOP_SOUND_PATH)
    )

    obs.obs_property_set_visible(success_path_prop,
                                 obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS))
    obs.obs_property_set_visible(failure_path_prop,
                                 obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_FAILURE))
    obs.obs_property_set_visible(recording_start_path_prop,
                                 obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_NOTIFY_RECORDING_ON_START))
    obs.obs_property_set_visible(recording_stop_path_prop,
                                 obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_NOTIFY_RECORDING_ON_STOP))

    # ----- Callbacks ------
    obs.obs_property_set_modified_callback(notification_success_prop, update_notifications_menu_callback)
    obs.obs_property_set_modified_callback(notification_failure_prop, update_notifications_menu_callback)
    obs.obs_property_set_modified_callback(recording_start_prop, update_notifications_menu_callback)
    obs.obs_property_set_modified_callback(recording_stop_prop, update_notifications_menu_callback)
    obs.obs_property_set_modified_callback(success_path_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(failure_path_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(recording_start_path_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(recording_stop_path_prop, persist_settings_callback)

def setup_aliases_settings(group_obj):
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_ALIASES_DESC,
        description=tr("path_specific_names_desc"),
        type=obs.OBS_TEXT_INFO
    )

    err_text_1 = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_ALIASES_INVALID_CHARACTERS,
        description=tr("alias_invalid_chars"),
        type=obs.OBS_TEXT_INFO
    )

    err_text_2 = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_ALIASES_PATH_EXISTS,
        description=tr("alias_path_exists"),
        type=obs.OBS_TEXT_INFO
    )

    err_text_3 = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_ALIASES_INVALID_FORMAT,
        description=tr("alias_invalid_format"),
        type=obs.OBS_TEXT_INFO
    )

    obs.obs_property_set_visible(err_text_1, False)
    obs.obs_property_set_visible(err_text_2, False)
    obs.obs_property_set_visible(err_text_3, False)

    aliases_list = obs.obs_properties_add_editable_list(
        props=group_obj,
        name=PN.PROP_ALIASES_LIST,
        description="",
        type=obs.OBS_EDITABLE_LIST_TYPE_STRINGS,
        filter=None,
        default_path=None
    )

    t = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_ALIASES_FORMAT,
        description=tr("aliases_format_desc", python_exe=sys.executable),
        type=obs.OBS_TEXT_INFO
    )

    aliases_import_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_ALIASES_IMPORT_PATH,
        description=tr("import_rules_file"),
        type=obs.OBS_PATH_FILE,
        filter=None,
        default_path="C:\\"
    )

    obs.obs_properties_add_button(
        group_obj,
        PN.BTN_ALIASES_IMPORT,
        tr("import_path_specific_names"),
        import_aliases_from_json_callback,
    )

    aliases_export_path_prop = obs.obs_properties_add_path(
        props=group_obj,
        name=PN.PROP_ALIASES_EXPORT_PATH,
        description=tr("export_rules_folder"),
        type=obs.OBS_PATH_DIRECTORY,
        filter=None,
        default_path="C:\\"
    )

    obs.obs_properties_add_button(
        group_obj,
        PN.BTN_ALIASES_EXPORT,
        tr("export_path_specific_names"),
        export_aliases_to_json_callback,
    )

    # ----- Callbacks -----
    obs.obs_property_set_modified_callback(aliases_list, update_aliases_callback)
    obs.obs_property_set_modified_callback(aliases_import_path_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(aliases_export_path_prop, persist_settings_callback)


def setup_app_name_rules_settings(group_obj):
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_APP_NAME_RULES_DESC,
        description=tr("exe_name_fixes_desc"),
        type=obs.OBS_TEXT_INFO
    )

    repl_invalid_chars = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_APP_NAME_REPLACEMENTS_INVALID_CHARACTERS,
        description=tr("replacement_invalid_chars"),
        type=obs.OBS_TEXT_INFO
    )
    repl_invalid_format = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_APP_NAME_REPLACEMENTS_INVALID_FORMAT,
        description=tr("replacement_invalid_format"),
        type=obs.OBS_TEXT_INFO
    )
    obs.obs_property_set_visible(repl_invalid_chars, False)
    obs.obs_property_set_visible(repl_invalid_format, False)

    replacement_list = obs.obs_properties_add_editable_list(
        props=group_obj,
        name=PN.PROP_APP_NAME_REPLACEMENTS,
        description="",
        type=obs.OBS_EDITABLE_LIST_TYPE_STRINGS,
        filter=None,
        default_path=None
    )
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_APP_NAME_REPLACEMENTS_DESC,
        description=tr("replacement_format_desc"),
        type=obs.OBS_TEXT_INFO
    )

    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_APP_OTHER_NAMES_TITLE,
        description=tr("send_to_other_desc", other_folder=CONSTANTS.OTHER_FOLDER_NAME),
        type=obs.OBS_TEXT_INFO
    )

    other_names_err = obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_APP_OTHER_NAMES_INVALID,
        description=tr("other_names_invalid"),
        type=obs.OBS_TEXT_INFO
    )
    obs.obs_property_set_visible(other_names_err, False)

    other_names_list = obs.obs_properties_add_editable_list(
        props=group_obj,
        name=PN.PROP_APP_OTHER_NAMES,
        description=tr("apps_saved_to_other", other_folder=CONSTANTS.OTHER_FOLDER_NAME),
        type=obs.OBS_EDITABLE_LIST_TYPE_STRINGS,
        filter=None,
        default_path=None
    )
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_APP_OTHER_NAMES_DESC,
        description=tr("other_names_desc"),
        type=obs.OBS_TEXT_INFO
    )

    obs.obs_property_set_modified_callback(other_names_list, update_other_names_callback)
    obs.obs_property_set_modified_callback(replacement_list, update_name_replacements_callback)


def setup_update_settings(group_obj):
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_UPDATE_STATUS,
        description=get_update_status_text(),
        type=obs.OBS_TEXT_INFO
    )

    obs.obs_properties_add_button(
        group_obj,
        PN.BTN_CHECK_UPDATES,
        tr("check_updates"),
        check_updates_callback
    )

    obs.obs_properties_add_button(
        group_obj,
        PN.BTN_OPEN_LATEST_RELEASE,
        tr("open_latest_release"),
        open_latest_release_callback
    )


def script_properties():
    p = obs.obs_properties_create()  # main properties object
    setup_interface_settings(p)

    # ----- Groups -----
    update_gr = obs.obs_properties_create()
    clip_path_gr = obs.obs_properties_create()
    clip_naming_gr = obs.obs_properties_create()
    notification_gr = obs.obs_properties_create()
    app_rules_gr = obs.obs_properties_create()

    obs.obs_properties_add_group(p, PN.GR_UPDATE_SETTINGS, tr("group_updates"), obs.OBS_GROUP_NORMAL, update_gr)
    obs.obs_properties_add_group(p, PN.GR_CLIPS_PATH_SETTINGS, tr("group_clip_paths"), obs.OBS_GROUP_NORMAL, clip_path_gr)
    obs.obs_properties_add_group(p, PN.GR_CLIP_NAMING_SETTINGS, tr("group_clip_naming"), obs.OBS_GROUP_NORMAL, clip_naming_gr)
    notification_group_prop = obs.obs_properties_add_group(p, PN.GR_SOUND_NOTIFICATION_SETTINGS, tr("group_sound_notifications"), obs.OBS_GROUP_CHECKABLE, notification_gr)
    obs.obs_properties_add_group(p, PN.GR_ALIASES_SETTINGS, tr("group_app_naming_rules"), obs.OBS_GROUP_NORMAL, app_rules_gr)

    # ------ Setup properties ------
    setup_update_settings(update_gr)
    setup_clip_paths_settings(clip_path_gr)
    setup_clip_naming_settings(clip_naming_gr)
    setup_notifications_settings(notification_gr)
    setup_app_name_rules_settings(app_rules_gr)

    if notification_group_prop is not None:
        obs.obs_property_set_modified_callback(notification_group_prop, persist_settings_callback)

    return p


# -------------------- properties_callbacks.py --------------------
def update_update_status_property(props) -> None:
    status_text = obs.obs_properties_get(props, PN.TXT_UPDATE_STATUS)
    if status_text is not None:
        obs.obs_property_set_description(status_text, get_update_status_text())


def update_status_refresh_timer_callback() -> None:
    props = VARIABLES.update_status_props
    if props is not None:
        update_update_status_property(props)

    if not VARIABLES.update_check_in_progress:
        VARIABLES.update_status_refresh_timer_active = False
        VARIABLES.update_status_props = None
        obs.timer_remove(update_status_refresh_timer_callback)


def schedule_update_status_refresh(props) -> None:
    VARIABLES.update_status_props = props
    if VARIABLES.update_status_refresh_timer_active:
        return

    VARIABLES.update_status_refresh_timer_active = True
    obs.timer_add(update_status_refresh_timer_callback, 250)


def check_updates_callback(*args):
    props = args[0] if args else None
    start_update_check_thread("button", props=props)
    return True


def open_latest_release_callback(*args):
    webbrowser.open(VARIABLES.latest_release_url or CONSTANTS.GITHUB_LATEST_RELEASE_URL, 1)


def update_aliases_callback(p, prop, data):
    """
    Checks the list of aliases and updates aliases menu (shows / hides error texts).
    """
    invalid_format_err_text = obs.obs_properties_get(p, PN.TXT_ALIASES_INVALID_FORMAT)
    invalid_chars_err_text = obs.obs_properties_get(p, PN.TXT_ALIASES_INVALID_CHARACTERS)
    path_exists_err_text = obs.obs_properties_get(p, PN.TXT_ALIASES_PATH_EXISTS)

    settings_json: dict = json.loads(obs.obs_data_get_json(data))
    if not settings_json:
        return False

    try:
        load_aliases(settings_json)
        obs.obs_property_set_visible(invalid_format_err_text, False)
        obs.obs_property_set_visible(invalid_chars_err_text, False)
        obs.obs_property_set_visible(path_exists_err_text, False)
        save_persisted_settings_from_obs_data(data)
        return True

    except AliasInvalidCharacters as e:
        obs.obs_property_set_visible(invalid_format_err_text, False)
        obs.obs_property_set_visible(invalid_chars_err_text, True)
        obs.obs_property_set_visible(path_exists_err_text, False)
        index = e.index

    except AliasInvalidFormat as e:
        obs.obs_property_set_visible(invalid_format_err_text, True)
        obs.obs_property_set_visible(invalid_chars_err_text, False)
        obs.obs_property_set_visible(path_exists_err_text, False)
        index = e.index

    except AliasPathAlreadyExists as e:
        obs.obs_property_set_visible(invalid_format_err_text, False)
        obs.obs_property_set_visible(invalid_chars_err_text, False)
        obs.obs_property_set_visible(path_exists_err_text, True)
        index = e.index

    except AliasParsingError as e:
        index = e.index

    # If error in parsing
    corrected_settings_json = repair_editable_list_property(
        data,
        PN.PROP_ALIASES_LIST,
        index,
        build_alias_items_from_runtime_or_defaults()
    )
    if corrected_settings_json is not None:
        load_aliases(corrected_settings_json)
    save_persisted_settings_from_obs_data(data)
    return True


def replace_editable_list(data, prop_name: str, items: list[dict]) -> None:
    new_items_array = obs.obs_data_array_create()

    for index, item in enumerate(items):
        item_data = obs.obs_data_create_from_json(json.dumps(item))
        obs.obs_data_array_insert(new_items_array, index, item_data)
        obs.obs_data_release(item_data)

    obs.obs_data_set_array(data, prop_name, new_items_array)
    obs.obs_data_array_release(new_items_array)


def remove_editable_list_item(data, prop_name: str, index: int) -> None:
    settings_json: dict = json.loads(obs.obs_data_get_json(data))
    items = settings_json.get(prop_name)
    if not isinstance(items, list) or not (0 <= index < len(items)):
        return

    items.pop(index)
    replace_editable_list(data, prop_name, items)


def update_other_names_callback(p, prop, data):
    invalid_err_text = obs.obs_properties_get(p, PN.TXT_APP_OTHER_NAMES_INVALID)

    settings_json: dict = json.loads(obs.obs_data_get_json(data))
    if not settings_json:
        return False

    try:
        load_other_names(settings_json)
        obs.obs_property_set_visible(invalid_err_text, False)
        save_persisted_settings_from_obs_data(data)
        return True
    except OtherNameInvalidCharacters as e:
        obs.obs_property_set_visible(invalid_err_text, True)
        corrected_settings_json = repair_editable_list_property(
            data,
            PN.PROP_APP_OTHER_NAMES,
            e.index,
            build_other_name_items_from_runtime_or_defaults()
        )
        if corrected_settings_json is not None:
            load_other_names(corrected_settings_json)
        save_persisted_settings_from_obs_data(data)
        return True


def update_name_replacements_callback(p, prop, data):
    invalid_format_err_text = obs.obs_properties_get(p, PN.TXT_APP_NAME_REPLACEMENTS_INVALID_FORMAT)
    invalid_chars_err_text = obs.obs_properties_get(p, PN.TXT_APP_NAME_REPLACEMENTS_INVALID_CHARACTERS)

    settings_json: dict = json.loads(obs.obs_data_get_json(data))
    if not settings_json:
        return False

    try:
        load_name_replacements(settings_json)
        obs.obs_property_set_visible(invalid_format_err_text, False)
        obs.obs_property_set_visible(invalid_chars_err_text, False)
        save_persisted_settings_from_obs_data(data)
        return True
    except NameReplacementInvalidFormat as e:
        obs.obs_property_set_visible(invalid_format_err_text, True)
        obs.obs_property_set_visible(invalid_chars_err_text, False)
        corrected_settings_json = repair_editable_list_property(
            data,
            PN.PROP_APP_NAME_REPLACEMENTS,
            e.index,
            build_name_replacement_items_from_runtime_or_defaults()
        )
        if corrected_settings_json is not None:
            load_name_replacements(corrected_settings_json)
        save_persisted_settings_from_obs_data(data)
        return True
    except NameReplacementInvalidCharacters as e:
        obs.obs_property_set_visible(invalid_format_err_text, False)
        obs.obs_property_set_visible(invalid_chars_err_text, True)
        corrected_settings_json = repair_editable_list_property(
            data,
            PN.PROP_APP_NAME_REPLACEMENTS,
            e.index,
            build_name_replacement_items_from_runtime_or_defaults()
        )
        if corrected_settings_json is not None:
            load_name_replacements(corrected_settings_json)
        save_persisted_settings_from_obs_data(data)
        return True


def persist_settings_callback(p, prop, data):
    save_persisted_settings_from_obs_data(data)
    return True


def update_interface_language_callback(p, prop, data):
    if VARIABLES.interface_language_refreshing:
        return True

    VARIABLES.interface_language_refreshing = True
    try:
        save_persisted_settings_from_obs_data(data)
        refresh_localized_properties(p, data)
        apply_settings = getattr(obs, "obs_properties_apply_settings", None)
        if apply_settings is not None:
            with suppress(Exception):
                apply_settings(p, data)
    finally:
        VARIABLES.interface_language_refreshing = False
    return True


def update_clip_naming_settings_visibility_callback(p, prop, data):
    is_visible = obs.obs_data_get_bool(data, PN.PROP_SHOW_CLIP_NAMING_SETTINGS)

    for prop_name in (
        PN.PROP_CLIPS_NAMING_MODE,
        PN.PROP_CLIPS_FILENAME_TEMPLATE,
    ):
        prop_obj = obs.obs_properties_get(p, prop_name)
        if prop_obj is not None:
            obs.obs_property_set_visible(prop_obj, is_visible)

    error_text = obs.obs_properties_get(p, PN.TXT_CLIPS_FILENAME_TEMPLATE_ERR)
    if error_text is not None:
        if not is_visible:
            obs.obs_property_set_visible(error_text, False)
        else:
            try:
                gen_filename("clipname", obs.obs_data_get_string(data, PN.PROP_CLIPS_FILENAME_TEMPLATE))
                obs.obs_property_set_visible(error_text, False)
            except Exception:
                obs.obs_property_set_visible(error_text, True)

    save_persisted_settings_from_obs_data(data)
    return True


def check_filename_template_callback(p, prop, data):
    """
    Checks filename template.
    If template is invalid, shows warning.
    """
    error_text = obs.obs_properties_get(p, PN.TXT_CLIPS_FILENAME_TEMPLATE_ERR)

    try:
        gen_filename("clipname", obs.obs_data_get_string(data, PN.PROP_CLIPS_FILENAME_TEMPLATE))
        obs.obs_property_set_visible(error_text, False)
        save_persisted_settings_from_obs_data(data)
    except Exception:
        obs.obs_property_set_visible(error_text, True)
    return True


def update_override_path_prop_visibility(p, prop, data):
    path_prop = obs.obs_properties_get(p, PN.PROP_CLIPS_OVERRIDE_PATH)
    path_warn_prop = obs.obs_properties_get(p, PN.TXT_CLIPS_OVERRIDE_PATH_WARNING)
    short_buffer_prop = obs.obs_properties_get(p, PN.PROP_SHORT_BUFFER_PERCENT)
    short_buffer_desc = obs.obs_properties_get(p, PN.TXT_SHORT_BUFFER_PERCENT_DESC)
    is_visible = obs.obs_data_get_bool(data, obs.obs_property_name(prop))

    obs.obs_property_set_visible(path_prop, is_visible)
    obs.obs_property_set_visible(path_warn_prop, is_visible)
    obs.obs_property_set_visible(short_buffer_prop, is_visible)
    obs.obs_property_set_visible(short_buffer_desc, is_visible)
    save_persisted_settings_from_obs_data(data)
    return True


def update_links_path_prop_visibility(p, prop, data):
    path_prop = obs.obs_properties_get(p, PN.PROP_CLIPS_LINKS_FOLDER_PATH)
    path_warn_prop = obs.obs_properties_get(p, PN.TXT_CLIPS_LINKS_FOLDER_PATH_WARNING)
    is_visible = obs.obs_data_get_bool(data, obs.obs_property_name(prop))

    obs.obs_property_set_visible(path_prop, is_visible)
    obs.obs_property_set_visible(path_warn_prop, is_visible)
    save_persisted_settings_from_obs_data(data)
    return True


def check_clips_links_folder_path_callback(p, prop, data):
    """
    Checks clips links folder path is in the same disk as OBS recordings path.
    If it's not - sets OBS records path as base path for clips + '_links' and shows warning.
    """
    warn_text = obs.obs_properties_get(p, PN.TXT_CLIPS_LINKS_FOLDER_PATH_WARNING)

    obs_records_path = Path(get_base_path())
    curr_path = Path(obs.obs_data_get_string(data, PN.PROP_CLIPS_LINKS_FOLDER_PATH))

    if not len(curr_path.parts) or obs_records_path.parts[0] == curr_path.parts[0]:
        obs.obs_property_text_set_info_type(warn_text, obs.OBS_TEXT_INFO_WARNING)
    else:
        obs.obs_property_text_set_info_type(warn_text, obs.OBS_TEXT_INFO_ERROR)
        obs.obs_data_set_string(data,
                                PN.PROP_CLIPS_LINKS_FOLDER_PATH,
                                str(obs_records_path / '_links'))
    save_persisted_settings_from_obs_data(data)
    return True


def update_notifications_menu_callback(p, prop, data):
    """
    Updates notifications settings menu.
    If notification is enabled, shows path widget.
    """
    success_path_prop = obs.obs_properties_get(p, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH)
    failure_path_prop = obs.obs_properties_get(p, PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH)
    recording_start_path_prop = obs.obs_properties_get(p, PN.PROP_NOTIFY_RECORDING_ON_START_PATH)
    recording_stop_path_prop = obs.obs_properties_get(p, PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH)

    on_success = obs.obs_data_get_bool(data, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS)
    on_failure = obs.obs_data_get_bool(data, PN.PROP_NOTIFY_CLIPS_ON_FAILURE)
    on_recording_start = obs.obs_data_get_bool(data, PN.PROP_NOTIFY_RECORDING_ON_START)
    on_recording_stop = obs.obs_data_get_bool(data, PN.PROP_NOTIFY_RECORDING_ON_STOP)

    obs.obs_property_set_visible(success_path_prop, on_success)
    obs.obs_property_set_visible(failure_path_prop, on_failure)
    obs.obs_property_set_visible(recording_start_path_prop, on_recording_start)
    obs.obs_property_set_visible(recording_stop_path_prop, on_recording_stop)
    save_persisted_settings_from_obs_data(data)
    return True


def check_base_path_callback(p, prop, data):
    """
    Checks base path is in the same disk as OBS recordings path.
    If it's not - sets OBS records path as base path for clips and shows warning.
    """
    warn_text = obs.obs_properties_get(p, PN.TXT_CLIPS_BASE_PATH_WARNING)

    obs_records_path = Path(get_base_path())
    curr_path = Path(obs.obs_data_get_string(data, PN.PROP_CLIPS_BASE_PATH))

    if not len(curr_path.parts) or obs_records_path.parts[0] == curr_path.parts[0]:
        obs.obs_property_text_set_info_type(warn_text, obs.OBS_TEXT_INFO_WARNING)
    else:
        obs.obs_property_text_set_info_type(warn_text, obs.OBS_TEXT_INFO_ERROR)
        obs.obs_data_set_string(data, PN.PROP_CLIPS_BASE_PATH, str(obs_records_path))
    save_persisted_settings_from_obs_data(data)
    return True


def check_override_path_callback(p, prop, data):
    """
    Checks override save path is in the same disk as OBS recordings path.
    If it's not - sets OBS records path as override path and shows warning.
    """
    warn_text = obs.obs_properties_get(p, PN.TXT_CLIPS_OVERRIDE_PATH_WARNING)

    obs_records_path = Path(get_base_path())
    curr_path = Path(obs.obs_data_get_string(data, PN.PROP_CLIPS_OVERRIDE_PATH))

    if not len(curr_path.parts) or obs_records_path.parts[0] == curr_path.parts[0]:
        obs.obs_property_text_set_info_type(warn_text, obs.OBS_TEXT_INFO_WARNING)
    else:
        obs.obs_property_text_set_info_type(warn_text, obs.OBS_TEXT_INFO_ERROR)
        obs.obs_data_set_string(data, PN.PROP_CLIPS_OVERRIDE_PATH, str(obs_records_path))
    save_persisted_settings_from_obs_data(data)
    return True


def import_aliases_from_json_callback(*args):
    """
    Imports aliases from JSON file.
    """
    path = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_ALIASES_IMPORT_PATH)
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return False

    with open(path, "r", encoding="utf-8") as f:
        data = f.read()

    try:
        data = json.loads(data)
    except json.JSONDecodeError:
        return False

    if not isinstance(data, list):
        return False

    try:
        validate_aliases_list(data)
    except AliasParsingError:
        return False

    arr = obs.obs_data_array_create()
    for index, i in enumerate(data):
        item = obs.obs_data_create_from_json(json.dumps(i))
        obs.obs_data_array_insert(arr, index, item)
        obs.obs_data_release(item)

    obs.obs_data_set_array(VARIABLES.script_settings, PN.PROP_ALIASES_LIST, arr)
    obs.obs_data_array_release(arr)
    load_aliases({PN.PROP_ALIASES_LIST: data})
    save_persisted_settings_from_obs_data(VARIABLES.script_settings)
    return True


def export_aliases_to_json_callback(*args):
    """
    Exports aliases to JSON file.
    """
    path = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_ALIASES_EXPORT_PATH)
    if not path or not os.path.exists(path) or not os.path.isdir(path):
        return False

    aliases_dict = json.loads(obs.obs_data_get_last_json(VARIABLES.script_settings))
    aliases_dict = aliases_dict.get(PN.PROP_ALIASES_LIST) or CONSTANTS.DEFAULT_ALIASES

    with open(os.path.join(path, "obs_arkanoid_replays_aliases.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(aliases_dict, ensure_ascii=False))
    return True


# -------------------- tech.py --------------------
def _print(*values, sep: str | None = None, end: str | None = None, file=None, flush: bool = False):
    str_time = datetime.now().strftime(f"%d.%m.%Y %H:%M:%S")
    print(f"[{str_time}]", *values, sep=sep, end=end, file=file, flush=flush)


def reset_forced_save_state():
    VARIABLES.force_override_save = False
    VARIABLES.half_buffer_save = False
    cancel_forced_save_watchdog()
    with suppress(RuntimeError):
        CONSTANTS.CLIPS_FORCE_MODE_LOCK.release()


def cancel_forced_save_watchdog():
    VARIABLES.forced_save_watchdog_armed = False
    VARIABLES.forced_save_watchdog_timeout_ms = 0
    with suppress(Exception):
        obs.timer_remove(forced_save_watchdog_callback)


def get_forced_save_watchdog_timeout_ms() -> int:
    with suppress(Exception):
        return max(CONSTANTS.FORCED_SAVE_TIMEOUT_MS, (get_replay_buffer_max_time() + 30) * 1000)
    return CONSTANTS.FORCED_SAVE_TIMEOUT_MS


def arm_forced_save_watchdog():
    cancel_forced_save_watchdog()
    timeout_ms = get_forced_save_watchdog_timeout_ms()
    obs.timer_add(forced_save_watchdog_callback, timeout_ms)
    VARIABLES.forced_save_watchdog_armed = True
    VARIABLES.forced_save_watchdog_timeout_ms = timeout_ms


def has_pending_forced_save() -> bool:
    return (CONSTANTS.CLIPS_FORCE_MODE_LOCK.locked() or
            VARIABLES.force_override_save or
            VARIABLES.half_buffer_save)


def forced_save_watchdog_callback():
    timeout_ms = max(VARIABLES.forced_save_watchdog_timeout_ms, CONSTANTS.FORCED_SAVE_TIMEOUT_MS)
    cancel_forced_save_watchdog()
    if has_pending_forced_save():
        _print(f"Forced save timed out after {timeout_ms / 1000:.0f}s. Resetting forced-save state.")
        reset_forced_save_state()


def get_clip_name_fallback() -> str:
    with suppress(Exception):
        scene_name = get_current_scene_name()
        if scene_name and not any(i in scene_name for i in CONSTANTS.FILENAME_PROHIBITED_CHARS):
            _print(f"Falling back to current scene name: {scene_name}")
            return scene_name

    _print(f"Falling back to default clip name: {CONSTANTS.DEFAULT_FALLBACK_CLIP_NAME}")
    return CONSTANTS.DEFAULT_FALLBACK_CLIP_NAME


def get_most_recorded_executable_path() -> Path | None:
    if not VARIABLES.clip_exe_counts:
        return None
    return max(VARIABLES.clip_exe_counts.items(), key=lambda item: item[1])[0]


def get_active_window_pid() -> int | None:
    """
    Gets process ID of the current active window.
    """
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_executable_path(pid: int) -> Path:
    """
    Gets path of process's executable.

    :param pid: process ID.
    :return: Executable path.
    """
    process_handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ

    if not process_handle:
        raise OSError(f"Process {pid} does not exist.")

    filename_buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.psapi.GetModuleFileNameExW(process_handle, None, filename_buffer, len(filename_buffer))
    ctypes.windll.kernel32.CloseHandle(process_handle)
    if result:
        return Path(filename_buffer.value)
    else:
        raise RuntimeError(f"Cannot get executable path for process {pid}.")


def get_active_executable_path(force_refresh: bool = False) -> Path:
    """
    Returns executable path of the current active window, reusing cache when possible.
    """
    pid = get_active_window_pid()
    if force_refresh or pid != VARIABLES.cached_active_window_pid or VARIABLES.cached_active_exe is None:
        try:
            executable_path = get_executable_path(pid)
        except Exception:
            VARIABLES.cached_active_window_pid = None
            VARIABLES.cached_active_exe = None
            raise
        VARIABLES.cached_active_window_pid = pid
        VARIABLES.cached_active_exe = executable_path
        return executable_path
    return VARIABLES.cached_active_exe


def play_sound(path: str | Path):
    """
    Plays sound using windows engine.

    :param path: path to sound (.wav)
    """
    with suppress(Exception):
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


def sanitize_clip_component(value: Any, fallback: str = CONSTANTS.DEFAULT_FALLBACK_CLIP_NAME) -> str:
    text = str(value).strip()
    text = CONSTANTS.SAFE_CLIP_NAME_RE.sub("_", text)
    text = text.rstrip(" .")

    reserved_name = text.split(".", 1)[0].casefold()
    if not text or text in (".", "..") or reserved_name in CONSTANTS.RESERVED_WINDOWS_NAMES:
        text = fallback

    return text


def sanitize_clip_name(value: Any) -> str:
    safe_name = sanitize_clip_component(value)
    if safe_name != str(value):
        _print(f"Clip name sanitized: {value!r} -> {safe_name!r}.")
    return safe_name


def ensure_same_drive_for_rename(source_path: Path | str, target_path: Path | str) -> None:
    source_path = Path(source_path)
    target_path = Path(target_path)
    source_drive = source_path.drive.casefold()
    target_drive = target_path.drive.casefold()

    if source_drive and target_drive and source_drive != target_drive:
        raise OSError(
            f"Cannot move clip across drives: {source_path} -> {target_path}. "
            "Keep OBS Recording Path and Moment Replays paths on the same drive."
        )


def create_hard_link(file_path: Path | str, links_folder: Path | str) -> bool:
    """
    Creates a hard link for `file_path`.

    :param file_path: Original file path.
    :param links_folder: Folder where the link will be created.
    """
    file_path = Path(file_path)
    links_folder = Path(links_folder)
    link_path = links_folder / file_path.name

    if (VARIABLES.last_links_folder != links_folder) or not links_folder.exists():
        os.makedirs(str(links_folder), exist_ok=True)
        VARIABLES.last_links_folder = links_folder

    try:
        os.link(str(file_path), str(link_path))
    except FileExistsError:
        with suppress(Exception):
            if link_path.samefile(file_path):
                return True

        original_link_path = link_path
        link_path = ensure_unique_filename(link_path)
        _print(f"Link path {original_link_path} already exists and points to a different file. Creating {link_path} instead.")
        try:
            os.link(str(file_path), str(link_path))
        except Exception:
            _print(f"Cannot create hard link for clip at {link_path}.")
            _print(traceback.format_exc())
            return False
    except Exception:
        _print(f"Cannot create hard link for clip at {link_path}.")
        _print(traceback.format_exc())
        return False
    return True


def trim_clip_to_last_seconds(file_path: Path | str, duration_seconds: float) -> Path:
    file_path = Path(file_path)
    duration_seconds = max(float(duration_seconds), 1.0)
    temp_path = ensure_unique_filename(file_path.with_name(f"{file_path.stem}.half_tmp{file_path.suffix}"))
    backup_path = ensure_unique_filename(file_path.with_name(f"{file_path.stem}.full_tmp{file_path.suffix}"))

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-sseof",
        f"-{duration_seconds:.3f}",
        "-i",
        str(file_path),
        "-map",
        "0",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(temp_path)
    ]

    _print(f"Trimming clip to the last {duration_seconds:.1f}s using ffmpeg stream copy...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except FileNotFoundError:
        _print("Cannot trim clip: ffmpeg executable not found. Keeping full clip.")
        return file_path
    except Exception:
        _print("Cannot trim clip with ffmpeg. Keeping full clip.")
        _print(traceback.format_exc())
        return file_path

    if result.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
        _print("ffmpeg could not produce a trimmed clip. Keeping full clip.")
        if result.stderr:
            _print(result.stderr.strip())
        with suppress(OSError):
            temp_path.unlink()
        return file_path

    try:
        os.replace(file_path, backup_path)
        try:
            os.replace(temp_path, file_path)
        except Exception:
            os.replace(backup_path, file_path)
            raise
        with suppress(OSError):
            backup_path.unlink()
        _print(f"Trimmed clip saved at {file_path}")
        return file_path
    except Exception:
        _print("Cannot replace the original clip with the trimmed version. Keeping full clip.")
        _print(traceback.format_exc())
        with suppress(OSError):
            temp_path.unlink()
        with suppress(OSError):
            if backup_path.exists() and not file_path.exists():
                os.replace(backup_path, file_path)
        return file_path


def trim_half_clip_async(file_path: Path | str, duration_seconds: float, links_enabled: bool, links_folder: str):
    try:
        final_path = trim_clip_to_last_seconds(file_path, duration_seconds)
        if links_enabled:
            create_hard_link(final_path, links_folder)
        VARIABLES.last_saved_clip_path = final_path
    finally:
        VARIABLES.save_in_progress = False


# -------------------- obs_related.py --------------------
def get_obs_config(section_name: str | None = None,
                   param_name: str | None = None,
                   value_type: type[str, int, bool, float] = str,
                   config_type: ConfigTypes = ConfigTypes.PROFILE):
    """
    Gets a value from OBS config.
    If the value is not set, it will use the default value. If there is no default value, it will return NULL.
    If section_name or param_name are not specified, returns OBS config obj.

    :param section_name: Section name. If not specified, returns the OBS config.
    :param param_name: Parameter name. If not specified, returns the OBS config.
    :param value_type: Type of value (str, int, bool, float).
    :param config_type: Which config search in? (global / profile / user (obs v31 or higher)
    """
    if config_type is ConfigTypes.PROFILE:
        cfg = obs.obs_frontend_get_profile_config()
    elif config_type is ConfigTypes.APP:
        cfg = obs.obs_frontend_get_global_config()
    else:
        if CONSTANTS.OBS_VERSION[0] < 31:
            cfg = obs.obs_frontend_get_global_config()
        else:
            cfg = obs.obs_frontend_get_user_config()

    if not section_name or not param_name:
        return cfg

    functions = {
        str: obs.config_get_string,
        int: obs.config_get_int,
        bool: obs.config_get_bool,
        float: obs.config_get_double
    }

    if value_type not in functions.keys():
        raise ValueError("Unsupported type.")

    return functions[value_type](cfg, section_name, param_name)


def get_last_replay_file_name() -> str:
    """
    Returns the last saved buffer file name.
    """
    replay_buffer = obs.obs_frontend_get_replay_buffer_output()
    if replay_buffer is None:
        raise RuntimeError("Replay buffer output is unavailable.")

    cd = obs.calldata_create()
    try:
        proc_handler = obs.obs_output_get_proc_handler(replay_buffer)
        if proc_handler is None:
            raise RuntimeError("Replay buffer proc handler is unavailable.")
        obs.proc_handler_call(proc_handler, 'get_last_replay', cd)
        path = obs.calldata_string(cd, 'path')
    finally:
        obs.calldata_destroy(cd)
        obs.obs_output_release(replay_buffer)

    if not path:
        raise RuntimeError("OBS did not return the last replay file path.")
    return path


def get_current_scene_name() -> str:
    """
    Returns the current OBS scene name.
    """
    current_scene = obs.obs_frontend_get_current_scene()
    name = obs.obs_source_get_name(current_scene)
    obs.obs_source_release(current_scene)
    return name


def get_replay_buffer_max_time() -> int:
    """
    Returns replay buffer max time from OBS config (in seconds).
    """
    config_mode = get_obs_config("Output", "Mode")
    if config_mode == "Simple":
        return get_obs_config("SimpleOutput", "RecRBTime", int)
    else:
        return get_obs_config("AdvOut", "RecRBTime", int)


def get_base_path(script_settings: Any | None = None) -> Path:
    """
    Returns the base path for clips, either from the script settings or OBS config.

    :param script_settings: Script config. If not provided, base path returns from OBS config.
    :return: The base path as a `Path` object.
    """
    if script_settings is not None:
        script_path = obs.obs_data_get_string(script_settings, PN.PROP_CLIPS_BASE_PATH)
        # If PN.PROP_CLIPS_BASE_PATH is not saved in the script config, then it has a default value,
        # which is the value from the OBS config.
        if script_path:
            return Path(script_path)

    config_mode = get_obs_config("Output", "Mode")
    if config_mode == "Simple":
        return Path(get_obs_config("SimpleOutput", "FilePath"))
    else:
        return Path(get_obs_config("AdvOut", "RecFilePath"))


# -------------------- script_helpers.py --------------------
def notify(success: bool, clip_path: Path | None = None, *, play_audio: bool = True):
    """
    Plays success / failure sound notification if it's enabled in notifications settings.
    """
    sound_notifications_enabled = obs.obs_data_get_bool(VARIABLES.script_settings, PN.GR_SOUND_NOTIFICATION_SETTINGS)

    if success:
        if (play_audio and sound_notifications_enabled and
                obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS)):
            path = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH)
            play_sound(path)
        if clip_path:
            _print(f"Clip saved at {clip_path}")
    else:
        if (play_audio and sound_notifications_enabled and
                obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_FAILURE)):
            path = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH)
            play_sound(path)


def play_recording_sound_notification(enabled_prop: str, path_prop: str) -> None:
    sound_notifications_enabled = obs.obs_data_get_bool(VARIABLES.script_settings, PN.GR_SOUND_NOTIFICATION_SETTINGS)
    if not sound_notifications_enabled:
        return
    if not obs.obs_data_get_bool(VARIABLES.script_settings, enabled_prop):
        return

    path = obs.obs_data_get_string(VARIABLES.script_settings, path_prop)
    if path:
        play_sound(path)


def normalize_rule_name(value: str) -> str:
    return value.strip().casefold()


def get_editable_list_values(script_settings_dict: dict, prop_name: str, default_values: tuple[str, ...]) -> list[str]:
    raw_values = script_settings_dict.get(prop_name)
    if raw_values is None:
        return list(default_values)

    values: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            values.append(str(item.get("value", "")))
        else:
            values.append(str(item))
    return values


def load_other_names(script_settings_dict: dict):
    """
    Loads names of apps that should be grouped into the `Other` folder.
    """
    _print("Loading app names for Other folder...")

    new_other_names = set()
    other_names_list = get_editable_list_values(script_settings_dict,
                                                PN.PROP_APP_OTHER_NAMES,
                                                CONSTANTS.DEFAULT_OTHER_APP_NAMES)

    for index, value in enumerate(other_names_list):
        value = value.strip()
        if not value:
            continue
        if any(i in value for i in (">", "\\", "/", ":")):
            raise OtherNameInvalidCharacters(index)

        new_other_names.add(normalize_rule_name(value))

    VARIABLES.other_names = new_other_names
    _print(f"{len(VARIABLES.other_names)} app names are grouped into {CONSTANTS.OTHER_FOLDER_NAME}.")


def load_name_replacements(script_settings_dict: dict):
    """
    Loads app name replacements for raw executable names.
    """
    _print("Loading app name replacements...")

    new_replacements = {}
    replacements_list = get_editable_list_values(script_settings_dict,
                                                 PN.PROP_APP_NAME_REPLACEMENTS,
                                                 CONSTANTS.DEFAULT_APP_NAME_REPLACEMENTS)

    for index, value in enumerate(replacements_list):
        value = value.strip()
        if not value:
            continue

        spl = value.split(">", 1)
        try:
            raw_name, fixed_name = spl[0].strip(), spl[1].strip()
        except IndexError:
            raise NameReplacementInvalidFormat(index)

        if not raw_name or not fixed_name:
            raise NameReplacementInvalidFormat(index)

        if (any(i in raw_name for i in CONSTANTS.FILENAME_PROHIBITED_CHARS) or
                any(i in fixed_name for i in CONSTANTS.FILENAME_PROHIBITED_CHARS)):
            raise NameReplacementInvalidCharacters(index)

        new_replacements[normalize_rule_name(raw_name)] = fixed_name

    VARIABLES.name_replacements = new_replacements
    _print(f"{len(VARIABLES.name_replacements)} app name replacements are loaded.")


def load_app_name_rules(script_settings_dict: dict):
    load_other_names(script_settings_dict)
    load_name_replacements(script_settings_dict)


def validate_aliases_list(aliases_list: Any) -> dict[Path, str]:
    if not isinstance(aliases_list, (list, tuple)):
        raise AliasInvalidFormat(0)

    new_aliases = {}
    for index, item in enumerate(aliases_list):
        if not isinstance(item, dict):
            raise AliasInvalidFormat(index)

        value = item.get("value")
        if not isinstance(value, str):
            raise AliasInvalidFormat(index)

        spl = value.split(">", 1)
        try:
            path, name = spl[0].strip(), spl[1].strip()
        except IndexError:
            raise AliasInvalidFormat(index)

        if not path or not name:
            raise AliasInvalidFormat(index)

        path = os.path.expandvars(path)
        if any(i in path for i in CONSTANTS.PATH_PROHIBITED_CHARS) or any(i in name for i in CONSTANTS.FILENAME_PROHIBITED_CHARS):
            raise AliasInvalidCharacters(index)

        resolved_path = Path(path)
        if resolved_path in new_aliases.keys():
            raise AliasPathAlreadyExists(index)

        new_aliases[resolved_path] = name

    return new_aliases


def load_aliases(script_settings_dict: dict):
    """
    Loads aliases to `VARIABLES.aliases`.
    Raises exception if path or name are invalid.

    :param script_settings_dict: Script settings as dict.
    """
    _print("Loading aliases...")

    aliases_list = script_settings_dict.get(PN.PROP_ALIASES_LIST)
    if aliases_list is None:
        aliases_list = CONSTANTS.DEFAULT_ALIASES

    new_aliases = validate_aliases_list(aliases_list)
    VARIABLES.aliases = new_aliases
    _print(f"{len(VARIABLES.aliases)} aliases are loaded.")


# -------------------- clipname_gen.py --------------------
def resolve_clip_naming_mode(mode: ClipNamingModes | int | None = None) -> ClipNamingModes:
    mode = obs.obs_data_get_int(VARIABLES.script_settings, PN.PROP_CLIPS_NAMING_MODE) if mode is None else mode
    return mode if isinstance(mode, ClipNamingModes) else ClipNamingModes(mode)


def apply_app_name_replacement(raw_name: str) -> str:
    replacement = VARIABLES.name_replacements.get(normalize_rule_name(raw_name))
    if replacement:
        _print(f"App name replacement found: {raw_name} -> {replacement}.")
        return replacement
    return raw_name


def resolve_app_clip_name(executable_path: str | Path) -> str:
    _print(f"Searching for {executable_path} in aliases list...")
    if alias := get_alias(executable_path, VARIABLES.aliases):
        _print(f"Alias found: {alias}.")
        return alias

    raw_name = Path(executable_path).stem
    _print(f"{executable_path} or its parents weren't found in aliases list. Assigning the name of the executable: {raw_name}")
    return apply_app_name_replacement(raw_name)


def gen_clip_base_name(mode: ClipNamingModes | None = None) -> str:
    """
    Generates the base name of the clip based on the selected naming mode.
    It does NOT generate a new path for the clip or filename, only its base name.

    :param mode: Clip naming mode. If None, the mode is fetched from the script config.
                 If a value is provided, it overrides the configs value.
    :return: The base name of the clip based on the selected naming mode.
    """
    _print("Generating clip base name...")
    mode = resolve_clip_naming_mode(mode)

    if mode in [ClipNamingModes.CURRENT_PROCESS, ClipNamingModes.MOST_RECORDED_PROCESS]:
        try:
            if mode is ClipNamingModes.CURRENT_PROCESS:
                _print("Clip file name depends on the name of an active app (.exe file name) at the moment of clip saving.")
                executable_path = get_active_executable_path(force_refresh=True)
                pid = VARIABLES.cached_active_window_pid
                _print(f"Current active window process ID: {pid}")
                _print(f"Current active window executable: {executable_path}")

            else:
                _print("Clip file name depends on the name of an app (.exe file name) "
                       "that was active most of the time during the clip recording.")
                executable_path = get_most_recorded_executable_path()
                if executable_path is None:
                    executable_path = get_active_executable_path(force_refresh=True)
        except Exception:
            _print("Cannot determine executable path for clip naming.")
            _print(traceback.format_exc())
            return get_clip_name_fallback()

        return resolve_app_clip_name(executable_path)

    else:
        _print("Clip filename depends on the name of the current scene name.")
        return get_current_scene_name()


def get_alias(executable_path: str | Path, aliases_dict: dict[Path, str]) -> str | None:
    """
    Retrieves an alias for the given executable path from the provided dictionary.

    The function first checks if the exact `executable_path` exists in `aliases_dict`.
    If not, it searches for the closest parent directory that is present in the dictionary.

    :param executable_path: A file path or string representing the executable.
    :param aliases_dict: A dictionary where keys are `Path` objects representing executable file paths
                         or directories, and values are their corresponding aliases.
    :return: The corresponding alias if found, otherwise `None`.
    """
    exe_path = Path(executable_path)
    if exe_path in aliases_dict:
        return aliases_dict[exe_path]

    for parent in exe_path.parents:
        if parent in aliases_dict:
            return aliases_dict[parent]


def get_target_clip_folder_name(clip_name: str, mode: ClipNamingModes | int | None = None) -> str:
    mode = resolve_clip_naming_mode(mode)
    if mode in (ClipNamingModes.CURRENT_PROCESS, ClipNamingModes.MOST_RECORDED_PROCESS):
        if normalize_rule_name(clip_name) in VARIABLES.other_names:
            return CONSTANTS.OTHER_FOLDER_NAME
    return clip_name


def gen_filename(base_name: str, template: str, dt: datetime | None = None) -> str:
    """
    Generates a file name based on the template.
    If the template is invalid or formatting fails, raises ValueError.
    If the generated name contains prohibited characters, raises SyntaxError.

    :param base_name: Base name for the file.
    :param template: Template for generating the file name.
    :param dt: Optional datetime object; uses current time if None.
    :return: Formatted file name.
    """
    if not template:
        raise ValueError

    dt = dt or datetime.now()
    filename = template.replace("%NAME", base_name)

    try:
        filename = dt.strftime(filename)
    except Exception as e:
        _print(f"An error occurred while generating the file name using the template {template}.")
        _print(traceback.format_exc())
        raise ValueError from e

    if any(i in filename for i in CONSTANTS.FILENAME_PROHIBITED_CHARS):
        raise SyntaxError
    return filename


def ensure_unique_filename(file_path: str | Path) -> Path:
    """
    Generates a unique filename by adding a numerical suffix if the file already exists.

    :param file_path: A string or Path object representing the target file.
    :return: A unique Path object with a modified name if necessary.
    """
    file_path = Path(file_path)
    parent, stem, suffix = file_path.parent, file_path.stem, file_path.suffix
    counter = 1

    while file_path.exists():
        file_path = parent / f"{stem} ({counter}){suffix}"
        counter += 1

    return file_path


# -------------------- save_buffer.py --------------------
def move_clip_file(mode: ClipNamingModes | None = None, *, create_links: bool = True) -> tuple[str, Path]:
    old_file_path = get_last_replay_file_name()
    _print(f"Old clip file path: {old_file_path}")

    resolved_mode = resolve_clip_naming_mode(mode)
    clip_name = sanitize_clip_name(gen_clip_base_name(resolved_mode))
    ext = old_file_path.split(".")[-1]
    filename_template = obs.obs_data_get_string(VARIABLES.script_settings,
                                                PN.PROP_CLIPS_FILENAME_TEMPLATE)
    filename = gen_filename(clip_name, filename_template) + f".{ext}"

    new_folder = Path(get_base_path(script_settings=VARIABLES.script_settings))
    if obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_CLIPS_SAVE_TO_FOLDER):
        new_folder = new_folder / get_target_clip_folder_name(clip_name, resolved_mode)

    new_path = ensure_unique_filename(new_folder / filename)
    ensure_same_drive_for_rename(old_file_path, new_path)

    if (VARIABLES.last_created_clip_folder != new_folder) or not new_folder.exists():
        os.makedirs(str(new_folder), exist_ok=True)
        VARIABLES.last_created_clip_folder = new_folder
    _print(f"New clip file path: {new_path}")

    os.rename(old_file_path, str(new_path))
    _print("Clip file successfully moved.")
    with suppress(OSError):
        os.utime(new_folder)

    if create_links and obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_CLIPS_CREATE_LINKS):
        links_folder = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_CLIPS_LINKS_FOLDER_PATH)
        create_hard_link(new_path, links_folder)
    return clip_name, new_path


def move_clip_file_override() -> tuple[str, Path]:
    old_file_path = get_last_replay_file_name()
    _print(f"Old clip file path: {old_file_path}")

    override_path = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_CLIPS_OVERRIDE_PATH)
    override_folder = Path(override_path) if override_path else get_base_path(script_settings=VARIABLES.script_settings)

    if (VARIABLES.last_created_clip_folder != override_folder) or not override_folder.exists():
        ensure_same_drive_for_rename(old_file_path, override_folder / Path(old_file_path).name)
        os.makedirs(str(override_folder), exist_ok=True)
        VARIABLES.last_created_clip_folder = override_folder

    new_path = ensure_unique_filename(override_folder / Path(old_file_path).name)
    ensure_same_drive_for_rename(old_file_path, new_path)
    _print(f"New clip file path: {new_path}")

    os.rename(old_file_path, str(new_path))
    _print("Clip file successfully moved.")
    with suppress(OSError):
        os.utime(override_folder)
    return Path(old_file_path).stem, new_path


def save_buffer_to_override_folder():
    """
    Sends a request to save the replay buffer and moves the clip to the override folder.
    Can only be called using hotkeys.
    """
    if not obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS):
        return

    if not obs.obs_frontend_replay_buffer_active():
        return

    if not CONSTANTS.CLIPS_FORCE_MODE_LOCK.acquire(blocking=False):
        return

    try:
        VARIABLES.force_override_save = True
        obs.obs_frontend_replay_buffer_save()
        arm_forced_save_watchdog()
    except Exception:
        _print("Cannot trigger replay buffer save for override folder.")
        _print(traceback.format_exc())
        reset_forced_save_state()


def save_half_buffer():
    """
    Sends a request to save the replay buffer and then trims the saved clip to the last half of the buffer.
    Can only be called using hotkeys.
    """
    if not obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS):
        return

    if not obs.obs_frontend_replay_buffer_active():
        return

    if not CONSTANTS.CLIPS_FORCE_MODE_LOCK.acquire(blocking=False):
        return

    try:
        VARIABLES.force_override_save = False
        VARIABLES.half_buffer_save = True
        obs.obs_frontend_replay_buffer_save()
        arm_forced_save_watchdog()
    except Exception:
        _print("Cannot trigger replay buffer save for half-buffer hotkey.")
        _print(traceback.format_exc())
        reset_forced_save_state()


def is_save_in_progress() -> bool:
    return VARIABLES.save_in_progress or has_pending_forced_save()


def cancel_pending_open_request() -> None:
    VARIABLES.open_last_video_requested = False
    VARIABLES.open_last_video_wait_ticks = 0
    with suppress(Exception):
        obs.timer_remove(open_last_video_wait_callback)


def open_last_video_wait_callback() -> None:
    """
    Polls until the in-progress replay save finishes (or a safety deadline is
    reached), then opens the freshly created clip. Runs on the OBS timer thread.
    """
    VARIABLES.open_last_video_wait_ticks -= 1
    if is_save_in_progress() and VARIABLES.open_last_video_wait_ticks > 0:
        return
    with suppress(Exception):
        obs.timer_remove(open_last_video_wait_callback)
    if VARIABLES.open_last_video_requested:
        VARIABLES.open_last_video_requested = False
        open_last_saved_video_now()


def open_last_saved_video():
    """
    Opens the most recently saved video. If a replay save is currently being
    processed, waits for it to finish first and then opens the just-created clip
    (without blocking the OBS thread). Can only be called using hotkeys.
    """
    if VARIABLES.open_last_video_requested:
        # Already waiting for an in-progress save; ignore repeated presses.
        return

    if is_save_in_progress():
        VARIABLES.open_last_video_requested = True
        interval = CONSTANTS.OPEN_LAST_VIDEO_WAIT_INTERVAL_MS
        max_wait_ms = get_forced_save_watchdog_timeout_ms() + 5000
        VARIABLES.open_last_video_wait_ticks = max(1, (max_wait_ms + interval - 1) // interval)
        _print("A replay save is in progress; the last video will open once it finishes.")
        obs.timer_add(open_last_video_wait_callback, interval)
        return

    open_last_saved_video_now()


def open_last_saved_video_now():
    """
    Opens the newest existing file among the last clip this script saved,
    OBS's last recording, and OBS's last replay, with the default application.
    """
    candidates = []
    if VARIABLES.last_saved_clip_path is not None:
        candidates.append(Path(VARIABLES.last_saved_clip_path))

    for getter_name in ("obs_frontend_get_last_recording", "obs_frontend_get_last_replay"):
        getter = getattr(obs, getter_name, None)
        if getter is None:
            continue
        with suppress(Exception):
            raw_path = getter()
            if raw_path:
                candidates.append(Path(raw_path))

    existing = []
    seen = set()
    for candidate in candidates:
        with suppress(Exception):
            key = candidate.resolve()
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                existing.append(candidate)

    if not existing:
        _print("Open last video: no saved video found yet.")
        return

    try:
        target = max(existing, key=lambda p: p.stat().st_mtime)
        _print(f"Opening last video: {target}")
        os.startfile(str(target))
    except Exception:
        _print("Cannot open last video.")
        _print(traceback.format_exc())


# -------------------- obs_events_callbacks.py --------------------
def on_recording_started_callback(event):
    if event != obs.OBS_FRONTEND_EVENT_RECORDING_STARTED:
        return

    play_recording_sound_notification(
        PN.PROP_NOTIFY_RECORDING_ON_START,
        PN.PROP_NOTIFY_RECORDING_ON_START_PATH
    )


def on_recording_stopped_callback(event):
    if event != obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED:
        return

    play_recording_sound_notification(
        PN.PROP_NOTIFY_RECORDING_ON_STOP,
        PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH
    )


def on_buffer_recording_started_callback(event):
    """
    Resets and starts recording executables history.
    """
    if event != obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_STARTED:
        return

    # Reset and restart exe history
    VARIABLES.clip_exe_history = deque([], maxlen=get_replay_buffer_max_time())
    VARIABLES.clip_exe_counts = {}
    VARIABLES.cached_active_window_pid = None
    VARIABLES.cached_active_exe = None
    VARIABLES.last_created_clip_folder = None
    VARIABLES.last_links_folder = None
    VARIABLES.save_in_progress = False
    cancel_pending_open_request()
    _print(f"Exe history deque created. Maxlen={VARIABLES.clip_exe_history.maxlen}.")
    obs.timer_add(append_clip_exe_history, 1000)


def on_buffer_recording_stopped_callback(event):
    """
    Stops recording executables history.
    """
    if event != obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_STOPPED:
        return

    obs.timer_remove(append_clip_exe_history)
    if VARIABLES.clip_exe_history is not None:
        VARIABLES.clip_exe_history.clear()
    VARIABLES.clip_exe_counts = {}
    VARIABLES.cached_active_window_pid = None
    VARIABLES.cached_active_exe = None
    VARIABLES.last_created_clip_folder = None
    VARIABLES.last_links_folder = None
    VARIABLES.save_in_progress = False
    cancel_pending_open_request()
    reset_forced_save_state()


def on_buffer_save_callback(event):
    if event != obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_SAVED:
        return

    _print(f"{'SAVING BUFFER':->50}")
    VARIABLES.save_in_progress = True

    force_override = VARIABLES.force_override_save
    half_buffer_save = VARIABLES.half_buffer_save
    try:
        if force_override:
            _, path = move_clip_file_override()
        else:
            _, path = move_clip_file(create_links=not half_buffer_save)
    except Exception:
        _print("An error occurred while moving file to the new destination.")
        _print(traceback.format_exc())
        notify(False)
        reset_forced_save_state()
        VARIABLES.save_in_progress = False
        _print("-" * 50)
        return

    VARIABLES.last_saved_clip_path = path

    trimming_started = False
    if half_buffer_save:
        short_percent = obs.obs_data_get_int(VARIABLES.script_settings, PN.PROP_SHORT_BUFFER_PERCENT)
        short_percent = min(max(short_percent, 5), 100)
        half_duration = get_replay_buffer_max_time() * short_percent / 100
        links_enabled = obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_CLIPS_CREATE_LINKS)
        links_folder = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_CLIPS_LINKS_FOLDER_PATH)
        try:
            Thread(
                target=trim_half_clip_async,
                args=(path, half_duration, links_enabled, links_folder),
                daemon=True
            ).start()
            trimming_started = True
        except Exception:
            _print("Cannot start short-clip trimming thread.")
            _print(traceback.format_exc())

    notify(True, path)
    reset_forced_save_state()
    if not trimming_started:
        VARIABLES.save_in_progress = False
    _print("-" * 50)


# -------------------- other_callbacks.py --------------------
def append_clip_exe_history():
    """
    Adds current active executable path in clip exe history.
    """
    if VARIABLES.clip_exe_history is None or not VARIABLES.clip_exe_history.maxlen:
        return

    with suppress(Exception):
        exe = get_active_executable_path()
        if len(VARIABLES.clip_exe_history) == VARIABLES.clip_exe_history.maxlen:
            dropped_exe = VARIABLES.clip_exe_history.pop()
            dropped_count = VARIABLES.clip_exe_counts.get(dropped_exe, 0)
            if dropped_count <= 1:
                VARIABLES.clip_exe_counts.pop(dropped_exe, None)
            else:
                VARIABLES.clip_exe_counts[dropped_exe] = dropped_count - 1

        VARIABLES.clip_exe_history.appendleft(exe)
        VARIABLES.clip_exe_counts[exe] = VARIABLES.clip_exe_counts.get(exe, 0) + 1


# -------------------- hotkeys.py --------------------
def build_default_hotkey_data(key_name: str, *, alt: bool = False, shift: bool = False,
                              control: bool = False, command: bool = False):
    data_array = obs.obs_data_array_create()
    data = obs.obs_data_create()
    obs.obs_data_set_string(data, "key", key_name)
    if alt:
        obs.obs_data_set_bool(data, "alt", True)
    if shift:
        obs.obs_data_set_bool(data, "shift", True)
    if control:
        obs.obs_data_set_bool(data, "control", True)
    if command:
        obs.obs_data_set_bool(data, "command", True)
    obs.obs_data_array_push_back(data_array, data)
    obs.obs_data_release(data)
    return data_array


def load_hotkeys():
    keys = (
        (PN.HK_SAVE_BUFFER_HALF, "[Moment Replays] Save short clip",
         lambda pressed: save_half_buffer() if pressed else None),

        (PN.HK_SAVE_BUFFER_OVERRIDE, "[Moment Replays] Save buffer (override folder)",
         lambda pressed: save_buffer_to_override_folder() if pressed else None),

        (PN.HK_OPEN_LAST_VIDEO, "[Moment Replays] Open last saved video",
         lambda pressed: open_last_saved_video() if pressed else None)
    )

    for key_name, key_desc, key_callback in keys:
        key_id = obs.obs_hotkey_register_frontend(key_name, key_desc, key_callback)
        VARIABLES.hotkey_ids.update({key_name: key_id})
        key_data = obs.obs_data_get_array(VARIABLES.script_settings, key_name)
        if key_name == PN.HK_SAVE_BUFFER_HALF and not obs.obs_data_has_user_value(VARIABLES.script_settings, key_name):
            default_data = build_default_hotkey_data("OBS_KEY_F10", control=True)
            obs.obs_hotkey_load(key_id, default_data)
            obs.obs_data_array_release(default_data)
        elif key_name == PN.HK_SAVE_BUFFER_OVERRIDE and not obs.obs_data_has_user_value(VARIABLES.script_settings, key_name):
            default_data = build_default_hotkey_data("OBS_KEY_F10", alt=True)
            obs.obs_hotkey_load(key_id, default_data)
            obs.obs_data_array_release(default_data)
        else:
            obs.obs_hotkey_load(key_id, key_data)
        if key_data is not None:
            obs.obs_data_array_release(key_data)


# -------------------- obs_script_other.py --------------------
def build_editable_list_item(value: str) -> dict[str, Any]:
    return {"value": value, "selected": False, "hidden": False}


def build_editable_list_items(values: list[str]) -> list[dict[str, Any]]:
    return [build_editable_list_item(value) for value in values]


def build_alias_items_from_runtime_or_defaults() -> list[dict[str, Any]]:
    if VARIABLES.aliases:
        return build_editable_list_items([f"{path} > {name}" for path, name in VARIABLES.aliases.items()])
    return [dict(item) for item in CONSTANTS.DEFAULT_ALIASES]


def build_other_name_items_from_runtime_or_defaults() -> list[dict[str, Any]]:
    values = sorted(VARIABLES.other_names) if VARIABLES.other_names else list(CONSTANTS.DEFAULT_OTHER_APP_NAMES)
    return build_editable_list_items(values)


def build_name_replacement_items_from_runtime_or_defaults() -> list[dict[str, Any]]:
    if VARIABLES.name_replacements:
        values = [f"{raw_name} > {fixed_name}" for raw_name, fixed_name in VARIABLES.name_replacements.items()]
    else:
        values = list(CONSTANTS.DEFAULT_APP_NAME_REPLACEMENTS)
    return build_editable_list_items(values)


def get_obs_data_json_dict(data) -> dict[str, Any] | None:
    try:
        settings_json = json.loads(obs.obs_data_get_json(data))
    except Exception:
        return None
    return settings_json if isinstance(settings_json, dict) else None


def unregister_frontend_event_callbacks() -> None:
    remove_event_callback = getattr(obs, "obs_frontend_remove_event_callback", None)
    if remove_event_callback is None:
        return

    for callback in (
        on_recording_started_callback,
        on_recording_stopped_callback,
        on_buffer_save_callback,
        on_buffer_recording_started_callback,
        on_buffer_recording_stopped_callback
    ):
        with suppress(Exception):
            remove_event_callback(callback)


def register_frontend_event_callbacks() -> None:
    unregister_frontend_event_callbacks()
    obs.obs_frontend_add_event_callback(on_recording_started_callback)
    obs.obs_frontend_add_event_callback(on_recording_stopped_callback)
    obs.obs_frontend_add_event_callback(on_buffer_save_callback)
    obs.obs_frontend_add_event_callback(on_buffer_recording_started_callback)
    obs.obs_frontend_add_event_callback(on_buffer_recording_stopped_callback)


def get_existing_persisted_settings_path() -> Path:
    if CONSTANTS.SETTINGS_PERSIST_PATH.exists():
        return CONSTANTS.SETTINGS_PERSIST_PATH
    if CONSTANTS.LEGACY_SETTINGS_PERSIST_PATH.exists():
        return CONSTANTS.LEGACY_SETTINGS_PERSIST_PATH
    if CONSTANTS.LEGACY_APP_RULES_PERSIST_PATH.exists():
        return CONSTANTS.LEGACY_APP_RULES_PERSIST_PATH
    return CONSTANTS.SETTINGS_PERSIST_PATH


def normalize_persisted_alias_values(raw_values: list[Any]) -> list[str]:
    values = [str(value).strip() for value in raw_values if str(value).strip()]
    validate_aliases_list([build_editable_list_item(value) for value in values])
    return values


def normalize_persisted_other_names(raw_values: list[Any]) -> list[str]:
    values: list[str] = []
    for index, value in enumerate(raw_values):
        value = str(value).strip()
        if not value:
            continue
        if any(i in value for i in (">", "\\", "/", ":")):
            raise OtherNameInvalidCharacters(index)
        values.append(value)
    return values


def normalize_persisted_name_replacements(raw_values: list[Any]) -> list[str]:
    values: list[str] = []
    for index, value in enumerate(raw_values):
        value = str(value).strip()
        if not value:
            continue

        spl = value.split(">", 1)
        try:
            raw_name, fixed_name = spl[0].strip(), spl[1].strip()
        except IndexError:
            raise NameReplacementInvalidFormat(index)

        if not raw_name or not fixed_name:
            raise NameReplacementInvalidFormat(index)

        if (any(i in raw_name for i in CONSTANTS.FILENAME_PROHIBITED_CHARS) or
                any(i in fixed_name for i in CONSTANTS.FILENAME_PROHIBITED_CHARS)):
            raise NameReplacementInvalidCharacters(index)

        values.append(f"{raw_name} > {fixed_name}")
    return values


def get_default_persisted_list(prop_name: str) -> list[str]:
    return list(PERSISTED_LIST_DEFAULTS[prop_name])


def get_last_valid_persisted_list(prop_name: str, persisted_settings: dict[str, Any]) -> list[str]:
    return list(persisted_settings.get(prop_name, get_default_persisted_list(prop_name)))


def normalize_default_sound_path(prop_name: str, raw_value: str | None) -> str:
    value = raw_value if isinstance(raw_value, str) else ""
    default_value = DEFAULT_SOUND_PATHS[prop_name]
    legacy_values = LEGACY_DEFAULT_SOUND_PATHS.get(prop_name, {""})
    legacy_values_folded = {legacy.casefold() for legacy in legacy_values}

    if not value.strip() or value.casefold() in legacy_values_folded:
        return default_value
    return value


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        with suppress(OSError):
            temp_path.unlink()
        raise


def normalize_current_persisted_list_value(settings_json: dict[str, Any],
                                           prop_name: str,
                                           normalizer,
                                           error_types,
                                           persisted_settings: dict[str, Any]) -> list[str]:
    raw_values = settings_json.get(prop_name)
    if raw_values is None:
        return get_default_persisted_list(prop_name)

    fallback_values = get_last_valid_persisted_list(prop_name, persisted_settings)
    if not isinstance(raw_values, list):
        _print(f"Current {prop_name} settings are invalid. Keeping the last valid persisted values for this list.")
        return fallback_values

    try:
        return normalizer(get_editable_list_values(settings_json, prop_name, ()))
    except error_types:
        _print(f"Current {prop_name} settings are invalid. Keeping the last valid persisted values for this list.")
        return fallback_values


def load_persisted_settings() -> dict[str, Any]:
    settings_path = get_existing_persisted_settings_path()
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        _print(f"Cannot read persisted settings from {settings_path}. Falling back to defaults.")
        _print(traceback.format_exc())
        return {}

    if not isinstance(payload, dict):
        _print(f"Persisted settings at {settings_path} are invalid. Falling back to defaults.")
        return {}

    persisted_settings: dict[str, Any] = {}

    for prop_name, default_value in PERSISTED_STRING_DEFAULTS.items():
        raw_value = payload.get(prop_name)
        if isinstance(raw_value, str):
            persisted_settings[prop_name] = raw_value

    for prop_name in DEFAULT_SOUND_PATHS.keys():
        persisted_settings[prop_name] = normalize_default_sound_path(prop_name, persisted_settings.get(prop_name))

    for prop_name in PERSISTED_BOOL_DEFAULTS.keys():
        raw_value = payload.get(prop_name)
        if isinstance(raw_value, bool):
            persisted_settings[prop_name] = raw_value

    for prop_name in PERSISTED_INT_DEFAULTS.keys():
        raw_value = payload.get(prop_name)
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            persisted_settings[prop_name] = raw_value

    if PN.PROP_ALIASES_LIST in payload:
        raw_aliases = payload.get(PN.PROP_ALIASES_LIST)
        if isinstance(raw_aliases, list):
            try:
                persisted_settings[PN.PROP_ALIASES_LIST] = normalize_persisted_alias_values(raw_aliases)
            except AliasParsingError:
                _print(f"Persisted {PN.PROP_ALIASES_LIST} at {settings_path} is invalid. Falling back to defaults for this list.")

    if PN.PROP_APP_OTHER_NAMES in payload:
        raw_other_names = payload.get(PN.PROP_APP_OTHER_NAMES)
        if isinstance(raw_other_names, list):
            try:
                persisted_settings[PN.PROP_APP_OTHER_NAMES] = normalize_persisted_other_names(raw_other_names)
            except OtherNameInvalidCharacters:
                _print(f"Persisted {PN.PROP_APP_OTHER_NAMES} at {settings_path} is invalid. Falling back to defaults for this list.")

    if PN.PROP_APP_NAME_REPLACEMENTS in payload:
        raw_name_replacements = payload.get(PN.PROP_APP_NAME_REPLACEMENTS)
        if isinstance(raw_name_replacements, list):
            try:
                persisted_settings[PN.PROP_APP_NAME_REPLACEMENTS] = normalize_persisted_name_replacements(raw_name_replacements)
            except AppRuleParsingError:
                _print(f"Persisted {PN.PROP_APP_NAME_REPLACEMENTS} at {settings_path} is invalid. Falling back to defaults for this list.")

    return persisted_settings


def save_persisted_settings_from_settings_dict(settings_json: dict) -> None:
    persisted_settings = load_persisted_settings()
    payload = {
        "version": CONSTANTS.SETTINGS_SCHEMA_VERSION,
    }

    for prop_name, default_value in PERSISTED_STRING_DEFAULTS.items():
        payload[prop_name] = default_value

    for prop_name, default_value in PERSISTED_BOOL_DEFAULTS.items():
        payload[prop_name] = default_value

    for prop_name, default_value in PERSISTED_INT_DEFAULTS.items():
        payload[prop_name] = default_value

    payload[PN.PROP_ALIASES_LIST] = get_default_persisted_list(PN.PROP_ALIASES_LIST)
    payload[PN.PROP_APP_OTHER_NAMES] = get_default_persisted_list(PN.PROP_APP_OTHER_NAMES)
    payload[PN.PROP_APP_NAME_REPLACEMENTS] = get_default_persisted_list(PN.PROP_APP_NAME_REPLACEMENTS)

    for prop_name in PERSISTED_STRING_DEFAULTS.keys():
        raw_value = settings_json.get(prop_name)
        if isinstance(raw_value, str):
            payload[prop_name] = raw_value

    for prop_name in DEFAULT_SOUND_PATHS.keys():
        payload[prop_name] = normalize_default_sound_path(prop_name, payload.get(prop_name))

    for prop_name in PERSISTED_BOOL_DEFAULTS.keys():
        raw_value = settings_json.get(prop_name)
        if isinstance(raw_value, bool):
            payload[prop_name] = raw_value

    payload[PN.PROP_CLIPS_SAVE_TO_FOLDER] = True

    for prop_name in PERSISTED_INT_DEFAULTS.keys():
        raw_value = settings_json.get(prop_name)
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            payload[prop_name] = raw_value

    payload[PN.PROP_ALIASES_LIST] = normalize_current_persisted_list_value(
        settings_json,
        PN.PROP_ALIASES_LIST,
        normalize_persisted_alias_values,
        (AliasParsingError,),
        persisted_settings
    )
    payload[PN.PROP_APP_OTHER_NAMES] = normalize_current_persisted_list_value(
        settings_json,
        PN.PROP_APP_OTHER_NAMES,
        normalize_persisted_other_names,
        (AppRuleParsingError,),
        persisted_settings
    )
    payload[PN.PROP_APP_NAME_REPLACEMENTS] = normalize_current_persisted_list_value(
        settings_json,
        PN.PROP_APP_NAME_REPLACEMENTS,
        normalize_persisted_name_replacements,
        (AppRuleParsingError,),
        persisted_settings
    )

    try:
        write_json_atomic(CONSTANTS.SETTINGS_PERSIST_PATH, payload)
    except Exception:
        _print(f"Cannot write persisted settings to {CONSTANTS.SETTINGS_PERSIST_PATH}.")
        _print(traceback.format_exc())


def save_persisted_settings_from_obs_data(data, *, allow_when_disabled: bool = False) -> None:
    if not allow_when_disabled and not VARIABLES.sidecar_persist_enabled:
        return

    settings_json = get_obs_data_json_dict(data)
    if settings_json is None:
        return

    try:
        save_persisted_settings_from_settings_dict(settings_json)
    except Exception:
        _print(f"Cannot persist script settings to {CONSTANTS.SETTINGS_PERSIST_PATH}.")
        _print(traceback.format_exc())


def repair_editable_list_property(data, prop_name: str, index: int, fallback_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    settings_json = get_obs_data_json_dict(data)
    items = settings_json.get(prop_name) if settings_json is not None else None
    if isinstance(items, list) and 0 <= index < len(items):
        items = list(items)
        items.pop(index)
    else:
        items = list(fallback_items)

    replace_editable_list(data, prop_name, items)
    return get_obs_data_json_dict(data)


def set_default_editable_list(settings, prop_name: str, values: tuple[str, ...]) -> None:
    arr = obs.obs_data_array_create()
    for index, value in enumerate(values):
        data = obs.obs_data_create_from_json(json.dumps(build_editable_list_item(value)))
        obs.obs_data_array_insert(arr, index, data)
        obs.obs_data_release(data)

    obs.obs_data_set_default_array(settings, prop_name, arr)
    if not obs.obs_data_has_user_value(settings, prop_name):
        obs.obs_data_set_array(settings, prop_name, arr)
    obs.obs_data_array_release(arr)


def script_defaults(s):
    _print("Loading default values...")
    VARIABLES.sidecar_persist_enabled = False
    persisted_settings = load_persisted_settings()

    for prop_name, default_value in PERSISTED_STRING_DEFAULTS.items():
        obs.obs_data_set_default_string(s, prop_name, persisted_settings.get(prop_name, default_value))

    for prop_name, default_value in PERSISTED_BOOL_DEFAULTS.items():
        obs.obs_data_set_default_bool(s, prop_name, persisted_settings.get(prop_name, default_value))

    for prop_name, default_value in PERSISTED_INT_DEFAULTS.items():
        obs.obs_data_set_default_int(s, prop_name, persisted_settings.get(prop_name, default_value))

    set_default_editable_list(
        s,
        PN.PROP_ALIASES_LIST,
        tuple(persisted_settings.get(PN.PROP_ALIASES_LIST, list(PERSISTED_LIST_DEFAULTS[PN.PROP_ALIASES_LIST])))
    )
    set_default_editable_list(
        s,
        PN.PROP_APP_OTHER_NAMES,
        tuple(persisted_settings.get(PN.PROP_APP_OTHER_NAMES, list(PERSISTED_LIST_DEFAULTS[PN.PROP_APP_OTHER_NAMES])))
    )
    set_default_editable_list(
        s,
        PN.PROP_APP_NAME_REPLACEMENTS,
        tuple(persisted_settings.get(PN.PROP_APP_NAME_REPLACEMENTS,
                                     list(PERSISTED_LIST_DEFAULTS[PN.PROP_APP_NAME_REPLACEMENTS])))
    )
    obs.obs_data_set_bool(s, PN.PROP_CLIPS_SAVE_TO_FOLDER, True)
    _print("The default values are set.")


def script_update(settings):
    _print("Updating script...")

    VARIABLES.sidecar_persist_enabled = False
    VARIABLES.script_settings = settings
    obs.obs_data_set_bool(settings, PN.PROP_CLIPS_SAVE_TO_FOLDER, True)
    VARIABLES.last_created_clip_folder = None
    VARIABLES.last_links_folder = None
    try:
        json_settings = json.loads(obs.obs_data_get_json(settings))
        load_aliases(json_settings)
        load_app_name_rules(json_settings)
    except (AliasParsingError, AppRuleParsingError):
        _print("Saved aliases or app rules are invalid. Falling back to defaults.")
        load_aliases({})
        load_app_name_rules({})
    VARIABLES.sidecar_persist_enabled = True
    _print("Script updated")


def script_save(settings):
    _print("Saving script...")
    save_persisted_settings_from_obs_data(settings, allow_when_disabled=True)
    for key_name in VARIABLES.hotkey_ids:
        k = obs.obs_hotkey_save(VARIABLES.hotkey_ids[key_name])
        obs.obs_data_set_array(settings, key_name, k)
        if k is not None:
            obs.obs_data_array_release(k)
    _print("Script saved")


def script_load(script_settings):
    _print("Loading script...")
    VARIABLES.sidecar_persist_enabled = False
    VARIABLES.script_settings = script_settings
    if not IS_WINDOWS:
        _print("Moment Replays is Windows-only; the script is loaded but its active features are disabled on this platform.")
        return
    obs.obs_data_set_bool(script_settings, PN.PROP_CLIPS_SAVE_TO_FOLDER, True)
    VARIABLES.clip_exe_counts = {}
    VARIABLES.forced_save_watchdog_armed = False
    VARIABLES.forced_save_watchdog_timeout_ms = 0
    VARIABLES.last_created_clip_folder = None
    VARIABLES.last_links_folder = None
    json_settings = json.loads(obs.obs_data_get_json(script_settings))
    try:
        load_aliases(json_settings)
        load_app_name_rules(json_settings)
    except (AliasParsingError, AppRuleParsingError):
        _print("Saved aliases or app rules are invalid. Falling back to defaults.")
        load_aliases({})
        load_app_name_rules({})

    register_frontend_event_callbacks()
    load_hotkeys()

    if obs.obs_frontend_replay_buffer_active():
        on_buffer_recording_started_callback(obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_STARTED)

    VARIABLES.sidecar_persist_enabled = True
    start_update_check_thread()
    _print("Script loaded.")


def script_unload():
    VARIABLES.sidecar_persist_enabled = False
    unregister_frontend_event_callbacks()
    if VARIABLES.script_settings is not None:
        save_persisted_settings_from_obs_data(VARIABLES.script_settings, allow_when_disabled=True)
    obs.timer_remove(append_clip_exe_history)
    obs.timer_remove(update_status_refresh_timer_callback)
    VARIABLES.update_status_refresh_timer_active = False
    VARIABLES.update_status_props = None
    if VARIABLES.clip_exe_history is not None:
        VARIABLES.clip_exe_history.clear()
    VARIABLES.clip_exe_counts = {}
    VARIABLES.other_names = set()
    VARIABLES.name_replacements = {}
    VARIABLES.cached_active_window_pid = None
    VARIABLES.cached_active_exe = None
    VARIABLES.last_created_clip_folder = None
    VARIABLES.last_links_folder = None
    VARIABLES.last_saved_clip_path = None
    VARIABLES.save_in_progress = False
    cancel_pending_open_request()
    reset_forced_save_state()

    _print("Script unloaded.")


def script_description():
    return f"""
<div style="font-size: 22pt; text-align: center; margin: 0 0 6px 0;">
Moment Replays 
</div>

<div style="font-size: 8pt; text-align: left; margin: 0 0 4px 0;">
        {tr("script_description_summary")}
</div>

<div style="font-size: 8pt; text-align: left; margin: 0;">
v{CONSTANTS.VERSION}  |  by Moment
</div>
"""
