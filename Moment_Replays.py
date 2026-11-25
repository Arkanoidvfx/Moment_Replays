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
import hashlib
import html
import re
import json
import traceback
import urllib.error
import urllib.request
import webbrowser
import os
import struct
import subprocess
import tempfile
import time
import wave
import winsound
from array import array
from enum import Enum
from threading import Event
from threading import Lock
from threading import Thread
from threading import current_thread
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
WORKER_THREAD_NAME = "MomentReplays-worker"  # every Thread this script starts; see _print


class CONSTANTS:
    VERSION = "1.7"
    OBS_VERSION_STRING = obs.obs_get_version_string()
    OBS_VERSION_RE = re.compile(r'(\d+)\.(\d+)\.(\d+)')
    OBS_VERSION = [int(i) for i in OBS_VERSION_RE.match(OBS_VERSION_STRING).groups()]
    CLIPS_FORCE_MODE_LOCK = Lock()
    UPDATE_CHECK_LOCK = Lock()
    FORCED_SAVE_TIMEOUT_MS = 30000
    OPEN_LAST_VIDEO_WAIT_INTERVAL_MS = 250
    ALT_RECORDING_WATCHDOG_MS = 8000
    FOREGROUND_TICK_MS = 1000
    AUTO_SCENE_DEBOUNCE_S = 1.5
    BLACK_LUMA_THRESHOLD = 12      # brightest R/G/B value (0..255) at or below which a frame is "black"
    BLACK_FALLBACK_S = 2.0         # black this long on the Game scene -> show Desktop
    BLACK_COOLDOWN_S = 60.0        # then keep that process off the Game scene this long
    BLACK_SAMPLE_SIZE = (32, 18)   # downscaled readback of the game capture
    OTHER_OBS_CHECK_S = 2.5        # how often auto scene looks for another running OBS
    OBS_PROCESS_NAME = "obs64.exe"
    MARK_FEEDBACK_MS = 200
    TIMELINE_LOG_MAXLEN = 10000
    MARKERS_MAXLEN = 1000
    MOMENT_SCHEMA = "moment.clip/1"
    MOMENT_METADATA_SUFFIX = ".moment.json"
    # Clip info inside the MP4 (contract: moment.clip/1 JSON in the `synopsis` tag).
    INFO_TAG_PADDING = 256          # spaces after the JSON, so it can be rewritten in place
    INFO_RETRY_S = 10.0             # OBS reports "stopped" before its file writer has finished
    INFO_RETRY_INTERVAL_S = 0.5
    # Clip end = a few frames after the save/stop was requested; see pick_clip_end(). Calibrated live on
    # OBS 33.0.1 (NVENC and x264, 30 and 60 fps): B-frame reorder plus the packet that ends the clip.
    REPLAY_END_FRAMES = 3.0
    RECORDING_END_FRAMES = 1.5
    CLIP_CREATED_LAG_S = 0.25       # replay file created minus clip end, until a key save shows the real value
    SAVE_KEY_MAX_LEAD_S = 5.0       # a save-key press older than this did not cause the file (x264: 1.2 s, AMF: 1.8 s)
    CREATED_MAX_AGE_S = 600.0       # writing a big buffer to a slow disk takes a while; older is not this file
    KEY_POLL_S = 0.004              # 250 Hz: 1 to 3 % of one core while a game is in front (measured)
    KEY_LOG_MAXLEN = 100_000        # press intervals per key
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
    SETTINGS_SCHEMA_VERSION = 6
    LEGACY_APP_RULES_PERSIST_PATH = Path(__file__).with_name("arkanoid_replays.app_rules.json")
    GITHUB_PROJECT_URL = "https://github.com/Arkanoidvfx/Moment_Replays"
    GITHUB_LATEST_RELEASE_URL = f"{GITHUB_PROJECT_URL}/releases/latest"
    FOLDER_GUIDE_URLS = {
        "en": f"{GITHUB_PROJECT_URL}/blob/main/FOLDERS.md",
        "ru": f"{GITHUB_PROJECT_URL}/blob/main/FOLDERS.ru.md",
    }
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
    alt_recording_pending = False
    saved_recording_path: str | None = None
    alt_recording_watchdog_armed = False
    # Moment metadata: (wall_ts, app, exe, scene) change points, F8 marker wall times.
    timeline_log: deque = deque(maxlen=CONSTANTS.TIMELINE_LOG_MAXLEN)
    moment_markers: deque = deque(maxlen=CONSTANTS.MARKERS_MAXLEN)
    deferred_logs: deque = deque(maxlen=1000)  # worker-thread log lines, printed by foreground_tick
    buffer_started_at: float | None = None
    recording_started_at: float | None = None
    recording_stop_at: float | None = None      # OBS_FRONTEND_EVENT_RECORDING_STOPPING
    recording_active = False
    buffer_active = False
    buffer_max_time = 0
    # Clip info anchor and key recorder (see pick_clip_end, KeyRecorder)
    save_requested_at: float | None = None      # script hotkeys: just before obs_frontend_replay_buffer_save()
    save_key_bindings: tuple = ()               # OBS's own "Save Replay" keys: (virtual key, modifier names)
    save_key_problem = ""                       # why there are none, as last logged
    save_key_presses: deque = deque(maxlen=64)  # wall times those keys went down
    created_lag = CONSTANTS.CLIP_CREATED_LAG_S  # learned from the last save with a known request
    pending_info_writes: set = set()            # worker threads still writing clip info
    unloading = Event()
    record_inputs = False                       # cached: the key thread must not call obspython
    key_recorder = None
    # Auto scene (Game/Desktop)
    auto_scene_machine = None
    auto_scene_source = None
    auto_scene_blocked = False
    auto_scene_switch_in_flight = False
    auto_scene_status = ""
    auto_scene_showing_held = False   # our obs_source_inc_showing ref on the game capture
    auto_scene_rehook_phase = ""      # "", "pending" (wait for Desktop), "released" (ref dropped)
    black_guard = None                # BlackFrameGuard, lives for the whole OBS session
    luma_sampler = None               # CaptureLumaSampler, created on first use
    luma_sampler_disabled = False
    other_obs: str | None = None      # description of another running OBS, if any
    other_obs_checked_at: float | None = None
    other_obs_paused = False
    other_obs_scan_running = False
    other_obs_answered_at: float | None = None
    other_obs_error_logged = False
    sidecar_persist_enabled = False
    update_check_in_progress = False
    update_status_props = None
    update_status_refresh_timer_active = False
    latest_release_url = CONSTANTS.GITHUB_LATEST_RELEASE_URL
    update_status_text = ""
    update_status_key = "update_status_initial"
    update_status_args = {"version": CONSTANTS.VERSION}
    interface_language_refreshing = False
    sound_dir: tempfile.TemporaryDirectory | None = None  # quieter copies of the sounds, see scaled_sound_path


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
    GR_MOMENT_SETTINGS = "moment_settings"

    # Moment capture settings (shared contract with the installer and Moment Player)
    PROP_AUTO_SCENE_ENABLED = "auto_scene_enabled"
    TXT_AUTO_SCENE_DESC = "auto_scene_desc"
    PROP_AUTO_SCENE_GAME = "auto_scene_game"
    PROP_AUTO_SCENE_DESKTOP = "auto_scene_desktop"
    PROP_AUTO_SCENE_GAME_SOURCE = "auto_scene_game_source"
    PROP_WRITE_MOMENT_METADATA = "write_moment_metadata"
    TXT_WRITE_MOMENT_METADATA_DESC = "write_moment_metadata_desc"
    PROP_RECORD_INPUTS = "record_inputs"
    TXT_RECORD_INPUTS_DESC = "record_inputs_desc"

    # Clips path settings
    PROP_CLIPS_BASE_PATH = "clips_base_path"
    TXT_NEXT_CLIP = "next_clip"
    TXT_FOLDER_PROBLEMS = "folder_problems"
    BTN_USE_OBS_FOLDER = "use_obs_folder_btn"
    BTN_CHECK_FOLDERS = "check_folders_btn"
    BTN_FOLDER_GUIDE = "folder_guide_btn"
    PROP_SHOW_MORE_FOLDERS = "show_more_folders"
    PROP_SHOW_OVERRIDE_FOLDER_SETTINGS = "show_override_folder_settings"
    PROP_CLIPS_OVERRIDE_PATH = "clips_override_path"
    TXT_CLIPS_OVERRIDE_PATH_DESC = "clips_override_path_desc"
    PROP_RECORDING_FOLDER = "recording_alt_folder"
    TXT_RECORDING_FOLDER_DESC = "recording_alt_folder_desc"
    PROP_SHOW_CLIP_NAMING_SETTINGS = "show_clip_naming_settings"
    PROP_CLIPS_NAMING_MODE = "clips_naming_mode"
    TXT_CLIPS_HOTKEY_TIP = "clips_hotkey_tip"
    PROP_CLIPS_FILENAME_TEMPLATE = "clips_filename_template"
    TXT_CLIPS_FILENAME_TEMPLATE_ERR = "clips_filename_template_err"
    PROP_CLIPS_SAVE_TO_FOLDER = "clips_save_to_folder"
    TXT_CLIPS_SAVE_TO_FOLDER_DESC = "clips_save_to_folder_desc"
    PROP_CLIPS_CREATE_LINKS = "clips_create_links"
    PROP_CLIPS_LINKS_FOLDER_PATH = "clips_links_folder_path"
    TXT_CLIPS_LINKS_FOLDER_PATH_DESC = "clips_links_folder_path_desc"

    # Sound notification settings
    PROP_NOTIFY_CLIPS_ON_SUCCESS = "notify_clips_on_success"
    PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH = "notify_clips_on_success_path"
    PROP_NOTIFY_CLIPS_ON_FAILURE = "notify_clips_on_failure"
    PROP_NOTIFY_CLIPS_ON_FAILURE_PATH = "notify_clips_on_failure_path"
    PROP_NOTIFY_RECORDING_ON_START = "notify_recording_on_start"
    PROP_NOTIFY_RECORDING_ON_START_PATH = "notify_recording_on_start_path"
    PROP_NOTIFY_RECORDING_ON_STOP = "notify_recording_on_stop"
    PROP_NOTIFY_RECORDING_ON_STOP_PATH = "notify_recording_on_stop_path"
    PROP_SOUND_VOLUME = "sound_volume"
    BTN_TEST_SOUND = "test_sound_btn"

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
    HK_RECORD_ALT = "record_alternative_folder"
    HK_MARK_MOMENT = "mark_moment"

PN = PropertiesNames

# Default bindings applied only when OBS has no saved binding for the hotkey yet.
HOTKEY_DEFAULTS = {
    PN.HK_SAVE_BUFFER_HALF: ("OBS_KEY_F10", {"control": True}),
    PN.HK_SAVE_BUFFER_OVERRIDE: ("OBS_KEY_F10", {"alt": True}),
    PN.HK_OPEN_LAST_VIDEO: ("OBS_KEY_F10", {"control": True, "alt": True}),
    PN.HK_MARK_MOMENT: ("OBS_KEY_F8", {}),
}

PERSISTED_STRING_DEFAULTS = {
    PN.PROP_INTERFACE_LANGUAGE: "en",
    PN.PROP_CLIPS_BASE_PATH: "",
    PN.PROP_CLIPS_OVERRIDE_PATH: "",
    PN.PROP_RECORDING_FOLDER: "",
    PN.PROP_CLIPS_FILENAME_TEMPLATE: CONSTANTS.DEFAULT_FILENAME_FORMAT,
    PN.PROP_CLIPS_LINKS_FOLDER_PATH: str(CONSTANTS.DEFAULT_LINKS_PATH),
    PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH: str(CONSTANTS.DEFAULT_SUCCESS_SOUND_PATH),
    PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH: str(CONSTANTS.DEFAULT_FAILURE_SOUND_PATH),
    PN.PROP_NOTIFY_RECORDING_ON_START_PATH: str(CONSTANTS.DEFAULT_RECORDING_START_SOUND_PATH),
    PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH: str(CONSTANTS.DEFAULT_RECORDING_STOP_SOUND_PATH),
    PN.PROP_ALIASES_IMPORT_PATH: "",
    PN.PROP_ALIASES_EXPORT_PATH: "",
    PN.PROP_AUTO_SCENE_GAME: "Game",
    PN.PROP_AUTO_SCENE_DESKTOP: "Desktop",
    PN.PROP_AUTO_SCENE_GAME_SOURCE: "Game Capture",
}

PERSISTED_BOOL_DEFAULTS = {
    PN.PROP_CLIPS_SAVE_TO_FOLDER: True,
    PN.PROP_CLIPS_CREATE_LINKS: False,
    PN.GR_SOUND_NOTIFICATION_SETTINGS: True,
    PN.PROP_NOTIFY_CLIPS_ON_SUCCESS: True,
    PN.PROP_NOTIFY_CLIPS_ON_FAILURE: True,
    PN.PROP_NOTIFY_RECORDING_ON_START: False,
    PN.PROP_NOTIFY_RECORDING_ON_STOP: False,
    PN.PROP_SHOW_MORE_FOLDERS: False,  # only what the panel shows; hidden settings keep working
    PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS: True,
    PN.PROP_SHOW_CLIP_NAMING_SETTINGS: False,
    # Opt-in: only the installer's fresh sidecar turns it on (see load_persisted_settings).
    PN.PROP_AUTO_SCENE_ENABLED: False,
    PN.PROP_WRITE_MOMENT_METADATA: True,
    PN.PROP_RECORD_INPUTS: False,  # a key logger: opt-in only
}

