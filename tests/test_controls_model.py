"""Testes do modelo versionado de controles.

Rodar na raiz do projeto:
    PYTHONDONTWRITEBYTECODE=1 python -B -m unittest tests.test_controls_model -v

Nao usa PySide6, Waydroid, Phantom, evdev, dispositivos fisicos nem resolucao
fixa. Todos os eventos e capacidades sao simulados.
"""
from __future__ import annotations

import json
import unittest

from linuxdroid.controls import cursor as cursor_mod
from linuxdroid.controls import phantom as phantom_mod
from linuxdroid.controls.keys import (
    InputBinding,
    canonical_for_code,
    is_phantom_name,
    normalize_phantom_name,
)
from linuxdroid.controls.cursor import CursorVirtual
from linuxdroid.controls.model import (
    BackendPreferences,
    ControlProfileV2,
    CursorModelConfig,
    Layer,
    ProfileError,
    ProfileNode,
    ScreenContract,
    has_errors,
    migrate_legacy_profile,
    validate_profile,
)


def pos(x: float, y: float) -> dict:
    return {"x": x, "y": y}


def verified(name: str, *, code=None, code_space="unknown") -> InputBinding:
    return InputBinding.from_canonical(
        name, capture_source="unit-test", code=code, code_space=code_space
    )


def errors(profile: ControlProfileV2) -> list[str]:
    return [
        issue.message for issue in validate_profile(profile) if issue.severity == "error"
    ]


def make_profile(*, screen: ScreenContract | None = None) -> ControlProfileV2:
    profile = ControlProfileV2(
        name="Perfil de teste",
        game_package="com.example.game",
        screen_contract=screen or ScreenContract(1920, 1080, "measured"),
    )
    profile.bindings["key_w"] = verified("W", code=17, code_space="evdev")
    profile.nodes.append(ProfileNode(
        id="move",
        type="tap",
        slot=0,
        geometry={"pos": pos(0.2, 0.8)},
        binding_refs={"key": "key_w"},
    ))
    return profile


def add_tap(profile: ControlProfileV2, node_id: str, binding_id: str, *, slot: int, layer: str = "") -> None:
    profile.nodes.append(ProfileNode(
        id=node_id,
        type="tap",
        layer=layer,
        slot=slot,
        geometry={"pos": pos(0.5, 0.5)},
        binding_refs={"key": binding_id},
    ))


class SerializationTests(unittest.TestCase):
    def test_serializacao_contem_todos_os_campos_exigidos(self):
        profile = make_profile()
        raw = profile.to_dict()
        for field in (
            "schema_version", "game_package", "screen_contract", "backend_preferences",
            "cursor_model", "layers", "nodes", "metadata", "bindings",
        ):
            self.assertIn(field, raw)

        binding = raw["bindings"]["key_w"]
        for field in (
            "namespace", "event_type", "code", "code_space", "canonical_name",
            "modifiers", "capture_source", "label", "validation",
        ):
            self.assertIn(field, binding)

    def test_json_e_reversivel(self):
        original = make_profile()
        raw = original.to_json()
        restored = ControlProfileV2.from_json(raw)
        self.assertEqual(restored.to_dict(), original.to_dict())

    def test_desserializacao_rejeita_formato_antigo(self):
        with self.assertRaises(ProfileError):
            ControlProfileV2.from_dict({"name": "antigo", "version": 1, "nodes": []})


