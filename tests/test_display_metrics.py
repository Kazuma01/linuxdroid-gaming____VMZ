"""Testes da leitura da superfície Android — sem PySide6 e sem Waydroid."""
import unittest

from linuxdroid.services.display_metrics import (
    DisplayMetrics,
    documented_reference,
    from_command_outputs,
    merge,
    parse_dumpsys_display,
    parse_wm_output,
    unknown,
)


class WmOutputTests(unittest.TestCase):
    def test_physical_size_and_density(self):
        metrics = parse_wm_output(
            "Physical size: 1920x1034\n", "Physical density: 180\n"
        )
        self.assertEqual((metrics.width, metrics.height), (1920, 1034))
        self.assertEqual(metrics.dpi, 180)
        self.assertTrue(metrics.measured)
        self.assertIn("1920×1034", metrics.label)

    def test_override_takes_precedence(self):
        metrics = parse_wm_output(
            "Physical size: 1280x720\nOverride size: 1920x1034\n", ""
        )
        self.assertEqual((metrics.width, metrics.height), (1920, 1034))

    def test_empty_output_never_invents_size(self):
        metrics = parse_wm_output("", "")
        self.assertFalse(metrics.known)
        self.assertFalse(metrics.measured)
        self.assertEqual(metrics.label, "resolução desconhecida")
        self.assertEqual(metrics.status_label, "NÃO MEDIDA")

    def test_implausible_size_is_rejected(self):
        metrics = parse_wm_output("Physical size: 1x1\n", "")
        self.assertFalse(metrics.known)


class DumpsysTests(unittest.TestCase):
    SAMPLE = """
Display Power: state=ON
DisplayDeviceInfo{"Built-in Screen": uniqueId="local:0", 1920 x 1034, 60.0 fps,
  density 180, deviceKeyMapping, supportedModes={{1920x1034, 60.0, 180.0}}}
mBaseDisplayInfo=DisplayInfo{"Built-in Screen", displayId 0, FLAG_SUPPORTS_PROTECTED_BUFFERS,
  1920 x 1034, dpi 180, refreshRate 60.0}
"""

    def test_parses_real_device_info(self):
        metrics = parse_dumpsys_display(self.SAMPLE)
        self.assertEqual((metrics.width, metrics.height), (1920, 1034))
        self.assertEqual(metrics.dpi, 180)
        self.assertEqual(metrics.refresh_hz, 60.0)
        self.assertTrue(metrics.measured)
        self.assertIn("60 Hz", metrics.label)

    def test_device_info_is_preferred_over_other_lines(self):
        sample = (
            'DisplayInfo{"Fake", 800 x 600, 320 dpi}\n'
            'DisplayDeviceInfo{"Built-in", 1920 x 1034, 60.0 fps, density 180}\n'
        )
        metrics = parse_dumpsys_display(sample)
        self.assertEqual((metrics.width, metrics.height), (1920, 1034))

    def test_garbage_does_not_produce_measurements(self):
        metrics = parse_dumpsys_display("no display here\n")
        self.assertFalse(metrics.known)
        self.assertFalse(metrics.measured)
        self.assertIn("dumpsys", metrics.source)

    def test_refresh_rate_without_fps_suffix(self):
        sample = 'DisplayDeviceInfo{"Screen", 2560 x 1440, refreshRate 144.0, density 160}'
        metrics = parse_dumpsys_display(sample)
        self.assertEqual(metrics.refresh_hz, 144.0)
        self.assertEqual(metrics.dpi, 160)


class ReferenceAndMergeTests(unittest.TestCase):
    def test_documented_reference_is_explicitly_not_measured(self):
        metrics = documented_reference()
        self.assertTrue(metrics.known)
        self.assertFalse(metrics.measured)
        self.assertEqual(metrics.status_label, "REFERÊNCIA / MANUAL")
        self.assertIn("histórico", metrics.note.lower())

    def test_merge_keeps_measured_flag_from_primary(self):
        primary = DisplayMetrics(width=1920, height=1034, source="dumpsys", measured=True)
        secondary = documented_reference()
        result = merge(primary, secondary)
        self.assertEqual(result.dpi, 180)
        self.assertEqual(result.refresh_hz, 60.0)
        self.assertTrue(result.measured)

    def test_merge_fills_missing_primary_from_secondary(self):
        primary = unknown("container congelado")
        secondary = documented_reference()
        result = merge(primary, secondary)
        self.assertEqual((result.width, result.height), (1920, 1034))
        self.assertFalse(result.measured)

    def test_plausible_range(self):
        self.assertTrue(documented_reference().plausible())
        self.assertFalse(DisplayMetrics(width=10, height=10).plausible())


class FromCommandOutputsTests(unittest.TestCase):
    def test_composes_wm_and_dumpsys(self):
        metrics = from_command_outputs(
            "Physical size: 1920x1034\n",
            "Physical density: 180\n",
            'DisplayDeviceInfo{"Built-in", 1920 x 1034, 60.0 fps, density 180}\n',
        )
        self.assertTrue(metrics.measured)
        self.assertEqual((metrics.width, metrics.height), (1920, 1034))
        self.assertEqual(metrics.dpi, 180)
        self.assertEqual(metrics.refresh_hz, 60.0)

    def test_dumpsys_fills_missing_refresh_rate(self):
        metrics = from_command_outputs(
            "Physical size: 1920x1034\n",
            "Physical density: 180\n",
            'DisplayDeviceInfo{"Built-in", 1920 x 1034, 60.0 fps}\n',
        )
        self.assertEqual(metrics.refresh_hz, 60.0)

    def test_no_output_returns_unknown_without_inventing(self):
        metrics = from_command_outputs("", "", "")
        self.assertFalse(metrics.known)
        self.assertFalse(metrics.measured)
        self.assertEqual(metrics.status_label, "NÃO MEDIDA")


if __name__ == "__main__":
    unittest.main()