PERSISTED_INT_DEFAULTS = {
    PN.PROP_CLIPS_NAMING_MODE: ClipNamingModes.MOST_RECORDED_PROCESS.value,
    PN.PROP_SHORT_BUFFER_PERCENT: 40,
    PN.PROP_SOUND_VOLUME: 100,
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

NOTIFICATION_SOUNDS = (
    (PN.PROP_NOTIFY_CLIPS_ON_SUCCESS, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH),
    (PN.PROP_NOTIFY_CLIPS_ON_FAILURE, PN.PROP_NOTIFY_CLIPS_ON_FAILURE_PATH),
    (PN.PROP_NOTIFY_RECORDING_ON_START, PN.PROP_NOTIFY_RECORDING_ON_START_PATH),
    (PN.PROP_NOTIFY_RECORDING_ON_STOP, PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH),
)

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
            "sounds, short clips, Game/Desktop auto scenes, clip info for Moment Player, and update checks."
        ),
        "interface_language": "Interface language",
        "hotkey_settings_tip": "All hotkeys can be changed in OBS Settings -> Hotkeys.",
        "group_clip_paths": "Clip folders",
        "group_clip_naming": "Clip naming",
        "group_sound_notifications": "Sounds",
        "group_app_naming_rules": "Naming rules",
        "group_updates": "Updates",
        "base_folder": "Clips folder",
        "next_clip": "Next clip: <b>{path}</b>",
        "next_clip_other": "Apps from the \"{other_folder}\" list: <b>{path}</b>",
        "next_clip_game": "game",
        "next_clip_scene": "scene",
        "folders_ok": "All folders checked: no problems.",
        "folder_not_found": "Not found: <b>{path}</b>. Connect the drive or choose another folder.",
        "folder_not_writable": "Can't write to <b>{path}</b>. Choose another folder.",
        "folder_wrong_drive": (
            "Wrong drive: OBS records to {drive}, so <b>{path}</b> must be on {drive} too. "
            "Choose a folder on {drive} or change the recording path in OBS."
        ),
        "clips_stay_in_obs_folder": "Until then clips stay in the OBS recording folder.",
        "use_obs_folder": "Use the OBS recording folder",
        "check_folders": "Check folders",
        "folder_guide": "Folder guide",
        "show_more_folders": "More folders",
        "show_override_folder_settings": "Extra hotkeys: second folder, short clip, separate recordings",
        "override_folder": "Second clips folder",
        "override_folder_desc": (
            "Used by the \"Save buffer (override folder)\" hotkey. "
            "Same drive as OBS recordings. Empty: the clips folder."
        ),
        "recording_folder": "Recordings folder",
        "recording_folder_desc": (
            "Used by the \"Start/stop recording (alternative folder)\" hotkey. Any drive. Empty: the clips folder."
        ),
        "short_clip_duration": "Short clip",
        "short_clip_duration_desc": (
            "The \"Save short clip\" hotkey keeps the last part of the replay. "
            "40% of 1 minute = 24 seconds. Needs ffmpeg in PATH."
        ),
        "create_hard_links": "Also collect all clips in one folder",
        "links_folder": "Shared folder",
        "links_folder_desc": (
            "Every clip saved to the clips folder appears here too and takes no extra space (hard link). "
            "Same drive as OBS recordings."
        ),
        "clip_name": "Clip name",
        "clip_name_active_app": "Active app at save time",
        "clip_name_most_recorded_app": "App active for most of the replay",
        "clip_name_current_scene": "Current scene",
        "file_name": "File name",
        "invalid_file_name_format": "<font color=\"red\"><pre> Invalid file name format.</pre></font>",
        "sound_volume": "Volume",
        "test_sound": "Play test sound",
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
        "other_names_invalid": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Use app names only.</span><br/>"
            "<span style=\"color: orange\">No paths, no separators like <code>&gt; / \\ :</code>.</span>"
            "</div>"
        ),
        "apps_saved_to_other": "Apps saved to the \"{other_folder}\" folder",
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
        "group_moments": "Moments",
        "auto_scene_enabled": "Auto-switch Game / Desktop scenes",
        "auto_scene_desc": (
            "Shows scene \"{game}\" once \"{source}\" has hooked a fullscreen game, otherwise \"{desktop}\". "
            "Stays off unless both scenes and the game capture source exist, and pauses while another OBS "
            "is running so it never takes that OBS's game hook."
        ),
        "write_moment_metadata": "Store clip info inside the clip",
        "write_moment_metadata_desc": (
            "Game, app timeline, Mark-moment markers, audio tracks and encoder settings for Moment Player, "
            "stored inside the MP4 itself (its synopsis tag). If that is not possible (another container or an "
            "unusual MP4), a .moment.json file is saved next to the clip instead."
        ),
        "record_inputs": "Record key presses (shown over clips in Moment Player)",
        "record_inputs_desc": (
            "Records when you press 1-5, Q W E R T, A S D F G, Z X C V, Shift, Ctrl, Alt, Space, Tab and the mouse "
            "buttons, and nothing else, but only while your game is the window in front. The press times are stored "
            "inside every clip and recording you save and travel with it: anyone who gets the clip can see them. "
            "Off by default."
        ),
    },
    "ru": {
        "script_description_summary": (
            "Сохраняет replay-клипы с именами по приложениям или сценам, правилами по путям и .exe, "
            "папкой Other, звуками, короткими клипами, автосценами Game/Desktop, данными о клипе для Moment Player "
            "и проверкой обновлений."
        ),
        "interface_language": "Язык интерфейса",
        "hotkey_settings_tip": "Все хоткеи можно изменить в OBS: Settings -> Hotkeys.",
        "group_clip_paths": "Папки клипов",
        "group_clip_naming": "Имена клипов",
        "group_sound_notifications": "Звуки",
        "group_app_naming_rules": "Правила имен",
        "group_updates": "Обновление",
        "base_folder": "Папка клипов",
        "next_clip": "Следующий клип: <b>{path}</b>",
        "next_clip_other": "Приложения из списка «{other_folder}»: <b>{path}</b>",
        "next_clip_game": "игра",
        "next_clip_scene": "сцена",
        "folders_ok": "Все папки проверены, проблем нет.",
        "folder_not_found": "Не найдено: <b>{path}</b>. Подключите диск или выберите другую папку.",
        "folder_not_writable": "Нет доступа на запись: <b>{path}</b>. Выберите другую папку.",
        "folder_wrong_drive": (
            "Не тот диск: OBS пишет на {drive}, поэтому <b>{path}</b> тоже должна быть на {drive}. "
            "Выберите папку на {drive} или смените путь записи в OBS."
        ),
        "clips_stay_in_obs_folder": "Пока что клипы остаются в папке записи OBS.",
        "use_obs_folder": "Взять папку записи OBS",
        "check_folders": "Проверить папки",
        "folder_guide": "Как настроить папки",
        "show_more_folders": "Другие папки",
        "show_override_folder_settings": "Дополнительные хоткеи: вторая папка, короткий клип, отдельные записи",
        "override_folder": "Вторая папка клипов",
        "override_folder_desc": (
            "Для хоткея «Save buffer (override folder)». "
            "Тот же диск, что и записи OBS. Пусто: папка клипов."
        ),
        "recording_folder": "Папка записей",
        "recording_folder_desc": (
            "Для хоткея «Start/stop recording (alternative folder)». Любой диск. Пусто: папка клипов."
        ),
        "short_clip_duration": "Короткий клип",
        "short_clip_duration_desc": (
            "Хоткей «Save short clip» оставляет конец повтора. "
            "40% от 1 минуты = 24 секунды. Нужен ffmpeg в PATH."
        ),
        "create_hard_links": "Собирать все клипы ещё и в одной папке",
        "links_folder": "Общая папка",
        "links_folder_desc": (
            "Каждый клип из папки клипов появится и здесь, без затрат места (hard link). "
            "Тот же диск, что и записи OBS."
        ),
        "clip_name": "Имя клипа",
        "clip_name_active_app": "Активное приложение в момент сохранения",
        "clip_name_most_recorded_app": "Приложение, активное большую часть replay",
        "clip_name_current_scene": "Текущая сцена",
        "file_name": "Имя файла",
        "invalid_file_name_format": "<font color=\"red\"><pre> Неверный формат имени файла.</pre></font>",
        "sound_volume": "Громкость",
        "test_sound": "Проверить звук",
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
        "other_names_invalid": (
            "<div style=\"font-size: 13px\">"
            "<span style=\"color: red\">Используй только имена приложений.</span><br/>"
            "<span style=\"color: orange\">Без путей и разделителей вроде <code>&gt; / \\ :</code>.</span>"
            "</div>"
        ),
        "apps_saved_to_other": "Приложения, сохраняемые в папку «{other_folder}»",
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
        "group_moments": "Моменты",
        "auto_scene_enabled": "Автопереключение сцен Game / Desktop",
        "auto_scene_desc": (
            "Показывает сцену \"{game}\", когда \"{source}\" захватил полноэкранную игру, иначе \"{desktop}\". "
            "Не работает, пока нет обеих сцен и источника захвата игры, и ставится на паузу, пока запущен "
            "другой OBS, чтобы не забирать у него захват игры."
        ),
        "write_moment_metadata": "Хранить данные о клипе внутри клипа",
        "write_moment_metadata_desc": (
            "Игра, хронология приложений, метки «Отметить момент», аудиодорожки и настройки энкодера для Moment Player "
            "записываются прямо в MP4 (тег synopsis). Если это невозможно (другой контейнер или необычный MP4), "
            "рядом с клипом создаётся файл .moment.json."
        ),
        "record_inputs": "Записывать нажатия клавиш (показываются поверх клипа в Moment Player)",
        "record_inputs_desc": (
            "Записывает моменты нажатий 1-5, Q W E R T, A S D F G, Z X C V, Shift, Ctrl, Alt, Space, Tab и кнопок мыши, "
            "и ничего больше, и только пока игра - окно на переднем плане. Время нажатий хранится внутри каждого "
            "сохранённого клипа и записи и передаётся вместе с ними: его увидит каждый, кому вы отправите клип. "
            "По умолчанию выключено."
        ),
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
        _print(re.sub(r"<br\s*/?>", " ", re.sub(r"<(?!br)[^>]+>", "", tr(key, lang=lang, **kwargs))))  # UI HTML


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
        # start_update_check_thread() already logged "Checking..." before handing over the lock.
        set_update_status_key("update_status_checking", version=CONSTANTS.VERSION, lang=lang,
                              log=not lock_acquired)
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
        Thread(target=check_for_updates, args=(source, lang), kwargs={"lock_acquired": True}, daemon=True,
               name=WORKER_THREAD_NAME).start()
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
    set_property_description(clip_paths, PN.BTN_USE_OBS_FOLDER, tr("use_obs_folder", data=data))
    set_property_description(clip_paths, PN.BTN_CHECK_FOLDERS, tr("check_folders", data=data))
    set_property_description(clip_paths, PN.BTN_FOLDER_GUIDE, tr("folder_guide", data=data))
    set_property_description(clip_paths, PN.PROP_SHOW_MORE_FOLDERS, tr("show_more_folders", data=data))
    set_property_description(clip_paths, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS,
                             tr("show_override_folder_settings", data=data))
    set_property_description(clip_paths, PN.PROP_CLIPS_OVERRIDE_PATH, tr("override_folder", data=data))
    set_property_description(clip_paths, PN.PROP_RECORDING_FOLDER, tr("recording_folder", data=data))
    set_property_description(clip_paths, PN.PROP_SHORT_BUFFER_PERCENT, tr("short_clip_duration", data=data))
    set_property_description(clip_paths, PN.TXT_SHORT_BUFFER_PERCENT_DESC, tr("short_clip_duration_desc", data=data))
    set_property_description(clip_paths, PN.PROP_CLIPS_CREATE_LINKS, tr("create_hard_links", data=data))
    set_property_description(clip_paths, PN.PROP_CLIPS_LINKS_FOLDER_PATH, tr("links_folder", data=data))
    set_property_description(clip_paths, PN.TXT_APP_OTHER_NAMES_INVALID, tr("other_names_invalid", data=data))
    set_property_description(clip_paths, PN.PROP_APP_OTHER_NAMES,
                             tr("apps_saved_to_other", data=data, other_folder=CONSTANTS.OTHER_FOLDER_NAME))
    set_property_description(clip_paths, PN.TXT_APP_OTHER_NAMES_DESC, tr("other_names_desc", data=data))
    if clip_paths is not None:
        refresh_folder_properties(clip_paths, data)

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
    set_property_description(notifications, PN.PROP_SOUND_VOLUME, tr("sound_volume", data=data))
    set_property_description(notifications, PN.BTN_TEST_SOUND, tr("test_sound", data=data))
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

    set_property_description(props, PN.GR_MOMENT_SETTINGS, tr("group_moments", data=data))
    moments = get_group_content(props, PN.GR_MOMENT_SETTINGS)
    set_property_description(moments, PN.PROP_AUTO_SCENE_ENABLED, tr("auto_scene_enabled", data=data))
    set_property_description(moments, PN.TXT_AUTO_SCENE_DESC, auto_scene_desc_text(data))
    set_property_description(moments, PN.PROP_WRITE_MOMENT_METADATA, tr("write_moment_metadata", data=data))
    set_property_description(moments, PN.TXT_WRITE_MOMENT_METADATA_DESC, tr("write_moment_metadata_desc", data=data))
    set_property_description(moments, PN.PROP_RECORD_INPUTS, tr("record_inputs", data=data))
    set_property_description(moments, PN.TXT_RECORD_INPUTS_DESC, tr("record_inputs_desc", data=data))

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


def setup_clip_paths_settings(group_obj):
    add_int_slider = getattr(obs, "obs_properties_add_int_slider", None) or obs.obs_properties_add_int

    def add_folder(name: str, label: str, default_path: Path):
        return obs.obs_properties_add_path(
            props=group_obj,
            name=name,
            description=tr(label),
            type=obs.OBS_PATH_DIRECTORY,
            filter=None,
            default_path=str(default_path)
        )

    def add_info(name: str, text: str = ""):
        return obs.obs_properties_add_text(
            props=group_obj,
            name=name,
            description=text,
            type=obs.OBS_TEXT_INFO
        )

    def add_switch(name: str, label: str):
        return obs.obs_properties_add_bool(props=group_obj, name=name, description=tr(label))

    # ----- The clips folder; texts and visibility come from refresh_folder_properties() -----
    folder_props = [add_folder(PN.PROP_CLIPS_BASE_PATH, "base_folder", CONSTANTS.DEFAULT_CLIPS_BASE_PATH)]
    add_info(PN.TXT_NEXT_CLIP)
    problems_text = add_info(PN.TXT_FOLDER_PROBLEMS)
    obs.obs_property_text_set_info_type(problems_text, obs.OBS_TEXT_INFO_ERROR)
    obs.obs_properties_add_button(group_obj, PN.BTN_USE_OBS_FOLDER, tr("use_obs_folder"), use_obs_folder_callback)
    obs.obs_properties_add_button(group_obj, PN.BTN_CHECK_FOLDERS, tr("check_folders"), check_folders_callback)
    obs.obs_properties_add_button(group_obj, PN.BTN_FOLDER_GUIDE, tr("folder_guide"), open_folder_guide_callback)
    folder_props.append(add_switch(PN.PROP_SHOW_MORE_FOLDERS, "show_more_folders"))

    # ----- Extra hotkeys -----
    folder_props.append(add_switch(PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS, "show_override_folder_settings"))
    folder_props.append(add_folder(PN.PROP_CLIPS_OVERRIDE_PATH, "override_folder", CONSTANTS.DEFAULT_OVERRIDE_PATH))
    add_info(PN.TXT_CLIPS_OVERRIDE_PATH_DESC)
    folder_props.append(add_folder(PN.PROP_RECORDING_FOLDER, "recording_folder", CONSTANTS.DEFAULT_CLIPS_BASE_PATH))
    add_info(PN.TXT_RECORDING_FOLDER_DESC)
    short_buffer_prop = add_int_slider(
        props=group_obj,
        name=PN.PROP_SHORT_BUFFER_PERCENT,
        description=tr("short_clip_duration"),
        min=5, max=100,
        step=5
    )
    obs.obs_property_int_set_suffix(short_buffer_prop, " %")
    add_info(PN.TXT_SHORT_BUFFER_PERCENT_DESC, tr("short_clip_duration_desc"))

    # ----- Links -----
    folder_props.append(add_switch(PN.PROP_CLIPS_CREATE_LINKS, "create_hard_links"))
    folder_props.append(add_folder(PN.PROP_CLIPS_LINKS_FOLDER_PATH, "links_folder", CONSTANTS.DEFAULT_LINKS_PATH))
    add_info(PN.TXT_CLIPS_LINKS_FOLDER_PATH_DESC)

    # ----- Apps that go to the Other folder -----
    other_names_err = add_info(PN.TXT_APP_OTHER_NAMES_INVALID, tr("other_names_invalid"))
    obs.obs_property_set_visible(other_names_err, False)
    other_names_list = obs.obs_properties_add_editable_list(
        props=group_obj,
        name=PN.PROP_APP_OTHER_NAMES,
        description=tr("apps_saved_to_other", other_folder=CONSTANTS.OTHER_FOLDER_NAME),
        type=obs.OBS_EDITABLE_LIST_TYPE_STRINGS,
        filter=None,
        default_path=None
    )
    add_info(PN.TXT_APP_OTHER_NAMES_DESC, tr("other_names_desc"))

    refresh_folder_properties(group_obj, VARIABLES.script_settings)

    # ----- Callbacks -----
    for prop in folder_props:
        obs.obs_property_set_modified_callback(prop, update_folders_callback)
    obs.obs_property_set_modified_callback(short_buffer_prop, persist_slider_callback)
    obs.obs_property_set_modified_callback(other_names_list, update_other_names_callback)


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

    obs.obs_property_set_modified_callback(clip_naming_mode_prop, update_naming_mode_callback)
    obs.obs_property_set_modified_callback(filename_format_prop, check_filename_template_callback)


def setup_notifications_settings(group_obj):
    add_int_slider = getattr(obs, "obs_properties_add_int_slider", None) or obs.obs_properties_add_int
    volume_prop = add_int_slider(
        props=group_obj,
        name=PN.PROP_SOUND_VOLUME,
        description=tr("sound_volume"),
        min=0, max=100,
        step=5
    )
    obs.obs_property_int_set_suffix(volume_prop, " %")
    obs.obs_properties_add_button(group_obj, PN.BTN_TEST_SOUND, tr("test_sound"), test_sound_callback)

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
    obs.obs_property_set_modified_callback(volume_prop, persist_slider_callback)
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

    obs.obs_property_set_modified_callback(replacement_list, update_name_replacements_callback)


def auto_scene_desc_text(data=None) -> str:
    settings = data if data is not None else VARIABLES.script_settings
    return tr(
        "auto_scene_desc",
        data=data,
        game=obs.obs_data_get_string(settings, PN.PROP_AUTO_SCENE_GAME),
        desktop=obs.obs_data_get_string(settings, PN.PROP_AUTO_SCENE_DESKTOP),
        source=obs.obs_data_get_string(settings, PN.PROP_AUTO_SCENE_GAME_SOURCE),
    )


def setup_moment_settings(group_obj):
    auto_scene_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_AUTO_SCENE_ENABLED,
        description=tr("auto_scene_enabled")
    )
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_AUTO_SCENE_DESC,
        description=auto_scene_desc_text(),
        type=obs.OBS_TEXT_INFO
    )
    metadata_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_WRITE_MOMENT_METADATA,
        description=tr("write_moment_metadata")
    )
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_WRITE_MOMENT_METADATA_DESC,
        description=tr("write_moment_metadata_desc"),
        type=obs.OBS_TEXT_INFO
    )
    inputs_prop = obs.obs_properties_add_bool(
        props=group_obj,
        name=PN.PROP_RECORD_INPUTS,
        description=tr("record_inputs")
    )
    obs.obs_properties_add_text(
        props=group_obj,
        name=PN.TXT_RECORD_INPUTS_DESC,
        description=tr("record_inputs_desc"),
        type=obs.OBS_TEXT_INFO
    )
    obs.obs_property_set_modified_callback(auto_scene_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(metadata_prop, persist_settings_callback)
    obs.obs_property_set_modified_callback(inputs_prop, persist_settings_callback)


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
    moment_gr = obs.obs_properties_create()
    notification_gr = obs.obs_properties_create()
    app_rules_gr = obs.obs_properties_create()

    obs.obs_properties_add_group(p, PN.GR_UPDATE_SETTINGS, tr("group_updates"), obs.OBS_GROUP_NORMAL, update_gr)
    obs.obs_properties_add_group(p, PN.GR_CLIPS_PATH_SETTINGS, tr("group_clip_paths"), obs.OBS_GROUP_NORMAL, clip_path_gr)
    obs.obs_properties_add_group(p, PN.GR_CLIP_NAMING_SETTINGS, tr("group_clip_naming"), obs.OBS_GROUP_NORMAL, clip_naming_gr)
    obs.obs_properties_add_group(p, PN.GR_MOMENT_SETTINGS, tr("group_moments"), obs.OBS_GROUP_NORMAL, moment_gr)
    notification_group_prop = obs.obs_properties_add_group(p, PN.GR_SOUND_NOTIFICATION_SETTINGS, tr("group_sound_notifications"), obs.OBS_GROUP_CHECKABLE, notification_gr)
    obs.obs_properties_add_group(p, PN.GR_ALIASES_SETTINGS, tr("group_app_naming_rules"), obs.OBS_GROUP_NORMAL, app_rules_gr)

    # ------ Setup properties ------
    setup_update_settings(update_gr)
    setup_clip_paths_settings(clip_path_gr)
    setup_clip_naming_settings(clip_naming_gr)
    setup_moment_settings(moment_gr)
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


def persist_slider_callback(p, prop, data):
    save_persisted_settings_from_obs_data(data)
    return False  # True rebuilds the panel, which takes the slider out of the user's hand


def update_naming_mode_callback(p, prop, data):
    next_clip_prop = obs.obs_properties_get(p, PN.TXT_NEXT_CLIP)  # in another group
    if next_clip_prop is not None:
        broken = PN.PROP_CLIPS_BASE_PATH in find_folder_problems(data)
        obs.obs_property_set_description(next_clip_prop, next_clip_text(data, broken=broken))
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


def update_folders_callback(p, prop, data):
    if VARIABLES.interface_language_refreshing:
        return True  # already refreshed and saved, and OBS calls this once per field
    refresh_folder_properties(p, data)
    save_persisted_settings_from_obs_data(data)
    return True


def check_folders_callback(props, *args):
    refresh_folder_properties(props, VARIABLES.script_settings, checked=True)
    return True


def use_obs_folder_callback(props, *args):
    """Clears the clips folder: the path field itself can't be emptied by hand."""
    obs.obs_data_set_string(VARIABLES.script_settings, PN.PROP_CLIPS_BASE_PATH, "")
    return update_folders_callback(props, None, VARIABLES.script_settings)


def open_folder_guide_callback(*args):
    webbrowser.open(CONSTANTS.FOLDER_GUIDE_URLS[get_ui_language()], 1)


def set_info_text(props, prop_name: str, text: str, *, error: bool = False) -> None:
    prop = obs.obs_properties_get(props, prop_name)
    obs.obs_property_set_description(prop, text)
    obs.obs_property_text_set_info_type(prop, obs.OBS_TEXT_INFO_ERROR if error else obs.OBS_TEXT_INFO_NORMAL)


def refresh_folder_properties(props, data, *, checked: bool = False) -> None:
    """Updates what the folder settings show: the next clip's folder, problems, hidden fields."""
    more = obs.obs_data_get_bool(data, PN.PROP_SHOW_MORE_FOLDERS)
    extra = more and obs.obs_data_get_bool(data, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS)
    links = more and obs.obs_data_get_bool(data, PN.PROP_CLIPS_CREATE_LINKS)

    problems = find_folder_problems(data)
    texts = {}
    for prop_name, (key, kwargs) in problems.items():
        escaped = {name: html.escape(value, quote=False) for name, value in kwargs.items()}
        texts[prop_name] = tr(key, data=data, **escaped)

    next_clip = next_clip_text(data, broken=PN.PROP_CLIPS_BASE_PATH in problems)
    if checked and not problems:
        next_clip += "<br/>" + tr("folders_ok", data=data)
    set_info_text(props, PN.TXT_NEXT_CLIP, next_clip)

    for prop_name, text_name, desc_key, shown in (
        (PN.PROP_CLIPS_OVERRIDE_PATH, PN.TXT_CLIPS_OVERRIDE_PATH_DESC, "override_folder_desc", extra),
        (PN.PROP_RECORDING_FOLDER, PN.TXT_RECORDING_FOLDER_DESC, "recording_folder_desc", extra),
        (PN.PROP_CLIPS_LINKS_FOLDER_PATH, PN.TXT_CLIPS_LINKS_FOLDER_PATH_DESC, "links_folder_desc", links),
    ):
        problem = texts.pop(prop_name, "") if shown else ""  # a hidden folder's problem stays at the top
        set_info_text(props, text_name, problem or tr(desc_key, data=data), error=bool(problem))
        for name in (prop_name, text_name):
            obs.obs_property_set_visible(obs.obs_properties_get(props, name), shown)

    if PN.PROP_CLIPS_BASE_PATH in texts and obs.obs_data_get_string(data, PN.PROP_CLIPS_BASE_PATH):
        texts[PN.PROP_CLIPS_BASE_PATH] += " " + tr("clips_stay_in_obs_folder", data=data)
    set_info_text(props, PN.TXT_FOLDER_PROBLEMS, "<br/>".join(texts.values()), error=True)

    for prop_name, shown in (
        (PN.TXT_FOLDER_PROBLEMS, bool(texts)),
        (PN.BTN_USE_OBS_FOLDER, bool(obs.obs_data_get_string(data, PN.PROP_CLIPS_BASE_PATH))),
        (PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS, more),
        (PN.PROP_SHORT_BUFFER_PERCENT, extra),
        (PN.TXT_SHORT_BUFFER_PERCENT_DESC, extra),
        (PN.PROP_CLIPS_CREATE_LINKS, more),
        (PN.PROP_APP_OTHER_NAMES, more),
        (PN.TXT_APP_OTHER_NAMES_DESC, more),
    ):
        obs.obs_property_set_visible(obs.obs_properties_get(props, prop_name), shown)
    if not more:
        obs.obs_property_set_visible(obs.obs_properties_get(props, PN.TXT_APP_OTHER_NAMES_INVALID), False)


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


def test_sound_callback(*args):
    """Plays the first enabled sound (the "clip saved" one if none is) at the current volume."""
    settings = VARIABLES.script_settings
    path_prop = next((path for enabled, path in NOTIFICATION_SOUNDS if obs.obs_data_get_bool(settings, enabled)),
                     PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH)
    play_sound(obs.obs_data_get_string(settings, path_prop))


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
    if current_thread().name == WORKER_THREAD_NAME:
        # OBS labels script output by obspython's "current script", which worker threads never
        # have ("[Unknown Script]"): queue the line; foreground_tick prints it within a second.
        VARIABLES.deferred_logs.append((sep or " ").join(map(str, (f"[{str_time}]",) + values)))
        return
    print(f"[{str_time}]", *values, sep=sep, end=end, file=file, flush=flush)


def flush_deferred_logs() -> None:
    """Prints worker-thread log lines; call from a script callback so OBS labels them correctly."""
    logs = VARIABLES.deferred_logs
    while logs:
        print(logs.popleft())


def reset_forced_save_state():
    VARIABLES.force_override_save = False
    VARIABLES.half_buffer_save = False
    VARIABLES.save_requested_at = None
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


def scale_wav(source: Path | str, target: Path | str, percent: int) -> None:
    """Writes a 16-bit copy of a PCM WAV with its volume scaled. Raises for anything it can't read."""
    with wave.open(str(source), "rb") as wav:
        if getattr(wav, "getformat", lambda: wave.WAVE_FORMAT_PCM)() not in (wave.WAVE_FORMAT_PCM, 0xFFFE):
            raise wave.Error("not integer PCM")  # Python 3.15 also opens float WAVs
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        data = wav.readframes(wav.getnframes())

    if width == 1:  # unsigned
        samples = array("h", ((value - 128) * 256 for value in data))
    elif width <= 4:  # the two high bytes of each little-endian sample
        count = len(data) // width
        high = bytearray(count * 2)
        high[0::2] = data[width - 2:count * width:width]
        high[1::2] = data[width - 1:count * width:width]
        samples = array("h", bytes(high))
    else:
        raise wave.Error(f"{width * 8}-bit WAV")

    scaled = array("h", [value * percent // 100 for value in samples])
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(scaled.tobytes())


def scaled_sound_path(path: str | Path, percent: int) -> Path:
    """
    The quieter copy of a sound, made once per file and volume and deleted on unload. It is a file because
    winsound can't play from memory asynchronously.
    """
    stat = os.stat(path)
    if VARIABLES.sound_dir is None:
        VARIABLES.sound_dir = tempfile.TemporaryDirectory(prefix="Moment_Replays_", ignore_cleanup_errors=True)
    key = f"{os.path.abspath(path)}|{stat.st_mtime_ns}|{stat.st_size}|{percent}"
    target = Path(VARIABLES.sound_dir.name) / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + ".wav")
    if not target.exists():
        partial = target.with_suffix(".part")
        scale_wav(path, partial, percent)
        os.replace(partial, target)
    return target


def play_sound(path: str | Path):
    """
    Plays sound using windows engine, at the volume from the settings.

    :param path: path to sound (.wav)
    """
    percent = 100
    with suppress(Exception):
        percent = obs.obs_data_get_int(VARIABLES.script_settings, PN.PROP_SOUND_VOLUME)
    if percent <= 0:
        return
    if percent < 100:
        try:
            path = scaled_sound_path(path, percent)
        except Exception as e:
            _print(f"Cannot change the volume of {path} ({e}); playing it unchanged.")
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


def on_another_drive(first: Path, second: Path) -> bool:
    first_drive, second_drive = first.drive.casefold(), second.drive.casefold()
    return bool(first_drive and second_drive and first_drive != second_drive)


def find_folder_problem(folder: Path, same_drive_as: Path | None = None) -> tuple[str, dict[str, str]] | None:
    """
    Why clips can't be saved in `folder`, as a UI text key and its arguments; None if they can. A folder that
    doesn't exist yet is fine: it is made when the first clip is saved.
    shortcut: an unreachable network path makes OBS wait here, move to a worker thread if people record to one.
    """
    if same_drive_as is not None and on_another_drive(folder, same_drive_as):
        return "folder_wrong_drive", {"path": str(folder), "drive": same_drive_as.drive}

    existing = next((path for path in (folder, *folder.parents) if os.path.exists(path)), None)
    if existing is None:
        return "folder_not_found", {"path": str(folder)}

    probe = existing / f".moment_replays_{os.getpid()}"  # not tempfile: it retries for long when access is denied
    try:
        before = os.stat(existing)
        os.makedirs(probe, exist_ok=True)
        os.rmdir(probe)
    except OSError:
        return "folder_not_writable", {"path": str(folder)}
    with suppress(OSError):
        os.utime(existing, ns=(before.st_atime_ns, before.st_mtime_ns))  # players sort folders by date
    return None


def ensure_same_drive_for_rename(source_path: Path | str, target_path: Path | str) -> None:
    source_path = Path(source_path)
    target_path = Path(target_path)
    if on_another_drive(source_path, target_path):
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

    try:
        if (VARIABLES.last_links_folder != links_folder) or not links_folder.exists():
            os.makedirs(str(links_folder), exist_ok=True)
            VARIABLES.last_links_folder = links_folder
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


def trim_clip_to_last_seconds(file_path: Path | str, duration_seconds: float) -> tuple[Path, bool]:
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
        return file_path, False
    except Exception:
        _print("Cannot trim clip with ffmpeg. Keeping full clip.")
        _print(traceback.format_exc())
        return file_path, False

    if result.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
        _print("ffmpeg could not produce a trimmed clip. Keeping full clip.")
        if result.stderr:
            _print(result.stderr.strip())
        with suppress(OSError):
            temp_path.unlink()
        return file_path, False

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
        return file_path, True
    except Exception:
        _print("Cannot replace the original clip with the trimmed version. Keeping full clip.")
        _print(traceback.format_exc())
        with suppress(OSError):
            temp_path.unlink()
        with suppress(OSError):
            if backup_path.exists() and not file_path.exists():
                os.replace(backup_path, file_path)
        return file_path, False


def trim_half_clip_async(file_path: Path | str, duration_seconds: float, links_enabled: bool, links_folder: str,
                         short_metadata: dict | None = None, full_metadata: dict | None = None):
    try:
        final_path, trimmed = trim_clip_to_last_seconds(file_path, duration_seconds)
        if links_enabled:
            create_hard_link(final_path, links_folder)
        VARIABLES.last_saved_clip_path = final_path
        # A failed trim keeps the full clip, so its metadata must describe the full clip.
        write_moment_metadata(final_path, short_metadata if trimmed else full_metadata)
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


def find_folder_problems(data) -> dict[str, tuple[str, dict[str, str]]]:
    """Problems of the folders in use (see find_folder_problem), by setting."""
    def setting(prop_name: str) -> str:
        return obs.obs_data_get_string(data, prop_name)

    obs_path = read_obs_recording_path()
    obs_folder = Path(obs_path)
    folders = [(PN.PROP_CLIPS_BASE_PATH, setting(PN.PROP_CLIPS_BASE_PATH) or obs_path, obs_folder)]
    if obs.obs_data_get_bool(data, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS):
        folders.append((PN.PROP_CLIPS_OVERRIDE_PATH, setting(PN.PROP_CLIPS_OVERRIDE_PATH), obs_folder))
        folders.append((PN.PROP_RECORDING_FOLDER, setting(PN.PROP_RECORDING_FOLDER), None))
    if obs.obs_data_get_bool(data, PN.PROP_CLIPS_CREATE_LINKS):
        folders.append((PN.PROP_CLIPS_LINKS_FOLDER_PATH, setting(PN.PROP_CLIPS_LINKS_FOLDER_PATH), obs_folder))

    problems = {}
    for prop_name, folder, same_drive_as in folders:
        problem = find_folder_problem(Path(folder), same_drive_as) if folder else None
        if problem is not None:
            problems[prop_name] = problem
    return problems


def next_clip_text(data, *, broken: bool) -> str:
    """Where a normal replay save puts its clip; with a broken clips folder it stays where OBS wrote it."""
    def show(path: Path) -> str:
        return html.escape(os.path.join(path, ""), quote=False)

    if broken:
        return tr("next_clip", data=data, path=show(Path(read_obs_recording_path())))

    base = Path(obs.obs_data_get_string(data, PN.PROP_CLIPS_BASE_PATH) or read_obs_recording_path())
    by_scene = obs.obs_data_get_int(data, PN.PROP_CLIPS_NAMING_MODE) == ClipNamingModes.CURRENT_SCENE.value
    name = tr("next_clip_scene" if by_scene else "next_clip_game", data=data)
    text = tr("next_clip", data=data, path=show(base / f"<{name}>"))
    if not by_scene:
        text += "<br/>" + tr("next_clip_other", data=data, other_folder=CONSTANTS.OTHER_FOLDER_NAME,
                             path=show(base / CONSTANTS.OTHER_FOLDER_NAME))
    return text


# -------------------- alt_recording.py --------------------
def get_obs_recording_path_keys() -> tuple[str, str]:
    """Returns the (section, key) of the OBS recording path for the active output mode."""
    if get_obs_config("Output", "Mode") == "Simple":
        return "SimpleOutput", "FilePath"
    return "AdvOut", "RecFilePath"


def read_obs_recording_path() -> str:
    section, key = get_obs_recording_path_keys()
    return get_obs_config(section, key) or ""


def set_obs_recording_path(path_str: str) -> bool:
    """Sets the OBS recording path in the (in-memory) profile config."""
    section, key = get_obs_recording_path_keys()
    try:
        obs.config_set_string(get_obs_config(), section, key, path_str)
        return True
    except Exception:
        _print("Cannot change the OBS recording path.")
        _print(traceback.format_exc())
        return False


def restore_recording_path() -> None:
    """Restores the OBS recording path saved before an alternative recording."""
    if VARIABLES.saved_recording_path is None:
        return
    set_obs_recording_path(VARIABLES.saved_recording_path)
    _print(f"Restored OBS recording path to {VARIABLES.saved_recording_path}")
    VARIABLES.saved_recording_path = None


def resolve_recording_alt_folder() -> Path:
    raw = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_RECORDING_FOLDER)
    if raw:
        return Path(raw)
    return get_base_path(script_settings=VARIABLES.script_settings)


def cancel_alt_recording_watchdog() -> None:
    VARIABLES.alt_recording_watchdog_armed = False
    with suppress(Exception):
        obs.timer_remove(alt_recording_watchdog_callback)


def arm_alt_recording_watchdog() -> None:
    cancel_alt_recording_watchdog()
    obs.timer_add(alt_recording_watchdog_callback, CONSTANTS.ALT_RECORDING_WATCHDOG_MS)
    VARIABLES.alt_recording_watchdog_armed = True


def alt_recording_watchdog_callback() -> None:
    """
    Safety net: if an alternative recording was requested but recording never
    became active, undo the recording-path override so normal recordings are
    not silently redirected. Runs on the OBS timer thread.
    """
    cancel_alt_recording_watchdog()
    if obs.obs_frontend_recording_active():
        return
    if VARIABLES.saved_recording_path is not None:
        _print("Alternative recording did not start; restoring the OBS recording path.")
        restore_recording_path()
    VARIABLES.alt_recording_pending = False


def toggle_alt_recording_save():
    """
    Starts a full OBS recording redirected into the alternative recording folder,
    or stops the current recording. Can only be called using hotkeys.
    """
    if not obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_SHOW_OVERRIDE_FOLDER_SETTINGS):
        return

    if obs.obs_frontend_recording_active():
        obs.obs_frontend_recording_stop()
        return

    alt_folder = resolve_recording_alt_folder()
    try:
        os.makedirs(str(alt_folder), exist_ok=True)
    except Exception:
        _print(f"Cannot create the alternative recording folder {alt_folder}. Aborting.")
        _print(traceback.format_exc())
        return

    VARIABLES.saved_recording_path = read_obs_recording_path()
    if not set_obs_recording_path(str(alt_folder)):
        VARIABLES.saved_recording_path = None
        return

    VARIABLES.alt_recording_pending = True
    _print(f"Starting alternative recording into {alt_folder}")
    try:
        obs.obs_frontend_recording_start()
        arm_alt_recording_watchdog()
    except Exception:
        _print("Cannot start the alternative recording.")
        _print(traceback.format_exc())
        restore_recording_path()
        VARIABLES.alt_recording_pending = False