class MigrationTests(unittest.TestCase):
    def test_migracao_de_perfil_antigo(self):
        legacy = {
            "name": "Jogo Antigo",
            "version": 1,
            "screen": {"width": 1600, "height": 900},
            "global_sensitivity": 1.25,
            "nodes": [{
                "id": "fire",
                "type": "tap",
                "slot": 3,
                "pos": {"x": 0.85, "y": 0.7},
                "key": "CTRL",
                "layer": "combat",
            }],
        }
        profile = migrate_legacy_profile(legacy, game_package="com.example.old")
        self.assertEqual(profile.schema_version, 2)
        self.assertEqual(profile.game_package, "com.example.old")
        self.assertEqual(profile.screen_contract.width, 1600)
        self.assertEqual(profile.screen_contract.source, "imported")
        self.assertEqual(profile.cursor_model.sensitivity, 1.25)

        binding = profile.bindings["fire_key"]
        self.assertEqual(binding.canonical_name, "LeftCtrl")
        self.assertEqual(binding.label, "CTRL")
        self.assertEqual(binding.validation, "unverified")
        self.assertIsNone(binding.code)
        self.assertEqual(binding.code_space, "unknown")
        self.assertEqual(binding.capture_source, "legacy_text")

    def test_binding_desconhecido_e_preservado_sem_codigo_inventado(self):
        legacy = {
            "name": "Antigo",
            "version": 1,
            "nodes": [{"id": "x", "type": "tap", "key": "Key0"}],
        }
        profile = migrate_legacy_profile(legacy)
        binding = next(iter(profile.bindings.values()))
        self.assertEqual(binding.label, "Key0")
        self.assertEqual(binding.canonical_name, "")
        self.assertEqual(binding.validation, "invalid")
        self.assertIsNone(binding.code)
        self.assertTrue(any("Binding marcado como invalido" in message for message in errors(profile)))

    def test_screen_desconhecido_permanece_desconhecido(self):
        profile = migrate_legacy_profile({"name": "sem tela", "version": 1, "nodes": []})
        self.assertIsNone(profile.screen_contract.width)
        self.assertIsNone(profile.screen_contract.height)
        self.assertEqual(profile.screen_contract.source, "unknown")
        self.assertFalse(profile.screen_contract.known)


class IdentifierTests(unittest.TestCase):
    def test_aliases_sao_normalizados_e_codigo_tem_espaco_explicito(self):
        self.assertEqual(normalize_phantom_name("CTRL"), "LeftCtrl")
        self.assertEqual(normalize_phantom_name("["), "LeftBrace")
        self.assertEqual(normalize_phantom_name("0"), "0")
        self.assertIsNone(normalize_phantom_name("Key0"))
        self.assertTrue(is_phantom_name("W"))

        self.assertEqual(canonical_for_code(17, "evdev"), "W")
        self.assertIsNone(canonical_for_code(30, "qt_native_scan_code"))
        self.assertEqual(canonical_for_code(0x110, "evdev"), "MouseLeft")
        self.assertIsNone(canonical_for_code(0, "qt_virtual_key"))

    def test_validacao_de_codigo_evdev(self):
        profile = make_profile()
        self.assertEqual(errors(profile), [])

        profile.bindings["key_w"].code = 18
        self.assertTrue(any("corresponde a E" in message for message in errors(profile)))

        profile.bindings["key_w"].code = 17
        profile.bindings["key_w"].code_space = "unknown"
        self.assertTrue(any("espaco conhecido" in message for message in errors(profile)))

    def test_roda_e_botao_de_mouse_tem_namespaces_diferentes(self):
        wheel = verified("WheelUp")
        mouse = verified("MouseLeft", code=0x110, code_space="evdev")
        self.assertEqual(wheel.namespace, "wheel")
        self.assertEqual(mouse.namespace, "mouse")
        self.assertIsNone(wheel.code)
        self.assertEqual(mouse.code, 0x110)


class ModifierTests(unittest.TestCase):
    def test_modificador_valido(self):
        profile = make_profile()
        profile.bindings["key_w"].modifiers = ("LeftShift",)
        self.assertEqual(errors(profile), [])

    def test_modificador_desconhecido(self):
        profile = make_profile()
        profile.bindings["key_w"].modifiers = ("F1",)
        self.assertTrue(any("Modificador desconhecido" in message for message in errors(profile)))

    def test_identidade_inclui_modificadores(self):
        plain = verified("W")
        shifted = verified("W")
        shifted.modifiers = ("LeftShift",)
        self.assertNotEqual(plain.identity(), shifted.identity())


