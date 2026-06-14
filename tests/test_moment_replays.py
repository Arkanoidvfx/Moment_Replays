"""
Unit tests for Moment Replays (arkanoid_replays.py).

These tests stub the `obspython` module so the OBS script can be imported and
its pure logic exercised outside OBS. Run with:

    python -m unittest discover -s tests
    # or
    python tests/test_moment_replays.py

No third-party dependencies — standard library only.
"""

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "arkanoid_replays.py"


def load_module():
    """Import arkanoid_replays.py with a stubbed obspython module."""
    stub = types.ModuleType("obspython")
    stub.obs_get_version_string = lambda: "31.0.0"
    stub._last_recording = ""
    stub._last_replay = ""
    stub.obs_frontend_get_last_recording = lambda: stub._last_recording
    stub.obs_frontend_get_last_replay = lambda: stub._last_replay
    sys.modules["obspython"] = stub

    spec = importlib.util.spec_from_file_location("moment_replays_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._obs_stub = stub
    return module


ar = load_module()


class TestVersionCompare(unittest.TestCase):
    def test_parse_strips_v_prefix(self):
        self.assertEqual(ar.parse_version_parts("v1.2.3"), (1, 2, 3))
        self.assertEqual(ar.parse_version_parts("1.0"), (1, 0))

    def test_is_newer(self):
        self.assertTrue(ar.is_newer_version("v1.1", "1.0"))
        self.assertTrue(ar.is_newer_version("2", "1.9"))
        self.assertTrue(ar.is_newer_version("1.10", "1.9"))
        self.assertFalse(ar.is_newer_version("1.0", "1.0"))
        self.assertFalse(ar.is_newer_version("1.0", "1.1"))

    def test_is_newer_handles_garbage(self):
        self.assertFalse(ar.is_newer_version("", "1.0"))
        self.assertFalse(ar.is_newer_version("abc", "1.0"))


class TestFilename(unittest.TestCase):
    def test_name_and_strftime(self):
        out = ar.gen_filename("MyClip", "%NAME_%Y")
        self.assertTrue(out.startswith("MyClip_"))
        self.assertEqual(len(out.split("_")[-1]), 4)  # 4-digit year

    def test_empty_template_raises_value_error(self):
        with self.assertRaises(ValueError):
            ar.gen_filename("Clip", "")

    def test_prohibited_chars_raise_syntax_error(self):
        with self.assertRaises(SyntaxError):
            ar.gen_filename("Clip", "%NAME:x")  # ':' is prohibited

    def test_ensure_unique_filename(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "clip.mp4"
            p.write_bytes(b"x")
            unique = ar.ensure_unique_filename(p)
            self.assertEqual(unique.name, "clip (1).mp4")


class TestSanitize(unittest.TestCase):
    def test_separators_and_colon(self):
        self.assertEqual(ar.sanitize_clip_component("Game: Boss"), "Game_ Boss")
        self.assertEqual(ar.sanitize_clip_component("a/b"), "a_b")

    def test_reserved_windows_names(self):
        self.assertEqual(ar.sanitize_clip_component("CON"), "UnknownApp")
        self.assertEqual(ar.sanitize_clip_component("com1"), "UnknownApp")

    def test_dots_and_empty(self):
        self.assertEqual(ar.sanitize_clip_component(".."), "UnknownApp")
        self.assertEqual(ar.sanitize_clip_component("   "), "UnknownApp")
        self.assertEqual(ar.sanitize_clip_component("name."), "name")

    def test_normal_and_unicode_preserved(self):
        self.assertEqual(ar.sanitize_clip_component("Minecraft"), "Minecraft")
        self.assertEqual(ar.sanitize_clip_component("Привет"), "Привет")


class TestDriveGuard(unittest.TestCase):
    def test_same_drive_ok(self):
        ar.ensure_same_drive_for_rename("C:/a/x.mp4", "C:/b/y.mp4")  # no raise

    def test_cross_drive_raises(self):
        with self.assertRaises(OSError):
            ar.ensure_same_drive_for_rename("C:/a/x.mp4", "D:/b/y.mp4")


class TestAliases(unittest.TestCase):
    def test_exact_and_parent_lookup(self):
        aliases = {Path("C:/games/game.exe"): "Game", Path("C:/launcher"): "Launcher"}
        self.assertEqual(ar.get_alias("C:/games/game.exe", aliases), "Game")
        self.assertEqual(ar.get_alias("C:/launcher/sub/app.exe", aliases), "Launcher")
        self.assertIsNone(ar.get_alias("C:/other/thing.exe", aliases))

    def test_validate_valid(self):
        result = ar.validate_aliases_list([{"value": "C:/games > Game"}])
        self.assertEqual(result, {Path("C:/games"): "Game"})

    def test_validate_invalid_format(self):
        with self.assertRaises(ar.AliasInvalidFormat):
            ar.validate_aliases_list([{"value": "no separator here"}])

    def test_validate_invalid_chars(self):
        with self.assertRaises(ar.AliasInvalidCharacters):
            ar.validate_aliases_list([{"value": "C:/games > Ba<d"}])

    def test_validate_duplicate_path(self):
        with self.assertRaises(ar.AliasPathAlreadyExists):
            ar.validate_aliases_list([{"value": "C:/g > A"}, {"value": "C:/g > B"}])


class TestAppRules(unittest.TestCase):
    def test_name_replacements(self):
        ar.load_name_replacements({"app_name_replacements": [{"value": "TslGame > PUBG"}]})
        self.assertEqual(ar.apply_app_name_replacement("TslGame"), "PUBG")
        self.assertEqual(ar.apply_app_name_replacement("tslgame"), "PUBG")  # case-insensitive
        self.assertEqual(ar.apply_app_name_replacement("Unmapped"), "Unmapped")

    def test_other_folder_routing(self):
        ar.load_other_names({"app_other_names": [{"value": "chrome"}, {"value": "OBS"}]})
        self.assertEqual(
            ar.get_target_clip_folder_name("Chrome", ar.ClipNamingModes.CURRENT_PROCESS),
            ar.CONSTANTS.OTHER_FOLDER_NAME,
        )
        self.assertEqual(
            ar.get_target_clip_folder_name("MyGame", ar.ClipNamingModes.CURRENT_PROCESS),
            "MyGame",
        )

    def test_scene_mode_never_routed_to_other(self):
        ar.load_other_names({"app_other_names": [{"value": "chrome"}]})
        self.assertEqual(
            ar.get_target_clip_folder_name("chrome", ar.ClipNamingModes.CURRENT_SCENE),
            "chrome",
        )


class TestPersistedSettings(unittest.TestCase):
    def setUp(self):
        self._orig_settings = ar.CONSTANTS.SETTINGS_PERSIST_PATH
        self._orig_legacy = ar.CONSTANTS.LEGACY_APP_RULES_PERSIST_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        ar.CONSTANTS.SETTINGS_PERSIST_PATH = Path(self._tmpdir.name) / "settings.json"
        ar.CONSTANTS.LEGACY_APP_RULES_PERSIST_PATH = Path(self._tmpdir.name) / "legacy.json"

    def tearDown(self):
        ar.CONSTANTS.SETTINGS_PERSIST_PATH = self._orig_settings
        ar.CONSTANTS.LEGACY_APP_RULES_PERSIST_PATH = self._orig_legacy
        self._tmpdir.cleanup()

    def test_roundtrip_drops_legacy_restart_keys(self):
        settings = {
            "clips_base_path": "D:\\X",
            "clips_naming_mode": 2,
            "short_buffer_percent": 25,
            "restart_buffer": True,       # legacy junk, must be dropped
            "restart_buffer_loop": 3600,  # legacy junk, must be dropped
            "app_other_names": [{"value": "chrome"}, {"value": "OBS"}],
            "app_name_replacements": [{"value": "TslGame > PUBG"}],
            "aliases_list": [{"value": "C:\\g > Game"}],
        }
        ar.save_persisted_settings_from_settings_dict(settings)

        raw = json.loads(ar.CONSTANTS.SETTINGS_PERSIST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], ar.CONSTANTS.SETTINGS_SCHEMA_VERSION)
        self.assertNotIn("restart_buffer", raw)
        self.assertNotIn("restart_buffer_loop", raw)
        self.assertTrue(raw["clips_save_to_folder"])
        self.assertEqual(raw["clips_base_path"], "D:\\X")
        self.assertEqual(raw["clips_naming_mode"], 2)

        loaded = ar.load_persisted_settings()
        self.assertEqual(loaded["clips_base_path"], "D:\\X")
        self.assertEqual(loaded["clips_naming_mode"], 2)
        self.assertEqual(loaded["short_buffer_percent"], 25)
        self.assertNotIn("restart_buffer", loaded)
        self.assertNotIn("restart_buffer_loop", loaded)
        self.assertEqual(loaded["app_other_names"], ["chrome", "OBS"])
        self.assertEqual(loaded["app_name_replacements"], ["TslGame > PUBG"])
        self.assertEqual(loaded["aliases_list"], ["C:\\g > Game"])

    def test_missing_file_returns_empty(self):
        self.assertEqual(ar.load_persisted_settings(), {})


class TestSoundPathMigration(unittest.TestCase):
    def test_empty_becomes_default(self):
        key = ar.PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH
        self.assertEqual(ar.normalize_default_sound_path(key, ""), ar.DEFAULT_SOUND_PATHS[key])

    def test_custom_path_kept(self):
        key = ar.PN.PROP_NOTIFY_CLIPS_ON_SUCCESS_PATH
        self.assertEqual(ar.normalize_default_sound_path(key, "C:/my/sound.wav"), "C:/my/sound.wav")


class TestOpenLastVideo(unittest.TestCase):
    def setUp(self):
        self._orig_startfile = getattr(ar.os, "startfile", None)
        self.opened = []
        ar.os.startfile = lambda p: self.opened.append(p)
        ar.VARIABLES.last_saved_clip_path = None
        ar._obs_stub._last_recording = ""
        ar._obs_stub._last_replay = ""
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        if self._orig_startfile is not None:
            ar.os.startfile = self._orig_startfile
        ar.VARIABLES.last_saved_clip_path = None
        self._tmpdir.cleanup()

    def _make(self, name, mtime):
        p = Path(self._tmpdir.name) / name
        p.write_bytes(b"x")
        os.utime(p, (mtime, mtime))
        return str(p)

    def test_opens_newest_candidate(self):
        clip = self._make("clip.mp4", 2000)
        rec = self._make("recording.mp4", 3000)
        rep = self._make("replay.mp4", 1000)
        ar.VARIABLES.last_saved_clip_path = clip
        ar._obs_stub._last_recording = rec
        ar._obs_stub._last_replay = rep
        ar.open_last_saved_video()
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(os.path.basename(self.opened[0]), "recording.mp4")

    def test_opens_script_clip_when_obs_empty(self):
        clip = self._make("clip.mp4", 2000)
        ar.VARIABLES.last_saved_clip_path = clip
        ar.open_last_saved_video()
        self.assertEqual(os.path.basename(self.opened[0]), "clip.mp4")

    def test_nothing_opened_when_missing(self):
        ar.VARIABLES.last_saved_clip_path = str(Path(self._tmpdir.name) / "gone.mp4")
        ar.open_last_saved_video()
        self.assertEqual(self.opened, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
