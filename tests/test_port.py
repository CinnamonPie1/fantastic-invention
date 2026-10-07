import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import catalog
import hod_controller
from hod_controller import HODController, OrderFields
from note_parser import parse_note


class _Valid:
    valid = True
    message = "ok"


def make_controller(**kwargs):
    with patch("license_manager.verify_installed_license", return_value=_Valid()):
        return HODController(**kwargs)


class PortTests(unittest.TestCase):
    def test_all_macros_are_well_formed_xml(self):
        macros = sorted((ROOT / "acs_macros").glob("*.mac"))
        self.assertEqual(len(macros), 3)
        names = set()
        for path in macros:
            root = ET.parse(path).getroot()
            self.assertEqual(root.tag, "HAScript")
            names.add(root.attrib["name"])
        self.assertEqual(names, {
            "DescargoLeer_HOD1108",
            "DescargoEjecutar_HOD1108",
            "DescargoConfirmar_HOD1108",
        })

    def test_no_macro_chaining_is_used(self):
        for path in (ROOT / "acs_macros").glob("*.mac"):
            root = ET.parse(path).getroot()
            self.assertEqual(list(root.iter("playmacro")), [], path.name)

    def test_execute_macro_uses_hod_pagedn_not_pcomm_roll_up(self):
        text = (ROOT / "acs_macros" / "DescargoEjecutar_HOD1108.mac").read_text(encoding="utf-8").lower()
        self.assertIn("[pagedn]", text)
        self.assertNotIn("[roll up]", text)

    def test_execute_macro_avoids_known_hod1108_invalid_expressions(self):
        text = (ROOT / "acs_macros" / "DescargoEjecutar_HOD1108.mac").read_text(encoding="utf-8")
        self.assertNotIn("new JString(", text)
        self.assertNotIn(".substring(", text)
        self.assertNotIn(".trim()", text)
        self.assertIn("new Tokenizer($cfgLine$, &apos;=|&apos;)", text)
        self.assertIn("$qtyNum$ &gt;= 10", text)
        self.assertIn('name="AgotadoDetectado"', text)

    def test_exec_payload_contains_expected_configuration(self):
        ctl = make_controller(screen_coords={"order_rows": [16, 18, 20], "via_selector_key": "[pf4]"})
        fields = [
            OrderFields("4102027", "2", "500", "MG", "qd", "1", "d"),
            OrderFields("3202006", "12", "40", "MG", "qd", "1", "d"),
        ]
        payload = ctl._build_exec_payload(fields, remove_patient=True)
        lines = payload.splitlines()
        self.assertEqual(lines[0], hod_controller.EXEC_COMMAND)
        self.assertTrue(lines[1].startswith("CFG=1|2|11|2|16|18|20|"))
        self.assertTrue(lines[1].endswith("|[pf4]"))
        self.assertEqual(lines[2:], ["4102027|2", "3202006|12"])

    def test_exec_response_returns_exhausted_codes(self):
        ctl = make_controller()
        ctl._invoke_macro = lambda *a, **k: "###DESCARGO_HOD1108_EXEC_OK###\nAGOTADOS=4102027;3202006;"
        got = ctl.execute_descargo([OrderFields("4102027", "1", "", "", "qd", "1", "d")])
        self.assertEqual(got, {"4102027", "3202006"})

    def test_read_response_parses_patient_and_note(self):
        ctl = make_controller()
        ctl._invoke_macro = lambda *a, **k: "###DESCARGO_HOD1108_READ_OK###\nPACIENTE PRUEBA\nLINEA 1\nLINEA 2"
        note = ctl.capture_note_text()
        self.assertEqual(ctl.get_patient_name(), "PACIENTE PRUEBA")
        self.assertEqual(note, "LINEA 1\nLINEA 2")

    def test_catalog_loads(self):
        rows = catalog.load_catalog(str(ROOT / "farmacos.csv"))
        self.assertGreater(len(rows), 100)
        self.assertTrue(rows[0].codigo)

    def test_parser_still_extracts_medication(self):
        meds = parse_note("1. PARACETAMOL SOLIDO ORAL 500 MG CADA 8 HORAS")
        self.assertGreaterEqual(len(meds), 1)
        self.assertIn("PARACETAMOL", meds[0].name)

    def test_config_has_acs_macro_settings_and_no_bridge(self):
        cfg = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["acs_read_hotkey_key"], "l")
        self.assertEqual(cfg["acs_exec_hotkey_key"], "e")
        self.assertEqual(cfg["acs_confirm_hotkey_key"], "c")
        self.assertEqual(cfg["acs_macro_hotkey_modifiers"], "control,shift")
        self.assertNotIn("hod_bridge_host", cfg)


if __name__ == "__main__":
    unittest.main()