# -------------------- script_helpers.py --------------------
def notify(success: bool, clip_path: Path | None = None, *, play_audio: bool = True):
    """
    Plays success / failure sound notification if it's enabled in notifications settings.
    """
    sound_notifications_enabled = obs.obs_data_get_bool(VARIABLES.script_settings, PN.GR_SOUND_NOTIFICATION_SETTINGS)

    if success:
        if clip_path:
            _print(f"Clip saved at {clip_path}")
        if (play_audio and sound_notifications_enabled and
                obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS)):
            path = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH)
            play_sound(path)
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
        VARIABLES.save_requested_at = time.time()  # the clip ends here
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
        VARIABLES.save_requested_at = time.time()  # the clip ends here
        obs.obs_frontend_replay_buffer_save()
        arm_forced_save_watchdog()
    except Exception:
        _print("Cannot trigger replay buffer save for half-buffer hotkey.")
        _print(traceback.format_exc())
        reset_forced_save_state()


def is_save_in_progress() -> bool:
    """A clip counts as saved only once its info is written."""
    return VARIABLES.save_in_progress or bool(VARIABLES.pending_info_writes) or has_pending_forced_save()


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

    VARIABLES.recording_started_at = time.time()
    VARIABLES.recording_stop_at = None
    VARIABLES.recording_active = True

    # The recording is live and has captured its output path. Restore the OBS
    # recording path now so the NEXT (normal) recording is not redirected.
    cancel_alt_recording_watchdog()
    restore_recording_path()

    play_recording_sound_notification(
        PN.PROP_NOTIFY_RECORDING_ON_START,
        PN.PROP_NOTIFY_RECORDING_ON_START_PATH
    )
    sync_key_recorder()


