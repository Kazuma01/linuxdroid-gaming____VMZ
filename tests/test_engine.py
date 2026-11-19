"""Motor de mapeamento: tipos logicos, camadas e seguranca de execucao."""
import unittest

from linuxdroid.controls.model import (
    ControlProfileV2,
    Layer,
    ProfileNode,
    ScreenContract,
)
from linuxdroid.input import (
    EventScript,
    InputRuntime,
    MappingEngine,
    ProfileRejected,
    RecordingTouchBackend,
)
from tests.input_helpers import add_node, make_profile, tap_profile


def run(profile, script, *, start=1.0):
    runtime = InputRuntime()
    runtime.start()
    runtime.load_profile(profile)
    runtime.activate()
    commands = runtime.run_script(script, start=start)
    return runtime, commands


class MappingEngineTests(unittest.TestCase):
    def test_tap_down_before_up(self):
        runtime, commands = run(tap_profile(), EventScript().tap("W"))
        self.assertEqual([c["kind"] for c in commands], ["touch_down", "touch_up"])
        self.assertEqual(runtime.backend.actions(), ("down", "up"))
        self.assertEqual(runtime.engine.contacts.active_contacts, ())

    def test_hold_tap_follows_physical_press(self):
        profile = make_profile()
        add_node(profile, node_id="hold", node_type="hold_tap", keys={"key": "W"},
                 geometry={"pos": {"x": 0.3, "y": 0.4}})
        runtime, _ = run(profile, EventScript().key_down("W").key_up("W"))
        self.assertEqual(runtime.backend.actions(), ("down", "up"))

    def test_toggle_tap_alternates(self):
        profile = make_profile()
        add_node(profile, node_id="toggle", node_type="toggle_tap", keys={"key": "T"},
                 geometry={"pos": {"x": 0.3, "y": 0.4}})
        # toggle_tap alterna na própria pressão: 1ª liga, 2ª desliga,
        # 3ª liga, 4ª desliga.
        runtime, _ = run(profile, EventScript().tap("T").tap("T").tap("T").tap("T"))
        self.assertEqual(runtime.backend.actions(), ("down", "up", "down", "up"))

    def test_joystick_keeps_single_contact_and_moves(self):
        profile = make_profile()
        add_node(profile, node_id="pad", node_type="joystick", keys={
            "up": "Up", "down": "Down", "left": "Left", "right": "Right",
        }, geometry={"pos": {"x": 0.5, "y": 0.5}}, parameters={"radius": 0.1})
        runtime, commands = run(profile, EventScript().key_down("Up").key_up("Up"))
        self.assertEqual(commands[0]["kind"], "touch_down")
        self.assertEqual(commands[1]["kind"], "touch_move")
        self.assertEqual(commands[-1]["kind"], "touch_up")
        self.assertEqual(runtime.backend.actions()[0], "down")
        self.assertEqual(runtime.backend.actions()[-1], "up")
        self.assertEqual(len([c for c in commands if c["kind"] == "touch_down"]), 1)

    def test_drag_down_move_up(self):
        profile = make_profile()
        add_node(profile, node_id="drag", node_type="drag", keys={"key": "D"},
                 geometry={"start": {"x": 0.2, "y": 0.2}, "end": {"x": 0.8, "y": 0.8}})
        runtime, commands = run(profile, EventScript().tap("D"))
        self.assertEqual([c["kind"] for c in commands], ["touch_down", "touch_up"])
        self.assertEqual(runtime.backend.actions(), ("down", "move", "up"))

    def test_wheel_up_and_down_use_distinct_slots(self):
        profile = make_profile()
        add_node(profile, node_id="wheel", node_type="wheel", keys={"key": "WheelUp"},
                 up_slot=1, down_slot=2,
                 geometry={"up_pos": {"x": 0.7, "y": 0.3}, "down_pos": {"x": 0.7, "y": 0.7}})
        runtime, commands = run(profile, EventScript().wheel("up").wheel("down"))
        self.assertEqual(runtime.backend.actions(), ("down", "up", "down", "up"))
        self.assertEqual([c.slot for c in runtime.backend.commands], [1, 1, 2, 2])
        self.assertEqual([c["kind"] for c in commands], ["wheel_tap", "wheel_tap"])

    def test_aim_while_held_and_motion(self):
        profile = make_profile()
        add_node(profile, node_id="aim", node_type="aim",
                 keys={"activation_key": "MouseRight"}, slot=1,
                 geometry={"anchor": {"x": 0.5, "y": 0.5}},
                 parameters={"activation_mode": "while_held", "reach": 0.1, "sensitivity": 1.0})
        script = (EventScript().mouse_down("MouseRight").motion(0.1, 0.1)
                  .mouse_up("MouseRight"))
        runtime, commands = run(profile, script)
        kinds = [c["kind"] for c in commands]
        self.assertIn("aim_activate", kinds)
        self.assertIn("touch_move", kinds)
        self.assertIn("aim_deactivate", kinds)
        self.assertFalse(runtime.engine.aim_active)
        self.assertEqual(runtime.state.value, "CAPTURE_ACTIVE")

    def test_layer_shift_changes_visible_action(self):
        profile = make_profile(layers=[Layer(id="sniper", name="sniper", exclusive=True)])
        add_node(profile, node_id="base", node_type="tap", keys={"key": "W"},
                 geometry={"pos": {"x": 0.1, "y": 0.1}})
        add_node(profile, node_id="shift", node_type="layer_shift", keys={"key": "LeftShift"},
                 slot=None,
                 parameters={"mode": "hold", "layer_name": "sniper", "suspend_base": True})
        add_node(profile, node_id="layer", node_type="tap", keys={"key": "Q"}, layer="sniper",
                 slot=1, geometry={"pos": {"x": 0.9, "y": 0.9}})
        script = (EventScript().key_down("W").key_up("W")
                  .key_down("LeftShift").key_down("W").key_up("W")
                  .key_down("Q").key_up("Q").key_up("LeftShift")
                  .key_down("W").key_up("W"))
        runtime, commands = run(profile, script)
        self.assertEqual(
            [c.get("node") for c in commands if c["kind"] == "touch_down"],
            ["base", "layer", "base"],
        )
        self.assertEqual(runtime.engine.active_layer, "")

    def test_repeat_requires_explicit_profile_authorization(self):
        profile = make_profile()
        add_node(profile, node_id="repeat", node_type="repeat_tap", keys={"key": "R"},
                 geometry={"pos": {"x": 0.5, "y": 0.5}},
                 parameters={"auto_repeat": True, "interval_ms": 50})
        runtime, _ = run(profile, EventScript().key_down("R").key_up("R"))
        self.assertEqual(runtime.backend.actions(), ("down", "up"))

        authorized = make_profile(metadata={"allow_auto_repeat": True})
        add_node(authorized, node_id="repeat", node_type="repeat_tap", keys={"key": "R"},
                 geometry={"pos": {"x": 0.5, "y": 0.5}},
                 parameters={"auto_repeat": True, "interval_ms": 50})
        runtime, _ = run(authorized, EventScript().key_down("R"))
        runtime.engine.tick(now=2.0)
        self.assertGreaterEqual(len(runtime.backend.actions()), 4)

    def test_macro_has_no_runtime(self):
        profile = make_profile()
        add_node(profile, node_id="macro", node_type="macro", keys={"key": "M"},
                 slot=None,
                 sequence=[{"action": "down", "slot": 3, "pos": {"x": 0.5, "y": 0.5},
                            "delay_ms": 0}])
        runtime, commands = run(profile, EventScript().tap("M"))
        self.assertEqual(commands, [])
        self.assertEqual(runtime.backend.commands, ())
        self.assertIn(
            "macro_runtime_disabled",
            [error["detail"] for error in runtime.snapshot()["errors"]],
        )

    def test_invalid_profile_is_rejected_before_loading(self):
        profile = ControlProfileV2(name="ruim", screen_contract=ScreenContract(1920, 1080, "measured"))
        add_node(profile, node_id="bad", node_type="tap", keys={"key": "W"},
                 slot=255, geometry={"pos": {"x": 0.1, "y": 0.1}})
        with self.assertRaises(ProfileRejected):
            MappingEngine(profile=profile, backend=RecordingTouchBackend())

    def test_key_repeat_alone_does_not_create_contacts(self):
        runtime, commands = run(tap_profile(), EventScript().key_repeat("W"))
        self.assertEqual(commands, [])
        self.assertEqual(runtime.backend.commands, ())

    def test_unbound_input_is_dropped_not_injected(self):
        runtime, commands = run(tap_profile(), EventScript().tap("Z"))
        self.assertEqual(commands, [])
        self.assertEqual(runtime.backend.commands, ())
        self.assertIn("unbound_input", [e["detail"] for e in runtime.snapshot()["errors"]])


if __name__ == "__main__":
    unittest.main()