class ConflictTests(unittest.TestCase):
    def test_conflito_dentro_da_mesma_camada(self):
        profile = make_profile()
        add_tap(profile, "fire", "key_w", slot=1)
        self.assertTrue(any("Conflito na mesma camada (base)" in message for message in errors(profile)))

    def test_repeticao_em_camadas_exclusivas_e_permitida(self):
        profile = make_profile()
        profile.layers.append(Layer(id="combat", name="combat", exclusive=True))
        add_tap(profile, "fire", "key_w", slot=1, layer="combat")
        profile.nodes.append(ProfileNode(
            id="shift",
            type="layer_shift",
            binding_refs={"key": "key_shift"},
            parameters={"layer_name": "combat", "suspend_base": True},
        ))
        profile.bindings["key_shift"] = verified("Q", code=16, code_space="evdev")
        self.assertEqual(errors(profile), [])

    def test_repeticao_base_e_camada_sem_protecao_e_bloqueada(self):
        profile = make_profile()
        profile.layers.append(Layer(id="combat", name="combat", exclusive=False))
        add_tap(profile, "fire", "key_w", slot=1, layer="combat")
        profile.nodes.append(ProfileNode(
            id="shift",
            type="layer_shift",
            binding_refs={"key": "key_shift"},
            parameters={"layer_name": "combat", "suspend_base": False},
        ))
        profile.bindings["key_shift"] = verified("Q", code=16, code_space="evdev")
        self.assertTrue(any("sem suspend_base" in message for message in errors(profile)))

    def test_chave_de_camada_nao_pode_ser_acao(self):
        profile = make_profile()
        profile.nodes.append(ProfileNode(
            id="shift",
            type="layer_shift",
            binding_refs={"key": "key_w"},
            parameters={"layer_name": "combat", "suspend_base": True},
        ))
        self.assertTrue(any("troca de camada e acao" in message for message in errors(profile)))


class InvalidProfileTests(unittest.TestCase):
    def test_ids_duplicados(self):
        profile = make_profile()
        add_tap(profile, "move", "key_w", slot=1)
        self.assertTrue(any("Identificador duplicado" in message for message in errors(profile)))

    def test_tipo_desconhecido(self):
        profile = make_profile()
        profile.nodes[0].type = "teleporte"
        self.assertTrue(any("Tipo desconhecido" in message for message in errors(profile)))

    def test_slot_reservado_pelo_phantom(self):
        profile = make_profile()
        profile.nodes[0].slot = 255
        self.assertTrue(any("reservado" in message for message in errors(profile)))

    def test_json_invalido(self):
        with self.assertRaises(ProfileError):
            ControlProfileV2.from_json("{")

    def test_schema_version_incompativel(self):
        raw = make_profile().to_dict()
        raw["schema_version"] = 99
        with self.assertRaises(ProfileError):
            ControlProfileV2.from_dict(raw)

    def test_backend_desconhecido(self):
        profile = make_profile()
        profile.backend_preferences = BackendPreferences(preferred="misterio")
        self.assertTrue(any("Preferencia de backend" in message for message in errors(profile)))