def on_recording_stopping_callback(event):
    """The end of a recording is when it was asked to stop, not when OBS reports it stopped."""
    if event == getattr(obs, "OBS_FRONTEND_EVENT_RECORDING_STOPPING", None):
        VARIABLES.recording_stop_at = time.time()


def on_recording_stopped_callback(event):
    if event != obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED:
        return

    # Safety: undo any lingering path override (e.g. if start failed mid-way).
    cancel_alt_recording_watchdog()
    restore_recording_path()

    stop_at, VARIABLES.recording_stop_at = VARIABLES.recording_stop_at, None
    clip_end = time.time() if stop_at is None else stop_at + frames_to_seconds(CONSTANTS.RECORDING_END_FRAMES)
    origin = "alt_recording" if VARIABLES.alt_recording_pending else "recording"
    started_at, VARIABLES.recording_started_at = VARIABLES.recording_started_at, None
    last_recording = None
    with suppress(Exception):
        getter = getattr(obs, "obs_frontend_get_last_recording", None)
        last_recording = getter() if getter else None

    if VARIABLES.alt_recording_pending:
        VARIABLES.alt_recording_pending = False
        if last_recording:
            VARIABLES.last_saved_clip_path = Path(last_recording)
            _print(f"Alternative recording saved at {last_recording}")

    # Only for a recording we saw start; otherwise last_recording may be an older file.
    if last_recording and started_at is not None:
        write_clip_info_async(last_recording, collect_moment_metadata(
            origin, clip_end, clip_end - started_at, "obs_frontend_get_recording_output"))
    VARIABLES.recording_active = False

    play_recording_sound_notification(
        PN.PROP_NOTIFY_RECORDING_ON_STOP,
        PN.PROP_NOTIFY_RECORDING_ON_STOP_PATH
    )
    sync_key_recorder()


def reset_buffer_history() -> None:
    """Resets and starts recording executables history."""
    # Reset exe history; foreground_tick() fills it every second while it exists.
    VARIABLES.buffer_started_at = time.time()
    VARIABLES.buffer_active = True
    VARIABLES.buffer_max_time = 0
    with suppress(Exception):
        VARIABLES.buffer_max_time = int(get_replay_buffer_max_time() or 0)
    VARIABLES.save_key_presses.clear()
    VARIABLES.save_key_bindings = read_save_key_bindings()
    VARIABLES.clip_exe_history = deque([], maxlen=get_replay_buffer_max_time())
    VARIABLES.clip_exe_counts = {}
    VARIABLES.cached_active_window_pid = None
    VARIABLES.cached_active_exe = None
    VARIABLES.last_created_clip_folder = None
    VARIABLES.last_links_folder = None
    VARIABLES.save_in_progress = False
    cancel_pending_open_request()
    _print(f"Exe history deque created. Maxlen={VARIABLES.clip_exe_history.maxlen}.")


def on_buffer_recording_started_callback(event):
    if event != obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_STARTED:
        return
    reset_buffer_history()
    sync_key_recorder()


def on_buffer_recording_stopped_callback(event):
    """
    Stops recording executables history.
    """
    if event != obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_STOPPED:
        return

    VARIABLES.buffer_started_at = None
    VARIABLES.buffer_active = False
    VARIABLES.clip_exe_history = None  # stops foreground_tick() from filling it
    VARIABLES.clip_exe_counts = {}
    VARIABLES.cached_active_window_pid = None
    VARIABLES.cached_active_exe = None
    VARIABLES.last_created_clip_folder = None
    VARIABLES.last_links_folder = None
    VARIABLES.save_in_progress = False
    cancel_pending_open_request()
    reset_forced_save_state()
    sync_key_recorder()


def on_buffer_save_callback(event):
    if event != obs.OBS_FRONTEND_EVENT_REPLAY_BUFFER_SAVED:
        return

    _print(f"{'SAVING BUFFER':->50}")
    VARIABLES.save_in_progress = True
    event_at = time.time()

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
        reset_forced_save_state()  # timer calls come before the sound, which releases the GIL
        notify(False)
        VARIABLES.save_in_progress = False
        _print("-" * 50)
        return

    VARIABLES.last_saved_clip_path = path
    created_at = get_file_created_at(path)
    clip_end, anchor = pick_clip_end(event_at, created_at, VARIABLES.save_requested_at,
                                     list(VARIABLES.save_key_presses),
                                     frames_to_seconds(CONSTANTS.REPLAY_END_FRAMES), VARIABLES.created_lag)
    learn_created_lag(anchor, created_at, clip_end)
    while VARIABLES.save_key_presses and VARIABLES.save_key_presses[0] <= event_at:
        VARIABLES.save_key_presses.popleft()  # older saves can't claim them
    _print(f"Clip end taken from: {anchor}")
    replay_output = "obs_frontend_get_replay_buffer_output"
    full_duration = get_replay_clip_duration(clip_end)
    full_metadata = collect_moment_metadata("replay_buffer", clip_end, full_duration, replay_output)

    short_job = None
    if half_buffer_save:
        short_percent = obs.obs_data_get_int(VARIABLES.script_settings, PN.PROP_SHORT_BUFFER_PERCENT)
        short_percent = min(max(short_percent, 5), 100)
        half_duration = get_replay_buffer_max_time() * short_percent / 100
        links_enabled = obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_CLIPS_CREATE_LINKS)
        links_folder = obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_CLIPS_LINKS_FOLDER_PATH)
        short_metadata = collect_moment_metadata(
            "short_clip", clip_end, min(half_duration, full_duration), replay_output)
        short_job = (path, half_duration, links_enabled, links_folder, short_metadata, full_metadata)

    # Timer calls come before the sound and any thread start: those release the GIL, and another script
    # callback may then leave OBS without a current script ("No active script").
    reset_forced_save_state()
    VARIABLES.save_key_bindings = read_save_key_bindings()  # may have changed since the buffer started
    notify(True, path)
    if short_job is None or not run_info_writer(trim_half_clip_async, *short_job):
        write_clip_info_async(path, full_metadata)
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


def foreground_tick():
    """
    1 s sampler (OBS graphics thread): auto scene hook-up, replay-buffer exe history, the
    moment timeline, then the auto scene decision. The hook-up goes first, while obspython's
    "current script" is still this one (see auto_scene_prepare): later steps call ctypes
    WinDLL functions, which release the GIL.
    """
    flush_deferred_logs()
    scene = ""
    with suppress(Exception):
        scene = get_current_scene_name() or ""  # obspython only: keeps the GIL
    names = run_auto_scene_step(auto_scene_prepare, scene)

    append_clip_exe_history()
    executable_path = None
    with suppress(Exception):
        executable_path = get_active_executable_path()
    record_timeline_sample(time.time(), app_display_name(executable_path), exe_basename(executable_path), scene)

    if names:
        run_auto_scene_step(auto_scene_switching, executable_path, scene, names)


def run_auto_scene_step(step, *args):
    """Runs one auto scene step; an error detaches, is logged once and retried next tick."""
    try:
        return step(*args)
    except Exception:
        with suppress(Exception):
            auto_scene_detach()
        if VARIABLES.auto_scene_status != "error":
            VARIABLES.auto_scene_status = "error"
            _print("Auto scene: error; it will retry every second.")
            _print(traceback.format_exc())
        return None


# -------------------- moment_metadata.py --------------------
RATE_CONTROL_QUALITY_KEYS = {"CQP": "cqp", "CRF": "crf", "ICQ": "icq_quality"}
RECORDING_PRESET_KEYS = ("encoder", "rate_control", "cq", "width", "height", "fps")


def exe_basename(executable_path) -> str:
    """Executable file name only: metadata never carries absolute paths."""
    return Path(executable_path).name.lower() if executable_path else ""


def app_display_name(executable_path) -> str:
    """Quiet clip-name resolution (path alias > .exe fix > exe stem) for per-second sampling."""
    if not executable_path:
        return CONSTANTS.DEFAULT_FALLBACK_CLIP_NAME
    alias = get_alias(executable_path, VARIABLES.aliases)
    if alias:
        return alias
    stem = Path(executable_path).stem
    return VARIABLES.name_replacements.get(normalize_rule_name(stem), stem)


def record_timeline_sample(ts: float, app: str, exe: str, scene: str) -> None:
    """Keeps only change points, so one log serves both short buffers and hour-long recordings."""
    log = VARIABLES.timeline_log
    if log and log[-1][1:] == (app, exe, scene):
        return
    if log and ts < log[-1][0]:
        ts = log[-1][0]  # the UI thread (scene change) and the 1 s sampler can race: stay ordered
    log.append((ts, app, exe, scene))


def record_scene_change() -> None:
    """Timeline entry the moment the program scene changes, not up to 1 s later at the next sample."""
    log = VARIABLES.timeline_log
    if not log:
        return
    with suppress(Exception):
        _, app, exe, _ = log[-1]
        record_timeline_sample(time.time(), app, exe, get_current_scene_name() or "")


def cut_timeline(log, clip_start: float, clip_end: float) -> list[tuple[float, str, str, str]]:
    """
    Change points inside the clip as (t, app, exe, scene) with t relative to the clip start.
    The last change before the clip start becomes the t=0 entry.
    """
    out = []
    for ts, app, exe, scene in log:
        if ts > clip_end:
            break
        if ts <= clip_start:
            out = [(0.0, app, exe, scene)]
        else:
            out.append((round(ts - clip_start, 2), app, exe, scene))
    return out


def markers_to_annotations(markers, clip_start: float, clip_end: float) -> list[dict]:
    """Mark-moment wall times inside the clip; older (or later) markers are dropped."""
    return [
        {"type": "marker", "t": round(marker - clip_start, 2), "label": "mark"}
        for marker in sorted(markers)
        if clip_start <= marker <= clip_end
    ]


def summarize_game(timeline, duration: float, game_scene: str) -> dict:
    """The app on screen for most of the clip, and whether it was shown via the Game scene."""
    app_time: dict[tuple[str, str], float] = {}
    scene_time: dict[tuple[str, str], dict[str, float]] = {}
    for index, (t, app, exe, scene) in enumerate(timeline):
        end = timeline[index + 1][0] if index + 1 < len(timeline) else duration
        span = max(end - t, 0.0)
        app_time[(app, exe)] = app_time.get((app, exe), 0.0) + span
        scenes = scene_time.setdefault((app, exe), {})
        scenes[scene] = scenes.get(scene, 0.0) + span

    if not app_time:
        return {"name": CONSTANTS.DEFAULT_FALLBACK_CLIP_NAME, "exe": "", "captured_via": "display_capture"}

    name, exe = max(app_time.items(), key=lambda item: item[1])[0]
    top_scene = max(scene_time[(name, exe)].items(), key=lambda item: item[1])[0]
    return {
        "name": name,
        "exe": exe,
        "captured_via": "game_capture" if game_scene and top_scene == game_scene else "display_capture",
    }


