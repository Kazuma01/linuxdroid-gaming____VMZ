"""Editor puro e persistencia V2: historico, migracao e escrita atomica."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linuxdroid import storage
from linuxdroid.controls.keys import InputBinding
from linuxdroid.controls.model import (
    ControlProfileV2,
    ProfileError,
    ScreenContract,
)
from linuxdroid.input import BindingEditor
from linuxdroid.input.editor_model import binding_from_text
from linuxdroid.input.profile_bridge import (
    legacy_payload_to_profile,
    normalize_legacy_slots,
    profile_to_legacy_payload,
    validate_editor_payload,
)
from tests.input_helpers import add_node, make_profile, tap_profile


def legacy_payload() -> dict:
    return {
        "version": 1,
        "name": "Perfil antigo",
        "screen": {"width": 1920, "height": 1080},
        "global_sensitivity": 1.0,
        "nodes": [
            {
                "id": "tap",
                "type": "tap",
                "slot": 0,
                "pos": {"x": 0.2, "y": 0.8},
                "key": "W",
            }
        ],
    }


class BindingEditorTests(unittest.TestCase):
    def test_legacy_payload_becomes_v2_without_fake_capture(self):
        editor = BindingEditor(legacy_payload(), package_key="com.example.game")
        self.assertIsInstance(editor.profile, ControlProfileV2)
        binding = next(iter(editor.profile.bindings.values()))
        self.assertEqual(binding.canonical_name, "W")
        self.assertEqual(binding.provenance, "unverified")
        self.assertFalse(binding.is_physically_captured())

    def test_undo_redo_and_dirty_state(self):
        editor = BindingEditor(tap_profile())
        self.assertFalse(editor.dirty)
        editor.set_name("Novo nome")
        self.assertTrue(editor.dirty)
        self.assertEqual(editor.profile.name, "Novo nome")
        self.assertTrue(editor.undo())
        self.assertEqual(editor.profile.name, "perfil-teste")
        self.assertTrue(editor.redo())
        self.assertEqual(editor.profile.name, "Novo nome")
        editor.mark_saved()
        self.assertFalse(editor.dirty)

    def test_duplicate_preserves_geometry_and_binding_identity(self):
        editor = BindingEditor(tap_profile())
        original = editor.profile.nodes[0]
        new_id = editor.duplicate_node(original.id)
        duplicated = editor.profile.nodes[-1]
        self.assertEqual(new_id, duplicated.id)
        self.assertEqual(duplicated.geometry, original.geometry)
        self.assertNotEqual(duplicated.slot, original.slot)
        original_binding = editor.profile.bindings[original.binding_refs["key"]]
        duplicated_binding = editor.profile.bindings[duplicated.binding_refs["key"]]
        self.assertEqual(duplicated_binding.canonical_name, original_binding.canonical_name)
        self.assertEqual(duplicated_binding.provenance, original_binding.provenance)
        self.assertTrue(editor.conflict_messages())

    def test_copy_paste_offsets_position(self):
        editor = BindingEditor(tap_profile())
        editor.copy_node("tap")
        new_id = editor.paste_node(dx=0.05, dy=0.05)
        pasted = editor.profile.nodes[-1]
        self.assertEqual(new_id, pasted.id)
        self.assertAlmostEqual(pasted.geometry["pos"]["x"], 0.25)
        self.assertAlmostEqual(pasted.geometry["pos"]["y"], 0.85)

    def test_remove_and_restore_binding(self):
        editor = BindingEditor(tap_profile())
        manual = binding_from_text("S")
        editor.set_binding("tap", "key", manual)
        binding = editor.profile.bindings["tap_key"]
        self.assertEqual(binding.canonical_name, "S")
        self.assertEqual(binding.provenance, "validated_by_vocabulary")
        editor.remove_binding("tap", "key")
        self.assertNotIn("key", editor.profile.nodes[0].binding_refs)
        self.assertTrue(editor.undo())
        self.assertIn("key", editor.profile.nodes[0].binding_refs)

    def test_local_capture_target(self):
        editor = BindingEditor(tap_profile())
        editor.start_capture("tap", "key")
        self.assertEqual(editor.capture_target, ("tap", "key"))
        binding = InputBinding.from_canonical(
            "Q", capture_source="qt_local_editor", provenance="captured_from_device"
        )
        self.assertTrue(editor.finish_capture(binding))
        self.assertIsNone(editor.capture_target)
        self.assertEqual(editor.profile.bindings["tap_key"].canonical_name, "Q")

    def test_geometry_and_properties_are_single_history_steps(self):
        editor = BindingEditor(tap_profile())
        editor.update_node_geometry("tap", {"pos": (0.4, 0.6)})
        editor.update_node_properties("tap", parameters={"radius": 0.12}, layer="combat")
        node = editor.profile.nodes[0]
        self.assertAlmostEqual(node.geometry["pos"]["x"], 0.4)
        self.assertEqual(node.parameters["radius"], 0.12)
        self.assertEqual(node.layer, "combat")
        self.assertTrue(editor.undo())
        self.assertEqual(editor.profile.nodes[0].layer, "")
        self.assertTrue(editor.undo())
        self.assertAlmostEqual(editor.profile.nodes[0].geometry["pos"]["x"], 0.2)

    def test_sequence_position_and_free_slot_exclusion(self):
        profile = make_profile()
        add_node(profile, node_id="macro", node_type="macro", slot=0,
                 keys={"key": "M"},
                 sequence=[{"action": "down", "slot": 0, "pos": {"x": 0.1, "y": 0.1},
                            "delay_ms": 0}])
        editor = BindingEditor(profile)
        editor.update_node_geometry("macro", {}, sequence_positions={0: (0.9, 0.2)})
        step = editor.profile.nodes[0].sequence[0]
        self.assertEqual(step["pos"], {"x": 0.9, "y": 0.2})
        self.assertEqual(editor.next_free_slot(excluding={1}), 2)

    def test_payload_roundtrip(self):
        editor = BindingEditor(tap_profile())
        payload = editor.to_payload()
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["nodes"][0]["key"], "W")
        restored = legacy_payload_to_profile(payload)
        self.assertEqual(len(restored.nodes), 1)
        self.assertEqual(restored.nodes[0].geometry["pos"]["x"], 0.2)

    def test_conflict_detection(self):
        profile = make_profile()
        add_node(profile, node_id="a", node_type="tap", keys={"key": "W"},
                 geometry={"pos": {"x": 0.1, "y": 0.1}})
        add_node(profile, node_id="b", node_type="tap", keys={"key": "W"}, slot=1,
                 geometry={"pos": {"x": 0.2, "y": 0.2}})
        editor = BindingEditor(profile)
        messages = " ".join(editor.conflict_messages())
        self.assertIn("Conflito", messages)


class ProfileBridgeTests(unittest.TestCase):
    def test_reserved_and_duplicate_slots_are_corrected(self):
        payload = legacy_payload()
        payload["nodes"].append({
            "id": "second", "type": "tap", "slot": 255,
            "pos": {"x": 0.4, "y": 0.4}, "key": "S",
        })
        normalized, warnings = normalize_legacy_slots(payload)
        self.assertNotEqual(normalized["nodes"][1]["slot"], 255)
        self.assertTrue(warnings)
        self.assertEqual(payload["nodes"][1]["slot"], 255)  # nao muta entrada

    def test_editor_payload_validation(self):
        self.assertEqual(validate_editor_payload(legacy_payload()), [])
        invalid = legacy_payload()
        invalid["nodes"][0]["slot"] = 255
        self.assertTrue(validate_editor_payload(invalid))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data_dir = storage.DATA_DIR
        storage.DATA_DIR = Path(self.temp.name)

    def tearDown(self):
        storage.DATA_DIR = self.old_data_dir
        self.temp.cleanup()

    def test_atomic_write_creates_backup(self):
        path = Path(self.temp.name) / "profile.json"
        storage.atomic_write_json(path, {"v": 1})
        storage.atomic_write_json(path, {"v": 2})
        self.assertEqual(json.loads(path.read_text()), {"v": 2})
        self.assertTrue(path.with_name("profile.json.bak").is_file())
        self.assertEqual(json.loads(path.with_name("profile.json.bak").read_text()), {"v": 1})

    def test_write_failure_leaves_original_and_no_temporary(self):
        path = Path(self.temp.name) / "profile.json"
        storage.atomic_write_json(path, {"v": 1})

        def failing_write(target, text):
            raise OSError("disco cheio")

        with self.assertRaises(OSError):
            storage.atomic_write_json(path, {"v": 2}, write_text=failing_write)
        self.assertEqual(json.loads(path.read_text()), {"v": 1})
        self.assertEqual(list(Path(self.temp.name).glob(".*.tmp")), [])

    def test_overwrite_protection(self):
        path = Path(self.temp.name) / "profile.json"
        storage.atomic_write_json(path, {"v": 1})
        with self.assertRaises(storage.StorageError):
            storage.atomic_write_json(path, {"v": 2}, overwrite=False)

    def test_corrupt_json_is_quarantined(self):
        path = Path(self.temp.name) / "bad.json"
        path.write_text("{corrompido", encoding="utf-8")
        with self.assertRaises(storage.StorageError):
            storage.load_json_recovered(path, {})
        self.assertTrue(path.with_name("bad.json.corrupt").is_file())
        self.assertTrue(path.exists())

    def test_load_game_controls_tolerates_corrupt_legacy_file(self):
        (Path(self.temp.name) / "game_controls.json").write_text("{", encoding="utf-8")
        self.assertEqual(storage.load_game_controls("com.example.game"), {})

    def test_v2_profile_save_load_and_validation(self):
        profile = tap_profile()
        path = storage.save_control_profile("com.example.game", profile)
        self.assertTrue(path.is_file())
        loaded = storage.load_control_profile("com.example.game")
        self.assertEqual(loaded.name, profile.name)
        self.assertEqual(loaded.schema_version, 2)
        self.assertEqual(loaded.bindings["tap_key"].provenance, "validated_by_vocabulary")

    def test_invalid_profile_is_not_saved(self):
        profile = make_profile(screen_contract=ScreenContract(None, None, "unknown"))
        add_node(profile, node_id="bad", node_type="tap", keys={"key": "W"},
                 slot=255, geometry={"pos": {"x": 0.1, "y": 0.1}})
        with self.assertRaises(storage.StorageError):
            storage.save_control_profile("com.example.game", profile)
        self.assertFalse(storage.control_profile_path("com.example.game").exists())

    def test_explicit_legacy_migration_preserves_v1(self):
        storage.save_game_controls("com.example.game", legacy_payload())
        migrated = storage.migrate_game_controls_to_v2("com.example.game")
        self.assertIsNotNone(migrated)
        self.assertEqual(migrated.game_package, "com.example.game")
        self.assertTrue(storage.control_profile_path("com.example.game").is_file())
        self.assertEqual(
            storage.load_game_controls("com.example.game")["name"], "Perfil antigo"
        )


if __name__ == "__main__":
    unittest.main()