class PhantomCompatibilityTests(unittest.TestCase):
    def test_exportacao_valida(self):
        profile = make_profile()
        result = phantom_mod.export_phantom_profile(profile)
        self.assertEqual(result.profile["version"], 1)
        self.assertEqual(result.profile["screen"], {"width": 1920, "height": 1080})
        self.assertEqual(result.profile["nodes"][0]["key"], "W")
        self.assertEqual(json.loads(result.to_json()), result.profile)

    def test_resolucao_desconhecida_bloqueia_exportacao(self):
        profile = make_profile(screen=ScreenContract())
        self.assertFalse(has_errors(validate_profile(profile)))
        self.assertTrue(any("Resolucao desconhecida" in str(issue.message) for issue in validate_profile(profile)))
        with self.assertRaises(ProfileError):
            phantom_mod.export_phantom_profile(profile)

    def test_binding_nao_verificado_nao_e_exportado_silentemente(self):
        legacy = {
            "name": "Antigo",
            "version": 1,
            "screen": {"width": 1280, "height": 720},
            "nodes": [{
                "id": "fire",
                "type": "tap",
                "slot": 1,
                "pos": {"x": 0.9, "y": 0.6},
                "key": "W",
            }],
        }
        profile = migrate_legacy_profile(legacy)
        with self.assertRaises(ProfileError):
            phantom_mod.export_phantom_profile(profile)

        result = phantom_mod.export_phantom_profile(profile, allow_unverified=True)
        self.assertEqual(result.profile["nodes"][0]["key"], "W")
        self.assertTrue(any("nao verificado" in warning for warning in result.warnings))

    def test_nome_inaceitavel_bloqueia_exportacao(self):
        profile = make_profile()
        profile.bindings["key_w"].canonical_name = "Key0"
        with self.assertRaises(ProfileError):
            phantom_mod.export_phantom_profile(profile)

    def test_slot_reservado_bloqueia_exportacao(self):
        profile = make_profile()
        profile.nodes[0].slot = 255
        with self.assertRaises(ProfileError):
            phantom_mod.export_phantom_profile(profile)

    def test_entrada_nao_suportada_bloqueia_exportacao(self):
        profile = make_profile()
        profile.bindings["key_w"].validation = "unsupported"
        with self.assertRaises(ProfileError):
            phantom_mod.export_phantom_profile(profile, allow_unverified=True)


class CursorTests(unittest.TestCase):
    def test_cursor_normalizado_e_clampado(self):
        cursor = CursorVirtual(CursorModelConfig(initial_x=0.5, initial_y=0.5))
        self.assertEqual(cursor.position, (0.5, 0.5))
        cursor.set_position_normalized(1.4, -0.2)
        self.assertEqual(cursor.position, (1.0, 0.0))
        self.assertTrue(cursor.in_bounds)

    def test_movimento_relativo_em_pixels_exige_tela_conhecida(self):
        cursor = CursorVirtual(screen=ScreenContract(1920, 1080, "measured"))
        cursor.set_position_normalized(0.5, 0.5)
        self.assertEqual(cursor.apply_relative(192, -54), (0.6, 0.45))

        unknown = CursorVirtual(screen=ScreenContract())
        with self.assertRaises(cursor_mod.CursorError):
            unknown.apply_relative(10, 10)

    def test_movimento_normalizado_nao_assume_resolucao(self):
        cursor = CursorVirtual()
        self.assertEqual(cursor.apply_relative(0.25, 0.1, unit="normalized"), (0.75, 0.6))

    def test_aceleracao_opcional(self):
        base = CursorVirtual(screen=ScreenContract(1000, 1000, "measured"))
        accelerated = CursorVirtual(
            CursorModelConfig(acceleration=True),
            ScreenContract(1000, 1000, "measured"),
        )
        base.set_position_normalized(0.5, 0.5)
        accelerated.set_position_normalized(0.5, 0.5)
        self.assertGreater(accelerated.apply_relative(100, 0)[0], base.apply_relative(100, 0)[0])

    def test_eventos_simulados_e_estados(self):
        cursor = CursorVirtual(screen=ScreenContract(1000, 1000, "measured"))
        cursor.simulate_events([
            {"type": "relative", "dx": 100, "dy": 0, "unit": "pixels"},
            {"type": "capture", "state": "captured"},
            {"type": "aim", "active": True},
            {"type": "menu_touch", "active": True},
        ])
        self.assertEqual(cursor.position, (0.6, 0.5))
        self.assertTrue(cursor.captured)
        self.assertTrue(cursor.aim_active)
        self.assertTrue(cursor.menu_touch_active)
        self.assertEqual(cursor.to_dict()["config"]["capture_state"], "captured")

        cursor.reset()
        self.assertFalse(cursor.captured)
        self.assertEqual(cursor.position, (0.5, 0.5))

    def test_evento_desconhecido_e_rejeitado(self):
        cursor = CursorVirtual()
        with self.assertRaises(cursor_mod.CursorError):
            cursor.simulate_events([{"type": "teleporte"}])


if __name__ == "__main__":
    unittest.main()