def build_moment_metadata(*, origin: str, clip_end: float, duration: float, timeline_log, markers,
                          game_scene: str, audio_tracks: list[dict], recording_preset: dict,
                          obs_version: str, key_log: dict | None = None) -> dict:
    """Pure `moment.clip/1` payload builder (shared contract with Moment Player)."""
    duration = max(float(duration), 0.0)
    clip_start = clip_end - duration
    timeline = cut_timeline(timeline_log, clip_start, clip_end)
    payload = {
        "schema": CONSTANTS.MOMENT_SCHEMA,
        "origin": origin,
        "saved_at": datetime.fromtimestamp(clip_end).astimezone().isoformat(timespec="seconds"),
        "duration_s": round(duration, 2),
        "game": summarize_game(timeline, duration, game_scene),
        "timeline": [{"t": t, "app": app, "scene": scene} for t, app, _, scene in timeline],
        "annotations": markers_to_annotations(markers, clip_start, clip_end),
        "audio_tracks": audio_tracks,
        "recording_preset": recording_preset,
        "obs_version": obs_version,
        "writer": f"Moment Replays {CONSTANTS.VERSION}",
    }
    inputs = build_clip_inputs(key_log, clip_start, clip_end) if key_log else None
    if inputs is not None:
        payload["inputs"] = inputs  # last field of the JSON
    return payload


def build_clip_inputs(key_log: dict, clip_start: float, clip_end: float) -> dict | None:
    """
    `inputs` of the clip: per recorded key, [down, up, down, up, ...] in ms from the first frame.
    Held at the start: the first down is 0. Held at the end: the last up is the clip's length.
    None when no game was in front during the clip.
    """
    if not any(start < clip_end and (end is None or end > clip_start) for start, end in key_log["focus"]):
        return None
    length_ms = round((clip_end - clip_start) * 1000)
    inputs = {}
    for name in KEY_VKS:
        times: list[int] = []
        for down, up in key_log["keys"].get(name, ()):
            down, up = max(down, clip_start), clip_end if up is None else min(up, clip_end)
            if up > down:
                times += [round((down - clip_start) * 1000), min(round((up - clip_start) * 1000), length_ms)]
        inputs[name] = times
    return inputs


def get_audio_tracks() -> list[dict]:
    """Recorded audio tracks (RecTracks bitmask) named from the profile's AdvOut/Track{n}Name."""
    if get_obs_config("Output", "Mode") == "Simple":
        mask = get_obs_config("SimpleOutput", "RecTracks", int)
    else:
        mask = get_obs_config("AdvOut", "RecTracks", int)
    mask = mask or 1
    return [
        {"track": n, "name": get_obs_config("AdvOut", f"Track{n}Name") or f"Track {n}"}
        for n in range(1, 7)
        if mask & (1 << (n - 1))
    ]


def get_output_fps() -> float | None:
    with suppress(Exception):
        video_info = obs.obs_video_info()
        if obs.obs_get_video_info(video_info) and video_info.fps_den:
            return video_info.fps_num / video_info.fps_den
    return None


def frames_to_seconds(frames: float) -> float:
    return frames / (get_output_fps() or 60.0)


def get_recording_preset(output_getter_name: str) -> dict:
    """Encoder id, rate control, quality, scaled size and fps of the output that wrote the clip."""
    preset = dict.fromkeys(RECORDING_PRESET_KEYS)
    fps = get_output_fps()
    if fps:
        preset["fps"] = int(fps) if float(fps).is_integer() else round(fps, 3)

    getter = getattr(obs, output_getter_name, None)
    output = getter() if getter is not None else None
    if output is None:
        return preset
    try:
        encoder = obs.obs_output_get_video_encoder(output)
        if encoder is None:
            return preset
        preset["encoder"] = obs.obs_encoder_get_id(encoder) or None
        preset["width"] = obs.obs_encoder_get_width(encoder) or None
        preset["height"] = obs.obs_encoder_get_height(encoder) or None
        settings = obs.obs_encoder_get_settings(encoder)
        if settings is not None:
            try:
                rate_control = obs.obs_data_get_string(settings, "rate_control") or ""
                preset["rate_control"] = rate_control or None
                quality_key = RATE_CONTROL_QUALITY_KEYS.get(rate_control.upper())
                if quality_key:
                    preset["cq"] = obs.obs_data_get_int(settings, quality_key)
            finally:
                obs.obs_data_release(settings)
    finally:
        obs.obs_output_release(output)
    return preset


def get_file_created_at(path: Path | str) -> float | None:
    """Wall time this file was created (NTFS keeps it through a rename), or None."""
    with suppress(OSError):
        stat = os.stat(path)
        return getattr(stat, "st_birthtime", stat.st_ctime)
    return None


def read_save_key_bindings() -> tuple:
    """
    (virtual key, modifier names) of every key bound to OBS's own "Save Replay", read from the profile
    the way OBS loads it. The replay output has no hotkey of its own in OBS 33. Logs once when there is none.
    """
    bindings, problem = [], "no key is bound to it"
    try:
        for name, array in SAVE_KEY_SOURCES:
            raw = get_obs_config("Hotkeys", name)
            if not raw:
                continue
            for item in json.loads(raw).get(array) or ():
                vk = obs.obs_key_to_virtual_key(obs.obs_key_from_name(item.get("key") or ""))
                if vk:
                    bindings.append((vk, frozenset(m for m in SAVE_KEY_MODIFIERS if item.get(m))))
            break
    except Exception as error:
        problem = f"its binding cannot be read ({type(error).__name__})"
    if bindings:
        problem = ""
    if problem and problem != VARIABLES.save_key_problem:
        _print(f"OBS's Save Replay hotkey: {problem}. Replay ends are estimated from the file's creation time.")
    VARIABLES.save_key_problem = problem
    return tuple(bindings)


def pick_clip_end(now: float, created_at: float | None, requested_at: float | None, presses,
                  shift: float, created_lag: float) -> tuple[float, str]:
    """
    (wall time of the clip's last moment, how it was found). OBS cuts the clip `shift` seconds after the
    save was *requested*; the SAVED event comes later (encoder latency plus the write), and marks
    anchored to that would be early by as much. In order: a script hotkey's request, OBS's own save
    key, the new file's creation time minus `created_lag`, and only then the event time.

    Presses count only within SAVE_KEY_MAX_LEAD_S before the saved file was created, and the last one
    wins: OBS overwrites a pending save's time when the key is pressed again.
    """
    if created_at is not None and not now - CONSTANTS.CREATED_MAX_AGE_S <= created_at <= now + 1:
        created_at = None  # a wrong clock or a file from some other time
    limit = now if created_at is None else created_at
    if requested_at is not None and limit - 30 <= requested_at <= limit + 0.1:
        return requested_at + shift, ANCHOR_SCRIPT_HOTKEY
    recent = [p for p in presses if limit - CONSTANTS.SAVE_KEY_MAX_LEAD_S <= p <= limit]
    if recent:
        return max(recent) + shift, ANCHOR_SAVE_KEY
    if created_at is not None:
        return created_at - created_lag, "file creation time"
    return now, "save event"


def learn_created_lag(anchor: str, created_at: float | None, clip_end: float) -> None:
    """
    How long after its clip's end a replay file appears depends on the encoder (NVENC 0.2 s, x264 1.2 s):
    remember it from saves whose end is known, for the ones whose end isn't (tray, Stream Deck).
    """
    if anchor in (ANCHOR_SCRIPT_HOTKEY, ANCHOR_SAVE_KEY) and created_at is not None:
        lag = created_at - clip_end
        if 0 < lag <= CONSTANTS.SAVE_KEY_MAX_LEAD_S:
            VARIABLES.created_lag = lag


def get_replay_clip_duration(clip_end: float) -> float:
    """Replay length: the buffer size, or less if the buffer started recently."""
    max_time = 0
    with suppress(Exception):
        max_time = int(get_replay_buffer_max_time() or 0)
    started = VARIABLES.buffer_started_at
    if started is None:
        return float(max_time)
    elapsed = max(clip_end - started, 0.0)
    return min(float(max_time), elapsed) if max_time else elapsed


def _find_mp4_box(f, start: int, end: int, box_type: bytes) -> tuple[int, int] | None:
    """(payload start, box end) of the first `box_type` box between start and end, or None."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        payload = pos + 8
        if size == 1:  # 64-bit size
            size = struct.unpack(">Q", f.read(8))[0]
            payload += 8
        elif size == 0:  # box runs to the end
            size = end - pos
        if size < payload - pos:
            return None
        if kind == box_type:
            return payload, min(pos + size, end)
        pos += size
    return None


def read_mp4_duration(path: Path | str) -> float | None:
    """
    Real length of a finished MP4 from its moov/mvhd box (no ffprobe needed): headers only,
    the media data is skipped. None for other containers, unfinished files or any error.
    """
    try:
        with open(path, "rb") as f:
            moov = _find_mp4_box(f, 0, os.fstat(f.fileno()).st_size, b"moov")
            mvhd = moov and _find_mp4_box(f, moov[0], moov[1], b"mvhd")
            if not mvhd:
                return None
            f.seek(mvhd[0])
            if f.read(4)[0] == 1:  # version 1: 64-bit times
                f.seek(16, os.SEEK_CUR)
                timescale, duration = struct.unpack(">IQ", f.read(12))
            else:
                f.seek(8, os.SEEK_CUR)
                timescale, duration = struct.unpack(">II", f.read(8))
            return duration / timescale if timescale and duration else None
    except (OSError, struct.error, IndexError):
        return None


# Clip info (moment.clip/1 JSON) inside the MP4: its standard `synopsis` tag,
# moov/udta/meta/ilst/ldes/data, UTF-8. ffmpeg keeps it through cuts and re-encodes; Explorer
# doesn't show it. A complete new moov is appended and the old one is retired afterwards by its
# 4-byte type, so the media never moves and an interrupted write leaves a clip that still plays.
MP4_META_HDLR = struct.pack(">I4s", 33, b"hdlr") + b"\0" * 8 + b"mdirappl" + b"\0" * 9


def _mp4_box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", len(body) + 8, kind) + body


def _mp4_top_boxes(f, end: int) -> list[tuple[bytes, int, int, int]]:
    """(kind, start, size, header size) of every top-level box; ValueError unless they fill the file exactly."""
    out, pos = [], 0
    while pos < end:
        f.seek(pos)
        head = f.read(16)
        if len(head) < 8:
            raise ValueError("truncated box")
        size, kind = struct.unpack(">I4s", head[:8])
        header = 8
        if size == 1 and len(head) == 16:
            size, header = struct.unpack(">Q", head[8:])[0], 16
        if size < header or pos + size > end:  # includes size 0 ("to the end"): nothing may follow it
            raise ValueError(f"open-ended or truncated box {kind!r}")
        out.append((kind, pos, size, header))
        pos += size
    return out


def _mp4_children(data: bytes) -> list[tuple[bytes, bytes]]:
    """(kind, whole box) of every child box; ValueError unless they fill data exactly."""
    out, pos = [], 0
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("truncated child box")
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if size < 8 or pos + size > len(data):
            raise ValueError(f"bad child box {kind!r}")
        out.append((kind, data[pos:pos + size]))
        pos += size
    return out


def _mp4_put(body: bytes, path: tuple[bytes, ...], leaf: bytes) -> bytes:
    """body with `leaf` at the end of the nested box `path`, replacing the same kind of leaf; parents are created."""
    kids = _mp4_children(body)
    if not path:
        return b"".join(box for kind, box in kids if kind != leaf[4:8]) + leaf
    kind = path[0]
    at = next((i for i, (k, _) in enumerate(kids) if k == kind), None)
    if at is None:
        at = len(kids)
        kids.append((kind, _mp4_box(kind, b"\0" * 4 + MP4_META_HDLR if kind == b"meta" else b"")))
    box = kids[at][1]
    head = 8
    if kind == b"meta":  # a full box: 4 bytes of version and flags before its children
        head = 12
        if box[16:20] != b"hdlr":
            raise ValueError("unexpected meta box")
    kids[at] = (kind, _mp4_box(kind, box[8:head] + _mp4_put(box[head:], path[1:], leaf)))
    return b"".join(box for _, box in kids)


def _finished_moov(f) -> tuple[int, int]:
    """(start, size) of the only moov of a finished, unfragmented MP4; ValueError otherwise."""
    boxes = _mp4_top_boxes(f, os.fstat(f.fileno()).st_size)
    kinds = [box[0] for box in boxes]
    moov = [box for box in boxes if box[0] == b"moov"]
    # OBS writes a recording as fragments and turns it into a plain MP4 at the end: `moof` also means "not ready".
    if kinds[:1] != [b"ftyp"] or len(moov) != 1 or b"mdat" not in kinds or b"moof" in kinds or moov[0][3] != 8:
        raise ValueError("not a finished plain MP4")
    return moov[0][1], moov[0][2]


def check_finished_mp4(path: Path | str) -> None:
    """ValueError unless the file is a finished plain MP4 that can take the clip info."""
    with open(path, "rb") as f:
        _finished_moov(f)


def embed_clip_info(path: Path | str, info: bytes) -> None:
    """
    Stores `info` in the MP4's synopsis tag. ValueError: not a finished plain MP4. OSError: locked,
    full disk... On any error the clip is left as it was.
    """
    stat = os.stat(path)
    with open(path, "r+b", buffering=0) as f:  # unbuffered: a failed write leaves nothing pending
        start, size = _finished_moov(f)
        f.seek(start)
        moov = b""
        while len(moov) < size:
            chunk = f.read(size - len(moov))
            if not chunk:
                raise ValueError("truncated moov")
            moov += chunk
        leaf = _mp4_box(b"ldes", _mp4_box(b"data", struct.pack(">II", 1, 0) + info))
        new_moov = _mp4_box(b"moov", _mp4_put(moov[8:], (b"udta", b"meta", b"ilst"), leaf))
        end = f.seek(0, os.SEEK_END)
        try:
            rest = memoryview(new_moov)
            while rest:
                written = f.write(rest)
                if not written:
                    raise OSError("short write")
                rest = rest[written:]
            os.fsync(f.fileno())  # the new index must be on disk before the old one is retired
        except BaseException:
            f.truncate(end)
            raise
        f.seek(start + 4)
        f.write(b"free")
    with suppress(OSError):
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def encode_clip_info(payload: dict) -> bytes:
    """Compact JSON plus spaces, so an editor can rewrite it in place at the same length."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8") + b" " * CONSTANTS.INFO_TAG_PADDING


def collect_moment_metadata(origin: str, clip_end: float, duration: float, output_getter_name: str) -> dict | None:
    """
    Snapshot of everything the .moment.json needs, i.e. the build_moment_metadata() arguments
    (UI thread: all OBS reads happen here). `duration` is only the estimate used when the saved
    file's real length can't be read. Never raises: metadata must not break a save.
    """
    if not obs.obs_data_get_bool(VARIABLES.script_settings, PN.PROP_WRITE_MOMENT_METADATA):
        return None
    try:
        audio_tracks = []
        with suppress(Exception):
            audio_tracks = get_audio_tracks()
        preset = dict.fromkeys(RECORDING_PRESET_KEYS)
        with suppress(Exception):
            preset = get_recording_preset(output_getter_name)
        return {
            "origin": origin,
            "clip_end": clip_end,
            "duration": duration,
            "timeline_log": list(VARIABLES.timeline_log),  # snapshot: the sampler appends on another thread
            "markers": list(VARIABLES.moment_markers),
            "game_scene": obs.obs_data_get_string(VARIABLES.script_settings, PN.PROP_AUTO_SCENE_GAME),
            "audio_tracks": audio_tracks,
            "recording_preset": preset,
            "obs_version": CONSTANTS.OBS_VERSION_STRING,
            "key_log": VARIABLES.key_recorder.snapshot() if VARIABLES.record_inputs and VARIABLES.key_recorder else None,
        }
    except Exception:
        _print("Cannot collect moment metadata; the clip itself is saved.")
        _print(traceback.format_exc())
        return None


def moment_metadata_path(clip_path: Path | str) -> Path:
    clip_path = Path(clip_path)
    return clip_path.with_name(clip_path.stem + CONSTANTS.MOMENT_METADATA_SUFFIX)


def build_clip_payload(clip_path: Path, inputs: dict) -> dict:
    """
    Payload for a saved file, using its real length: the replay buffer starts a clip on a keyframe,
    so a "35 s" clip is often 1-4 s shorter, and every `t` must count from its real first frame.
    """
    return build_moment_metadata(**{**inputs, "duration": read_mp4_duration(clip_path) or inputs["duration"]})


def store_in_mp4(clip_path: Path, inputs: dict, retry_s: float) -> bool:
    """
    Stores the clip info inside the MP4, retrying for up to retry_s while OBS is still finishing the
    file (a recording is fragments until then) or a scanner holds it. False = use the sidecar.
    """
    deadline = time.monotonic() + retry_s
    while True:
        try:
            check_finished_mp4(clip_path)
            embed_clip_info(clip_path, encode_clip_info(build_clip_payload(clip_path, inputs)))
            _print(f"Clip info saved inside {clip_path.name}")
            return True
        except FileNotFoundError:
            _print("The clip is gone; its info was not written.")
            return True
        except (ValueError, PermissionError) as error:
            reason = str(error)
        except OSError as error:
            _print(f"Cannot store the clip info inside the clip: {error}")
            return False
        if VARIABLES.unloading.is_set() or time.monotonic() >= deadline:
            _print(f"The clip info cannot be stored inside the clip ({reason}).")
            return False
        VARIABLES.unloading.wait(CONSTANTS.INFO_RETRY_INTERVAL_S)


def write_moment_metadata(clip_path: Path | str | None, inputs: dict | None, retry_s: float | None = None) -> None:
    """
    Stores the clip info (built from collect_moment_metadata() inputs) inside a finished plain MP4,
    or else in <clip basename>.moment.json next to it. Worker thread: retries for up to retry_s.
    Never raises.
    """
    if inputs is None or not clip_path:
        return
    clip_path = Path(clip_path)
    try:
        retry_s = CONSTANTS.INFO_RETRY_S if retry_s is None else retry_s
        if clip_path.suffix.lower() == ".mp4" and store_in_mp4(clip_path, inputs, retry_s):
            return
        if not clip_path.exists():
            _print("The clip is gone; its info was not written.")
            return
        path = moment_metadata_path(clip_path)
        write_json_atomic(path, build_clip_payload(clip_path, inputs))
        _print(f"Moment metadata saved at {path}")
    except Exception:
        _print("Cannot write moment metadata; the clip itself is saved.")
        _print(traceback.format_exc())


def run_info_writer(target, *args) -> bool:
    """Runs `target` on a worker thread that is_save_in_progress() and script_unload() know about."""
    def worker():
        try:
            target(*args)
        finally:
            VARIABLES.pending_info_writes.discard(current_thread())

    thread = Thread(target=worker, daemon=True, name=WORKER_THREAD_NAME)
    VARIABLES.pending_info_writes.add(thread)
    try:
        thread.start()
        return True
    except Exception:
        VARIABLES.pending_info_writes.discard(thread)
        _print("Cannot start a worker thread for the clip info.")
        _print(traceback.format_exc())
        return False


def write_clip_info_async(clip_path: Path | str, inputs: dict | None) -> None:
    """write_moment_metadata() on a worker; without a thread, one attempt here and no retries."""
    if inputs is None:
        return
    if not run_info_writer(write_moment_metadata, clip_path, inputs):
        write_moment_metadata(clip_path, inputs, 0)


def mark_moment():
    """Stores a wall-clock marker; a later save turns markers inside the clip into annotations."""
    VARIABLES.moment_markers.append(time.time())
    _print("Moment marked.")
    play_mark_feedback()


def play_mark_feedback():
    """A short blip of the success sound, if sound notifications are on."""
    settings = VARIABLES.script_settings
    if not (obs.obs_data_get_bool(settings, PN.GR_SOUND_NOTIFICATION_SETTINGS) and
            obs.obs_data_get_bool(settings, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS)):
        return
    # Timer calls need obspython's current script, so they go before play_sound (which releases the GIL).
    obs.timer_remove(stop_mark_feedback)  # at most one pending stop timer
    obs.timer_add(stop_mark_feedback, CONSTANTS.MARK_FEEDBACK_MS)
    play_sound(obs.obs_data_get_string(settings, PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH))


def stop_mark_feedback():
    obs.timer_remove(stop_mark_feedback)
    stop_playing_sound()


def stop_playing_sound():
    with suppress(Exception):
        winsound.PlaySound(None, 0)


# -------------------- auto_scene.py --------------------
SHELL_WINDOW_CLASSES = frozenset(("progman", "workerw", "shell_traywnd"))
WS_MAXIMIZE = 0x01000000
WS_BORDER = 0x00800000
HOOKED_EXE_UNKNOWN = "*"


def is_fullscreen_game_window(window_rect, monitor_rect, window_class: str, style: int,
                              exe_name: str, app_name: str, other_names) -> bool:
    """
    True when the foreground window looks like a game: it covers its whole monitor
    (exclusive or borderless fullscreen), is not the desktop/taskbar, is not a regular
    maximized window (same rule as OBS game capture), and its app is not in the Other list.
    """
    if (window_class or "").casefold() in SHELL_WINDOW_CLASSES:
        return False
    if (style & WS_MAXIMIZE) and (style & WS_BORDER):
        return False
    if (normalize_rule_name(Path(exe_name).stem) in other_names or
            normalize_rule_name(app_name) in other_names):
        return False
    left, top, right, bottom = window_rect
    m_left, m_top, m_right, m_bottom = monitor_rect
    return left <= m_left and top <= m_top and right >= m_right and bottom >= m_bottom


class AutoSceneMachine:
    """
    Game/Desktop decision with a debounce on the way back to Desktop.

    - Desktop -> Game: the foreground is a fullscreen game AND the game capture source has
      hooked that exe (so the Game scene never shows black frames).
    - Game -> Desktop: immediately on `unhooked`; otherwise once the foreground has not been
      the hooked fullscreen game for longer than `debounce_s`.
    - Any other current scene (e.g. a manual "BRB" scene) is left alone.
    """

    def __init__(self, debounce_s: float = CONSTANTS.AUTO_SCENE_DEBOUNCE_S):
        self.debounce_s = debounce_s
        self.hooked_exe: str | None = None  # set by the game capture `hooked`/`unhooked` signals
        self.lost_since: float | None = None

    def decide(self, now: float, current_scene: str, fg_exe: str, fg_is_game: bool,
               game_scene: str, desktop_scene: str, game_allowed: bool = True) -> str | None:
        """`game_allowed` (from BlackFrameGuard) only gates Desktop -> Game."""
        if current_scene not in (game_scene, desktop_scene):
            self.lost_since = None
            return None

        hooked = self.hooked_exe
        in_game = bool(fg_is_game and hooked and hooked in (HOOKED_EXE_UNKNOWN, fg_exe))

        if current_scene == desktop_scene:
            self.lost_since = None
            return game_scene if in_game and game_allowed else None

        if hooked is None:
            self.lost_since = None
            return desktop_scene
        if in_game:
            self.lost_since = None
            return None
        if self.lost_since is None:
            self.lost_since = now
            return None
        if now - self.lost_since > self.debounce_s:
            self.lost_since = None
            return desktop_scene
        return None


class BlackFrameGuard:
    """
    "Hooked but black" protection (anti-cheat, HDR, hybrid GPUs, swapchain recreate), per
    process, for the whole OBS session.

    - observe(): the capture's brightest sampled channel (0..255); None = unknown/no sample.
    - should_fall_back(): black for `window_s` while on Game -> show Desktop (Display Capture
      still shows the game, so clips never end up black with sound).
    - fall_back(): puts the process on a cooldown so the scenes can't flap; True the first
      time per process, when one rehook is worth a try.
    - can_show_game(): no cooldown AND the latest sample is not black. Unknown counts as fine,
      so a missing sampler never blocks Game; a black loading screen only delays Game until
      a non-black frame arrives (after any cooldown).
    """

    def __init__(self, threshold: int = CONSTANTS.BLACK_LUMA_THRESHOLD,
                 window_s: float = CONSTANTS.BLACK_FALLBACK_S,
                 cooldown_s: float = CONSTANTS.BLACK_COOLDOWN_S):
        self.threshold = threshold
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self.luma: int | None = None
        self.black_since: float | None = None
        self.cooldown_until: dict[str, float] = {}
        self.rehooked: set[str] = set()

    def is_black(self) -> bool:
        return self.luma is not None and self.luma <= self.threshold

    def observe(self, now: float, luma: int | None) -> None:
        self.luma = luma
        if not self.is_black():
            self.black_since = None
        elif self.black_since is None:
            self.black_since = now

    def should_fall_back(self, now: float) -> bool:
        return self.black_since is not None and now - self.black_since >= self.window_s

    def fall_back(self, now: float, process: str) -> bool:
        self.cooldown_until[process] = now + self.cooldown_s
        self.black_since = None
        if process in self.rehooked:
            return False
        self.rehooked.add(process)
        return True

    def can_show_game(self, now: float, process: str) -> bool:
        return now >= self.cooldown_until.get(process, 0.0) and not self.is_black()


def max_rgb(raw: bytes, width: int, height: int, linesize: int) -> int:
    """Brightest colour channel of an RGBA/BGRA pixel buffer (alpha ignored)."""
    best = 0
    for y in range(height):
        row = raw[y * linesize:y * linesize + width * 4]
        best = max(best, max(row[0::4]), max(row[1::4]), max(row[2::4]))
    return best


GS_RGBA = 3          # enum gs_color_format (checked against obspython, OBS 33)
GS_ZS_NONE = 0       # enum gs_zstencil_format
GS_CLEAR_COLOR = 1

GFX_PROTOTYPES = {
    "obs_enter_graphics": (None, ()),
    "obs_leave_graphics": (None, ()),
    "obs_get_source_by_name": (ctypes.c_void_p, (ctypes.c_char_p,)),
    "obs_source_release": (None, (ctypes.c_void_p,)),
    "obs_source_get_width": (ctypes.c_uint32, (ctypes.c_void_p,)),
    "obs_source_get_height": (ctypes.c_uint32, (ctypes.c_void_p,)),
    "obs_source_video_render": (None, (ctypes.c_void_p,)),
    "gs_texrender_create": (ctypes.c_void_p, (ctypes.c_int, ctypes.c_int)),
    "gs_texrender_destroy": (None, (ctypes.c_void_p,)),
    "gs_texrender_reset": (None, (ctypes.c_void_p,)),
    "gs_texrender_begin": (ctypes.c_bool, (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32)),
    "gs_texrender_end": (None, (ctypes.c_void_p,)),
    "gs_texrender_get_texture": (ctypes.c_void_p, (ctypes.c_void_p,)),
    "gs_clear": (None, (ctypes.c_uint32, ctypes.c_void_p, ctypes.c_float, ctypes.c_uint8)),
    "gs_ortho": (None, (ctypes.c_float,) * 6),
    "gs_stagesurface_create": (ctypes.c_void_p, (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int)),
    "gs_stagesurface_destroy": (None, (ctypes.c_void_p,)),
    "gs_stage_texture": (None, (ctypes.c_void_p, ctypes.c_void_p)),
    "gs_stagesurface_map": (ctypes.c_bool, (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                            ctypes.POINTER(ctypes.c_uint32))),
    "gs_stagesurface_unmap": (None, (ctypes.c_void_p,)),
}


def load_obs_graphics():
    """
    ctypes view of obs.dll for the GPU readback. PyDLL keeps the GIL during calls (like the
    obspython wrappers): releasing it while this thread holds the graphics context could
    deadlock against another Python thread that wants the graphics context.
    """
    gfx = ctypes.PyDLL("obs.dll", handle=get_loaded_module_handle("obs.dll"))
    for name, (restype, argtypes) in GFX_PROTOTYPES.items():
        function = getattr(gfx, name)
        function.restype = restype
        function.argtypes = argtypes
    return gfx


class CaptureLumaSampler:
    """
    Brightest channel of a 32x18 downscale of the game capture, read back from the GPU on the
    OBS graphics thread (1 s tick). Each call returns the frame staged by the previous call and
    stages a new one, so mapping never stalls on the GPU.
    """

    def __init__(self, gfx):
        self.gfx = gfx
        self.texrender = None
        self.stagesurf = None
        self.staged = False
        self._clear_buffer = (ctypes.c_float * 8)()  # zeroed; holds a 16-byte aligned vec4

    def _clear_color(self) -> int:
        return (ctypes.addressof(self._clear_buffer) + 15) & ~15

    def sample(self, source_name: str) -> int | None:
        gfx = self.gfx
        source = gfx.obs_get_source_by_name(source_name.encode("utf-8"))
        if not source:
            self.staged = False
            return None
        try:
            width, height = gfx.obs_source_get_width(source), gfx.obs_source_get_height(source)
            gfx.obs_enter_graphics()
            try:
                luma = self._read_staged()
                if width and height:
                    self._render_and_stage(source, width, height)
            finally:
                gfx.obs_leave_graphics()
        finally:
            gfx.obs_source_release(source)
        return luma

    def _render_and_stage(self, source, width: int, height: int) -> None:
        gfx = self.gfx
        sample_w, sample_h = CONSTANTS.BLACK_SAMPLE_SIZE
        if not self.texrender:
            self.texrender = gfx.gs_texrender_create(GS_RGBA, GS_ZS_NONE)
        if not self.stagesurf:
            self.stagesurf = gfx.gs_stagesurface_create(sample_w, sample_h, GS_RGBA)
        if not self.texrender or not self.stagesurf:
            return
        gfx.gs_texrender_reset(self.texrender)
        if not gfx.gs_texrender_begin(self.texrender, sample_w, sample_h):
            return
        gfx.gs_clear(GS_CLEAR_COLOR, self._clear_color(), 0.0, 0)
        gfx.gs_ortho(0.0, float(width), 0.0, float(height), -100.0, 100.0)
        gfx.obs_source_video_render(source)
        gfx.gs_texrender_end(self.texrender)
        texture = gfx.gs_texrender_get_texture(self.texrender)
        if texture:
            gfx.gs_stage_texture(self.stagesurf, texture)
            self.staged = True

    def _read_staged(self) -> int | None:
        if not self.staged:
            return None
        self.staged = False
        data = ctypes.c_void_p()
        linesize = ctypes.c_uint32()
        if not self.gfx.gs_stagesurface_map(self.stagesurf, ctypes.byref(data), ctypes.byref(linesize)):
            return None
        try:
            sample_w, sample_h = CONSTANTS.BLACK_SAMPLE_SIZE
            raw = ctypes.string_at(data.value, linesize.value * sample_h)
        finally:
            self.gfx.gs_stagesurface_unmap(self.stagesurf)
        return max_rgb(raw, sample_w, sample_h, linesize.value)

    def destroy(self) -> None:
        if not (self.texrender or self.stagesurf):
            return
        gfx = self.gfx
        gfx.obs_enter_graphics()
        try:
            if self.texrender:
                gfx.gs_texrender_destroy(self.texrender)
            if self.stagesurf:
                gfx.gs_stagesurface_destroy(self.stagesurf)
        finally:
            gfx.obs_leave_graphics()
        self.texrender = self.stagesurf = None
        self.staged = False


def sample_capture_luma(source_name: str) -> int | None:
    """Latest brightness sample of the game capture, or None if unavailable (never raises)."""
    if VARIABLES.luma_sampler_disabled:
        return None
    try:
        if VARIABLES.luma_sampler is None:
            VARIABLES.luma_sampler = CaptureLumaSampler(load_obs_graphics())
        return VARIABLES.luma_sampler.sample(source_name)
    except Exception:
        VARIABLES.luma_sampler_disabled = True
        _print("Auto scene: black-frame check is unavailable; auto scene keeps working without it.")
        _print(traceback.format_exc())
        return None


def run_rehook_step(current_scene: str, desktop_scene: str) -> bool:
    """
    One-shot rehook after a black fallback: once Desktop is on air, drop our showing ref for
    one tick (game capture unhooks when nothing shows it), then take it again (it re-hooks).
    Returns True while a step ran, so the tick makes no scene decision.
    """
    phase = VARIABLES.auto_scene_rehook_phase
    source = VARIABLES.auto_scene_source
    if not phase or source is None:
        return False
    if phase == "pending":
        if current_scene != desktop_scene:
            return False  # the Game scene would keep the capture showing
        if VARIABLES.auto_scene_showing_held:
            obs.obs_source_dec_showing(source)
            VARIABLES.auto_scene_showing_held = False
        VARIABLES.auto_scene_rehook_phase = "released"
        _print("Auto scene: re-hooking the game capture once.")
        return True
    if not VARIABLES.auto_scene_showing_held:
        obs.obs_source_inc_showing(source)
        VARIABLES.auto_scene_showing_held = True
    VARIABLES.auto_scene_rehook_phase = ""
    return True


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


if IS_WINDOWS:
    # Own WinDLL instance: typed prototypes here must not leak into other scripts' ctypes.windll.user32.
    _win_user32 = ctypes.WinDLL("user32")
    _win_user32.GetForegroundWindow.restype = wintypes.HWND
    _win_user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    _win_user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    _win_user32.MonitorFromWindow.restype = wintypes.HMONITOR
    _win_user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
    _win_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _win_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    _win_user32.GetWindowLongW.restype = wintypes.LONG
    _win_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _win_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    # PyDLL keeps the GIL: the key thread makes ~30 of these sub-microsecond calls per poll.
    _get_async_key_state = ctypes.PyDLL("user32").GetAsyncKeyState
    _get_async_key_state.argtypes = (ctypes.c_int,)
    _get_async_key_state.restype = ctypes.c_short
else:
    _win_user32 = None
    _get_async_key_state = None


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


if IS_WINDOWS:
    _win_kernel32 = ctypes.WinDLL("kernel32")
    _win_kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _win_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _win_kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    _win_kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    _win_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _win_kernel32.OpenProcess.restype = wintypes.HANDLE
    _win_kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _win_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
else:
    _win_kernel32 = None

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def list_processes() -> list[tuple[int, str]]:
    """(pid, exe file name) of every running process. Read-only Toolhelp snapshot."""
    snapshot = _win_kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        raise OSError("CreateToolhelp32Snapshot failed.")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        processes = []
        ok = _win_kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            processes.append((entry.th32ProcessID, entry.szExeFile))
            ok = _win_kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return processes
    finally:
        _win_kernel32.CloseHandle(snapshot)


def get_process_image_path(pid: int) -> str | None:
    """Full image path of a process, or None when it can't be read (e.g. an elevated process)."""
    handle = _win_kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _win_kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        _win_kernel32.CloseHandle(handle)


def other_obs_pids(processes, own_pid: int) -> list[int]:
    """PIDs of OBS processes other than this one (any path: a second copy of the same OBS counts too)."""
    name = CONSTANTS.OBS_PROCESS_NAME.casefold()
    return [pid for pid, exe in processes if pid != own_pid and exe.casefold() == name]


def describe_other_obs(processes, own_pid: int, path_of) -> str | None:
    """Human-readable list of other running OBS instances, or None. Unreadable paths still count."""
    pids = other_obs_pids(processes, own_pid)
    if not pids:
        return None
    return ", ".join(path_of(pid) or f"pid {pid}, path not readable" for pid in pids)


def scan_other_obs() -> None:
    """
    Worker thread: refreshes VARIABLES.other_obs. A failed scan keeps the previous answer
    (logged once). Never raises; calls no obspython API.
    """
    try:
        VARIABLES.other_obs = describe_other_obs(list_processes(), os.getpid(), get_process_image_path)
    except Exception:
        if not VARIABLES.other_obs_error_logged:
            VARIABLES.other_obs_error_logged = True
            _print("Auto scene: cannot list processes to look for another OBS.")
            _print(traceback.format_exc())
    finally:
        VARIABLES.other_obs_answered_at = time.monotonic()
        VARIABLES.other_obs_scan_running = False


def other_obs_answer(now: float) -> tuple[bool, str | None]:
    """(answer is fresh, description of another running OBS or None)."""
    answered_at = VARIABLES.other_obs_answered_at
    fresh = answered_at is not None and now - answered_at < 2 * CONSTANTS.OTHER_OBS_CHECK_S
    return fresh, VARIABLES.other_obs


def request_other_obs_scan(now: float) -> None:
    """
    Starts a background scan every OTHER_OBS_CHECK_S. A scan costs several ms (too much for the
    OBS graphics thread) and releases the GIL hundreds of times, so it never runs inside the tick.
    """
    checked_at = VARIABLES.other_obs_checked_at
    if VARIABLES.other_obs_scan_running or (
            checked_at is not None and now - checked_at < CONSTANTS.OTHER_OBS_CHECK_S):
        return
    VARIABLES.other_obs_checked_at = now
    VARIABLES.other_obs_scan_running = True
    try:
        Thread(target=scan_other_obs, daemon=True, name=WORKER_THREAD_NAME).start()
    except Exception:
        VARIABLES.other_obs_scan_running = False


_OBS_NATIVE = None  # (libobs, frontend) ctypes handles, loaded on first scene switch


def get_foreground_window_geometry(hwnd=None):
    """(window_rect, monitor_rect, class_name, style) of the foreground window (or `hwnd`), or None."""
    hwnd = hwnd or _win_user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not _win_user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    monitor = _win_user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not monitor or not _win_user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    class_name = ctypes.create_unicode_buffer(256)
    _win_user32.GetClassNameW(hwnd, class_name, 256)
    style = _win_user32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF  # GWL_STYLE
    m = info.rcMonitor
    return (rect.left, rect.top, rect.right, rect.bottom), (m.left, m.top, m.right, m.bottom), class_name.value, style


def classify_foreground(executable_path) -> tuple[str, bool]:
    """(exe file name, is fullscreen game) for the current foreground window."""
    exe = exe_basename(executable_path)
    if not executable_path or VARIABLES.cached_active_window_pid == os.getpid():
        return exe, False
    geometry = get_foreground_window_geometry()
    if geometry is None:
        return exe, False
    window_rect, monitor_rect, class_name, style = geometry
    return exe, is_fullscreen_game_window(window_rect, monitor_rect, class_name, style, exe,
                                          app_display_name(executable_path), VARIABLES.other_names)


def set_auto_scene_status(status: str) -> None:
    if status != VARIABLES.auto_scene_status:
        VARIABLES.auto_scene_status = status
        _print(f"Auto scene: {status}")


def get_live_source(name: str):
    """Strong reference to a not-removed source by name, or None. Caller releases."""
    if not name:
        return None
    source = obs.obs_get_source_by_name(name)
    if source is not None and obs.obs_source_removed(source):
        obs.obs_source_release(source)
        return None
    return source


def scene_exists(name: str) -> bool:
    source = get_live_source(name)
    if source is None:
        return False
    try:
        return obs.obs_scene_from_source(source) is not None
    finally:
        obs.obs_source_release(source)


def on_game_capture_hooked(calldata):
    machine = VARIABLES.auto_scene_machine
    if machine is not None:
        machine.hooked_exe = exe_basename(obs.calldata_string(calldata, "executable")) or HOOKED_EXE_UNKNOWN


def on_game_capture_unhooked(calldata):
    machine = VARIABLES.auto_scene_machine
    if machine is not None:
        machine.hooked_exe = None


GAME_CAPTURE_SIGNALS = (("hooked", on_game_capture_hooked), ("unhooked", on_game_capture_unhooked))


def auto_scene_attach(source_name: str) -> bool:
    """
    Takes the game capture: strong ref, hooked/unhooked signals, showing ref. Must run while
    obspython's current script is this one (see auto_scene_prepare). If connecting fails, every
    partial step is undone before the error propagates, so nothing leaks.
    """
    source = get_live_source(source_name)
    if source is None:
        return False
    if obs.obs_source_get_unversioned_id(source) != "game_capture":
        obs.obs_source_release(source)
        return False

    machine = AutoSceneMachine()
    # Already capturing (e.g. scripts reloaded mid-game): `hooked` will not fire again.
    if obs.obs_source_get_width(source) > 0:
        machine.hooked_exe = HOOKED_EXE_UNKNOWN
    VARIABLES.auto_scene_machine = machine

    handler = obs.obs_source_get_signal_handler(source)
    connected = []
    try:
        for signal, callback in GAME_CAPTURE_SIGNALS:
            obs.signal_handler_connect(handler, signal, callback)
            connected.append((signal, callback))
    except Exception:
        for signal, callback in connected:
            with suppress(Exception):
                obs.signal_handler_disconnect(handler, signal, callback)
        VARIABLES.auto_scene_machine = None
        obs.obs_source_release(source)
        raise
    # Keep the capture hooking while Desktop is on air; balanced in auto_scene_detach().
    obs.obs_source_inc_showing(source)
    VARIABLES.auto_scene_showing_held = True
    VARIABLES.auto_scene_rehook_phase = ""
    VARIABLES.auto_scene_source = source
    return True


def auto_scene_detach() -> None:
    source = VARIABLES.auto_scene_source
    if source is None:
        return
    VARIABLES.auto_scene_source = None
    VARIABLES.auto_scene_machine = None
    handler = None
    with suppress(Exception):
        handler = obs.obs_source_get_signal_handler(source)
    for signal, callback in GAME_CAPTURE_SIGNALS:
        # A failed disconnect is harmless: the callbacks ignore signals while detached, and
        # OBS drops the script's callbacks when the script unloads.
        with suppress(Exception):
            obs.signal_handler_disconnect(handler, signal, callback)
    with suppress(Exception):
        if VARIABLES.auto_scene_showing_held:  # not held mid-rehook
            obs.obs_source_dec_showing(source)
    VARIABLES.auto_scene_showing_held = False
    VARIABLES.auto_scene_rehook_phase = ""
    obs.obs_source_release(source)


def get_loaded_module_handle(name: str):
    """Handle of a DLL already loaded in this (OBS) process; never loads another copy."""
    get_module = ctypes.WinDLL("kernel32").GetModuleHandleW
    get_module.argtypes = (wintypes.LPCWSTR,)
    get_module.restype = wintypes.HMODULE
    handle = get_module(name)
    if not handle:
        raise OSError(f"{name} is not loaded in this process.")
    return handle


def load_obs_native():
    """ctypes views of the already-loaded obs.dll and obs-frontend-api.dll (calls release the GIL)."""
    libobs = ctypes.CDLL("obs.dll", handle=get_loaded_module_handle("obs.dll"))
    frontend = ctypes.CDLL("obs-frontend-api.dll", handle=get_loaded_module_handle("obs-frontend-api.dll"))
    libobs.obs_get_source_by_name.argtypes = (ctypes.c_char_p,)
    libobs.obs_get_source_by_name.restype = ctypes.c_void_p
    libobs.obs_source_release.argtypes = (ctypes.c_void_p,)
    libobs.obs_source_release.restype = None
    frontend.obs_frontend_set_current_scene.argtypes = (ctypes.c_void_p,)
    frontend.obs_frontend_set_current_scene.restype = None
    return libobs, frontend


def set_current_scene_by_name(name: str) -> bool:
    """
    Switches the program scene through ctypes, which releases the GIL. The obspython wrapper
    keeps the GIL while obs_frontend_set_current_scene blocks on the UI thread, and the UI
    thread needs the GIL for Python frontend-event callbacks: a deadlock.
    """
    global _OBS_NATIVE
    if _OBS_NATIVE is None:
        _OBS_NATIVE = load_obs_native()
    libobs, frontend = _OBS_NATIVE
    source = libobs.obs_get_source_by_name(name.encode("utf-8"))
    if not source:
        return False
    try:
        frontend.obs_frontend_set_current_scene(source)
    finally:
        libobs.obs_source_release(source)
    return True


def request_scene_switch(name: str) -> None:
    """Switches on a worker thread so the OBS video thread never waits for the UI thread."""
    if VARIABLES.auto_scene_switch_in_flight:
        return
    VARIABLES.auto_scene_switch_in_flight = True

    def worker():
        try:
            if set_current_scene_by_name(name):
                _print(f"Auto scene: switched to '{name}'.")
            else:
                _print(f"Auto scene: scene '{name}' not found.")
        except Exception:
            _print(f"Auto scene: cannot switch to '{name}'.")
            _print(traceback.format_exc())
        finally:
            VARIABLES.auto_scene_switch_in_flight = False

    try:
        Thread(target=worker, daemon=True, name=WORKER_THREAD_NAME).start()
    except Exception:
        VARIABLES.auto_scene_switch_in_flight = False
        _print(traceback.format_exc())


def auto_scene_prepare(current_scene: str) -> tuple[str, str, str] | None:
    """
    First step of every tick: decides whether auto scene is active and attaches/detaches the
    game capture. Returns (game scene, desktop scene, source name) when switching should run.

    Everything that registers or removes Python callbacks (signal connect/disconnect) happens
    here, before anything that releases the GIL (ctypes WinDLL calls, thread starts). obspython
    keeps "the current script" in one process-wide variable; while this thread has released the
    GIL another thread's script callback can end and reset it, and signal_handler_connect then
    fails with "No active script" (seen on the first tick after load in OBS 33).

    Active only when the setting is on, both scenes and the game capture exist, and a fresh
    process scan found no other OBS.
    """
    settings = VARIABLES.script_settings
    if (settings is None or VARIABLES.auto_scene_blocked or
            not obs.obs_data_get_bool(settings, PN.PROP_AUTO_SCENE_ENABLED)):
        auto_scene_detach()
        set_auto_scene_status("off")
        return None

    game_scene = obs.obs_data_get_string(settings, PN.PROP_AUTO_SCENE_GAME)
    desktop_scene = obs.obs_data_get_string(settings, PN.PROP_AUTO_SCENE_DESKTOP)
    source_name = obs.obs_data_get_string(settings, PN.PROP_AUTO_SCENE_GAME_SOURCE)
    if game_scene == desktop_scene or not (scene_exists(game_scene) and scene_exists(desktop_scene)):
        auto_scene_detach()
        set_auto_scene_status(f"waiting for scenes '{game_scene}' and '{desktop_scene}'")
        return None

    now = time.monotonic()
    fresh, other_obs = other_obs_answer(now)
    try:
        # Only one OBS can hold a game's hook: while another OBS runs, release the capture
        # (game capture unhooks once nothing shows it) and stay off the Game scene.
        if other_obs:
            auto_scene_detach()
            VARIABLES.other_obs_paused = True
            set_auto_scene_status(
                f"another OBS is running ({other_obs}); game capture paused so its game hook is left alone")
            if current_scene == game_scene and not VARIABLES.auto_scene_switch_in_flight:
                request_scene_switch(desktop_scene)
            return None
        if not fresh:  # never attach on a stale "no other OBS" (first tick, or auto scene was off)
            auto_scene_detach()
            set_auto_scene_status("checking whether another OBS is running")
            return None
        if VARIABLES.other_obs_paused:
            VARIABLES.other_obs_paused = False
            _print("Auto scene: no other OBS is running any more; resuming game capture.")

        source = VARIABLES.auto_scene_source
        if source is not None and (obs.obs_source_removed(source) or obs.obs_source_get_name(source) != source_name):
            auto_scene_detach()
        if VARIABLES.auto_scene_source is None:
            try:
                attached = auto_scene_attach(source_name)
            except RuntimeError:  # "No active script": already cleaned up, retry next tick
                set_auto_scene_status("OBS script context was busy; retrying the game capture next second")
                return None
            if not attached:
                set_auto_scene_status(f"waiting for game capture source '{source_name}'")
                return None
        set_auto_scene_status(f"on ('{game_scene}' / '{desktop_scene}', source '{source_name}')")
        return game_scene, desktop_scene, source_name
    finally:
        request_other_obs_scan(now)  # starts a thread (releases the GIL): keep it last


def auto_scene_tick(executable_path, current_scene: str) -> None:
    """One auto scene tick, in the order foreground_tick runs it."""
    names = auto_scene_prepare(current_scene)
    if names:
        auto_scene_switching(executable_path, current_scene, names)


def auto_scene_switching(executable_path, current_scene: str, names: tuple[str, str, str]) -> None:
    """Second step of the tick: black-frame check, rehook and the Game/Desktop decision."""
    game_scene, desktop_scene, source_name = names
    machine = VARIABLES.auto_scene_machine
    if machine is None:  # detached by another thread since prepare
        return
    if VARIABLES.black_guard is None:
        VARIABLES.black_guard = BlackFrameGuard()
    guard = VARIABLES.black_guard
    now = time.monotonic()
    if run_rehook_step(current_scene, desktop_scene):
        return
    guard.observe(now, sample_capture_luma(source_name) if machine.hooked_exe else None)

    if VARIABLES.auto_scene_switch_in_flight:
        return
    fg_exe, fg_is_game = classify_foreground(executable_path)
    hooked = machine.hooked_exe
    process = hooked if hooked not in (None, HOOKED_EXE_UNKNOWN) else fg_exe

    if current_scene == game_scene and hooked and guard.should_fall_back(now):
        if guard.fall_back(now, process):
            VARIABLES.auto_scene_rehook_phase = "pending"
        _print(f"Auto scene: '{source_name}' shows only black frames for {process or 'the game'}; "
               f"showing '{desktop_scene}' and keeping it off '{game_scene}' for {guard.cooldown_s:.0f}s.")
        request_scene_switch(desktop_scene)
        return

    target = machine.decide(now, current_scene, fg_exe, fg_is_game, game_scene, desktop_scene,
                            game_allowed=guard.can_show_game(now, process))
    if target:
        request_scene_switch(target)


def on_scene_collection_event_callback(event):
    """
    Releases the Game Capture reference before OBS tears sources down, and timestamps scene
    changes in the moment timeline.
    """
    if event == getattr(obs, "OBS_FRONTEND_EVENT_SCENE_CHANGED", None):
        record_scene_change()
        return
    release_events = {getattr(obs, name, None) for name in (
        "OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGING",
        "OBS_FRONTEND_EVENT_SCENE_COLLECTION_CLEANUP",
        "OBS_FRONTEND_EVENT_EXIT",
    )} - {None}
    resume_events = {getattr(obs, name, None) for name in (
        "OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED",
        "OBS_FRONTEND_EVENT_FINISHED_LOADING",
    )} - {None}
    if event in release_events:
        VARIABLES.auto_scene_blocked = True
        auto_scene_detach()
    elif event in resume_events:
        VARIABLES.auto_scene_blocked = False


# -------------------- key_recorder.py --------------------
KEY_VKS = {  # the fixed, ordered set of recorded keys (contract: CLIP_INFO.md section 6)
    **{str(n): 0x30 + n for n in range(1, 6)},
    **{letter: ord(letter) for letter in "QWERTASDFGZXCV"},
    "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12, "SPACE": 0x20, "TAB": 0x09,
    "LMB": 0x01, "RMB": 0x02, "MMB": 0x04, "MB4": 0x05, "MB5": 0x06,
}
# Never a game even when fullscreen, whatever the user's Other list says (exe stems, casefolded):
# typing happens there, so it must not be recorded.
KEY_NEVER_APPS = frozenset((
    "chrome", "msedge", "firefox", "opera", "opera_gx", "brave", "vivaldi", "arc", "browser", "chromium",
    "waterfox", "librewolf", "zen", "iexplore", "discord", "discordptb", "discordcanary", "telegram", "signal",
    "whatsapp", "slack", "zoom", "skype", "teams", "ms-teams", "vlc", "mpv", "mpc-hc", "mpc-hc64", "mpc-be64",
    "potplayermini64", "potplayermini", "kmplayer", "smplayer", "wmplayer", "momentplayer", "moment player",
    "windowsterminal", "wt", "cmd", "powershell", "pwsh", "conhost", "alacritty", "wezterm-gui", "mintty",
    "code", "cursor", "explorer", "obs64", "obs",
))
# Profile section "Hotkeys": OBS 33 has its own frontend hotkey and reads the older entry only until that exists.
SAVE_KEY_SOURCES = (("OBSBasic.SaveReplayBuffer", "bindings"), ("ReplayBuffer", "ReplayBuffer.Save"))
SAVE_KEY_MODIFIERS = {"shift": (0x10,), "control": (0x11,), "alt": (0x12,), "command": (0x5B, 0x5C)}
ANCHOR_SCRIPT_HOTKEY = "script hotkey"
ANCHOR_SAVE_KEY = "OBS save key"


class GameInFront:
    """
    True while the window in front is the game: OBS's fullscreen-game rule, or the exe the game
    capture has hooked. Any doubt counts as no: no foreground window, our own OBS, an unreadable
    process, an app in the Other list or in KEY_NEVER_APPS.
    """

    def __init__(self):
        self._window = None  # (hwnd, pid) the cached names belong to
        self._exe = self._app = ""

    def __call__(self) -> bool:
        hwnd = _win_user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        _win_user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value == os.getpid():
            return False
        if self._window != (hwnd, pid.value):
            path = get_process_image_path(pid.value)
            self._exe = exe_basename(path)
            self._app = app_display_name(path) if path else ""
            self._window = (hwnd, pid.value)
        if not self._exe:
            return False
        stem = normalize_rule_name(Path(self._exe).stem)
        if stem in KEY_NEVER_APPS or {stem, normalize_rule_name(self._app)} & VARIABLES.other_names:
            return False

        geometry = get_foreground_window_geometry(hwnd)
        if geometry is None:
            return False
        window_rect, monitor_rect, class_name, style = geometry
        if is_fullscreen_game_window(window_rect, monitor_rect, class_name, style, self._exe, self._app,
                                     VARIABLES.other_names):
            return True
        machine = VARIABLES.auto_scene_machine
        hooked = machine.hooked_exe if machine is not None else None
        return (hooked not in (None, HOOKED_EXE_UNKNOWN) and hooked == self._exe and
                class_name.casefold() not in SHELL_WINDOW_CLASSES)


class KeyRecorder:
    """
    Press times of the keys in KEY_VKS, recorded only while `game_in_front()` says the game is in
    front, plus the last presses of OBS's own save key (to anchor a replay's end; Shift, Ctrl, Alt
    and Win are looked at only while that key is down).

    One thread polls GetAsyncKeyState about 250 times a second; nothing here hooks anything or runs
    in the game's process. Key times stay in memory (for the length of the buffer/recording) and leave
    it only inside a clip the user saves; they are never logged. No obspython calls: worker thread.
    """

    def __init__(self, game_in_front, key_state):
        self._game_in_front = game_in_front
        self._key_state = key_state
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._polls = 0
        self._last_poll = 0.0
        self._game = False
        self._open: dict[str, float] = {}  # keys held now: press time
        self._closed: dict[str, deque] = {name: deque(maxlen=CONSTANTS.KEY_LOG_MAXLEN) for name in KEY_VKS}
        self._focus: deque = deque(maxlen=CONSTANTS.KEY_LOG_MAXLEN)  # [start, end or None] while the game was in front
        self._save_bindings: tuple = ()
        self._save_active: set = set()
        self._error_logged = False

    # --- thread ---
    def start(self) -> None:
        self._thread = Thread(target=self._run, daemon=True, name=WORKER_THREAD_NAME)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        # Event.wait follows the Windows timer: 15.6 ms by default (about 65 polls a second, measured).
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
        try:
            self._poll_until_stopped()
        finally:
            winmm.timeEndPeriod(1)

    def _poll_until_stopped(self) -> None:
        due = time.perf_counter()
        while not self._stop.is_set():
            try:
                self.poll(time.time())
            except Exception:
                with suppress(Exception):
                    with self._lock:
                        self._release(time.time())
                if not self._error_logged:
                    self._error_logged = True
                    _print("Key recording: a poll failed; recording continues.")
                    _print(traceback.format_exc())
            due = max(due + CONSTANTS.KEY_POLL_S, time.perf_counter())
            self._stop.wait(max(due - time.perf_counter(), 0.001))

    # --- polling ---
    def poll(self, now: float) -> None:
        cache: dict[int, int] = {}

        def read(vk: int) -> int:  # one GetAsyncKeyState call per key per poll: it clears the low bit
            if vk not in cache:
                cache[vk] = self._key_state(vk)
            return cache[vk]

        self._poll_save_keys(now, read)
        if not VARIABLES.record_inputs:
            self._forget()
            return
        try:
            game = bool(self._game_in_front())
        except Exception:
            game = False  # any doubt: record nothing
        with self._lock:
            self._poll_keys(now, game, read)
            self._polls += 1
            if self._polls % 250 == 0:  # about once a second
                self._trim(now)

    def _poll_save_keys(self, now: float, read) -> None:
        """Same rule as OBS: pressed = the key is down with exactly its own modifiers (Ctrl+F10 is not F10)."""
        bindings = VARIABLES.save_key_bindings
        changed = bindings != self._save_bindings  # first poll or rebound: low bits and held keys are stale
        if changed:
            self._save_bindings, self._save_active = bindings, set()
        for binding in bindings:
            vk, modifiers = binding
            state = read(vk)
            match = bool(state & 0x8001) and all(
                any(read(m) & 0x8000 for m in vks) == (name in modifiers)
                for name, vks in SAVE_KEY_MODIFIERS.items())
            if match and state & 0x8000:
                if binding not in self._save_active and not changed:
                    VARIABLES.save_key_presses.append(now)
                self._save_active.add(binding)
            elif binding in self._save_active:
                self._save_active.discard(binding)
            elif match and not changed:  # pressed and released between two polls
                VARIABLES.save_key_presses.append(now)

    def _poll_keys(self, now: float, game: bool, read) -> None:
        if not game:
            self._release(now)
            return
        prime = not self._game  # just came to the front: presses before this moment don't count
        if prime:
            self._game = True
            self._focus.append([now, None])
        for name, vk in KEY_VKS.items():
            state = read(vk)
            if state & 0x8000:
                self._open.setdefault(name, now)
            elif name in self._open:
                self._closed[name].append((self._open.pop(name), now))
            elif state & 1 and not prime:  # pressed and released between two polls
                self._closed[name].append((max(self._last_poll, now - 2 * CONSTANTS.KEY_POLL_S), now))
        self._last_poll = now

    def _release(self, now: float) -> None:
        """The game is not in front: every key counts as released."""
        if not self._game:
            return
        self._game = False
        self._focus[-1][1] = now
        for name, down in self._open.items():
            self._closed[name].append((down, now))
        self._open.clear()

    def _forget(self) -> None:
        """Recording is off: drop everything (save-key presses stay, they aren't game input)."""
        if not (self._focus or self._open):
            return
        with self._lock:
            self._game = False
            self._open.clear()
            self._focus.clear()
            for closed in self._closed.values():
                closed.clear()

    # --- memory ---
    def _keep_since(self, now: float) -> float:
        keep = now - (VARIABLES.buffer_max_time + 10 if VARIABLES.buffer_active else 0)
        if VARIABLES.recording_active and VARIABLES.recording_started_at is not None:
            keep = min(keep, VARIABLES.recording_started_at - 1)
        return keep

    def _trim(self, now: float) -> None:
        keep = self._keep_since(now)
        for closed in self._closed.values():
            while closed and closed[0][1] < keep:
                closed.popleft()
        while self._focus and self._focus[0][1] is not None and self._focus[0][1] < keep:
            self._focus.popleft()

    def snapshot(self) -> dict:
        """{"focus": [(start, end or None)], "keys": {name: [(down, up or None)]}} in wall-clock times."""
        with self._lock:
            keys = {name: list(closed) for name, closed in self._closed.items()}
            for name, down in self._open.items():
                keys[name].append((down, None))
            return {"focus": [tuple(span) for span in self._focus], "keys": keys}


def sync_key_recorder() -> None:
    """
    Starts or stops the key thread. Call it last in a script callback: it may start or join a
    thread (that releases the GIL) and obspython registrations must not come after that.
    """
    wanted = IS_WINDOWS and (VARIABLES.buffer_active or (VARIABLES.recording_active and VARIABLES.record_inputs))
    recorder = VARIABLES.key_recorder
    try:
        if wanted and recorder is None:
            recorder = KeyRecorder(GameInFront(), _get_async_key_state)
            VARIABLES.key_recorder = recorder
            recorder.start()
        elif not wanted and recorder is not None:
            VARIABLES.key_recorder = None
            recorder.stop()
    except Exception:
        VARIABLES.key_recorder = None
        _print("Key recording: cannot start or stop the key thread.")
        _print(traceback.format_exc())


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
         lambda pressed: open_last_saved_video() if pressed else None),

        (PN.HK_RECORD_ALT, "[Moment Replays] Start/stop recording (alternative folder)",
         lambda pressed: toggle_alt_recording_save() if pressed else None),

        (PN.HK_MARK_MOMENT, "[Moment Replays] Mark moment",
         lambda pressed: mark_moment() if pressed else None)
    )

    for key_name, key_desc, key_callback in keys:
        key_id = obs.obs_hotkey_register_frontend(key_name, key_desc, key_callback)
        VARIABLES.hotkey_ids.update({key_name: key_id})
        key_data = obs.obs_data_get_array(VARIABLES.script_settings, key_name)
        default = HOTKEY_DEFAULTS.get(key_name)
        if default and not obs.obs_data_has_user_value(VARIABLES.script_settings, key_name):
            default_data = build_default_hotkey_data(default[0], **default[1])
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
        on_recording_stopping_callback,
        on_recording_stopped_callback,
        on_buffer_save_callback,
        on_buffer_recording_started_callback,
        on_buffer_recording_stopped_callback,
        on_scene_collection_event_callback
    ):
        with suppress(Exception):
            remove_event_callback(callback)


def register_frontend_event_callbacks() -> None:
    unregister_frontend_event_callbacks()
    obs.obs_frontend_add_event_callback(on_recording_started_callback)
    obs.obs_frontend_add_event_callback(on_recording_stopping_callback)
    obs.obs_frontend_add_event_callback(on_recording_stopped_callback)
    obs.obs_frontend_add_event_callback(on_buffer_save_callback)
    obs.obs_frontend_add_event_callback(on_buffer_recording_started_callback)
    obs.obs_frontend_add_event_callback(on_buffer_recording_stopped_callback)
    obs.obs_frontend_add_event_callback(on_scene_collection_event_callback)


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

    # Schema 6 migration: auto scene is opt-in. A sidecar without the key (any pre-1.6 setup,
    # e.g. one driven by Advanced Scene Switcher) stays off; only the installer writes `true`.
    persisted_settings.setdefault(PN.PROP_AUTO_SCENE_ENABLED, False)

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
    if not obs.obs_data_get_bool(settings, PN.PROP_AUTO_SCENE_ENABLED):
        auto_scene_detach()  # balance inc_showing right away; foreground_tick re-attaches when re-enabled
    VARIABLES.sidecar_persist_enabled = True
    VARIABLES.record_inputs = obs.obs_data_get_bool(settings, PN.PROP_RECORD_INPUTS)
    _print("Script updated")
    sync_key_recorder()


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
    VARIABLES.alt_recording_pending = False
    VARIABLES.saved_recording_path = None
    VARIABLES.auto_scene_blocked = False
    VARIABLES.auto_scene_status = ""
    VARIABLES.unloading.clear()
    VARIABLES.record_inputs = obs.obs_data_get_bool(script_settings, PN.PROP_RECORD_INPUTS)
    VARIABLES.recording_active = bool(obs.obs_frontend_recording_active())
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
        reset_buffer_history()
        VARIABLES.buffer_started_at = None  # started before this load: assume a full buffer
    # A recording already running has an unknown start, so it gets no .moment.json.
    VARIABLES.recording_started_at = None
    obs.timer_add(foreground_tick, CONSTANTS.FOREGROUND_TICK_MS)

    VARIABLES.sidecar_persist_enabled = True
    start_update_check_thread()
    sync_key_recorder()
    _print("Script loaded.")


def script_unload():
    VARIABLES.sidecar_persist_enabled = False
    VARIABLES.unloading.set()  # clip info still waiting for a file stops retrying and uses the sidecar
    unregister_frontend_event_callbacks()
    if VARIABLES.script_settings is not None:
        save_persisted_settings_from_obs_data(VARIABLES.script_settings, allow_when_disabled=True)
    obs.timer_remove(foreground_tick)
    obs.timer_remove(stop_mark_feedback)
    auto_scene_detach()
    if VARIABLES.luma_sampler is not None:
        with suppress(Exception):
            VARIABLES.luma_sampler.destroy()
        VARIABLES.luma_sampler = None
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
    restore_recording_path()
    cancel_alt_recording_watchdog()
    VARIABLES.alt_recording_pending = False
    reset_forced_save_state()

    # Joins release the GIL, so nothing that needs obspython comes after this point.
    recorder, VARIABLES.key_recorder = VARIABLES.key_recorder, None
    if recorder is not None:
        recorder.stop()
    VARIABLES.buffer_active = VARIABLES.recording_active = False
    sound_dir, VARIABLES.sound_dir = VARIABLES.sound_dir, None
    if sound_dir is not None:
        stop_playing_sound()  # its file goes away
        with suppress(Exception):
            sound_dir.cleanup()
    deadline = time.monotonic() + 3
    for thread in list(VARIABLES.pending_info_writes):
        thread.join(max(deadline - time.monotonic(), 0))

    flush_deferred_logs()
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
