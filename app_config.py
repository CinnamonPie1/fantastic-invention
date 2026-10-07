# -*- coding: utf-8 -*-
"""
app_config.py
Carga y guarda la configuración persistente de la aplicación (config.json,
en la misma carpeta que el ejecutable/script). Todo lo que antes estaba
"hardcodeado" en el código (nombre de sesión, coordenadas de pantalla,
sinónimos, apariencia) vive acá para poder editarse desde la Ventana de
Configuración sin tocar código.
"""

import json
import os
import sys
from pathlib import Path

APP_NAME = "DescargoMedicacion"

def resource_path(name: str) -> str:
    """Path to a bundled read-only resource in source/PyInstaller mode."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / name)

def _app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".descargo_medicacion"

APP_DATA_DIR = _app_data_dir()
CONFIG_PATH = APP_DATA_DIR / "config.json"
LEGACY_CONFIG_PATH = Path(resource_path("config.json"))
DEFAULT_CONFIG_PATH = Path(resource_path("config.default.json"))

def resolve_data_path(value: str) -> str:
    """Resolve relative packaged files (such as farmacos.csv) robustly."""
    p = Path(value)
    if p.is_absolute():
        return str(p)
    cwd_candidate = Path.cwd() / p
    if cwd_candidate.exists():
        return str(cwd_candidate)
    return resource_path(value)

DEFAULT_CONFIG = {
    "session_name": "ACS 5250 activo",  # legado informativo
    "catalog_path": "farmacos.csv",
    "timeout_seconds": 15,

    # ACS 1.1.8.7 / HOD1108 en Windows/macOS. La app activa la ventana 5250 ya
    # abierta y dispara directamente cada macro (sin Play Macro/encadenamiento).
    "acs_window_title_contains": "5250",
    "acs_read_hotkey_key": "l",
    "acs_exec_hotkey_key": "e",
    "acs_confirm_hotkey_key": "c",
    "acs_macro_hotkey_modifiers": "control,shift",
    "macro_timeout_seconds": 600,

    "screen_coords": {
        "search_result_row": 11,
        "search_result_col": 2,
        "order_rows": [16, 18, 20],
        "col_cant_tens": 17,
        "col_cant": 18,
        "col_dosis": 21,
        "col_via": 30,
        "col_frecuencia": 45,
        "col_dura_cant": 57,
        "col_dura_unidad": 59,
        "pf4_popup_delay_seconds": 0.3,
        "pf4_confirm_delay_seconds": 0.2,
        "guard_row": 15,
        "guard_col": 2,
        "guard_len": 2,
        "via_selector_key": "[pf4]",

        # Navegación para buscar un paciente en la dependencia (tecla F3 en
        # el programa). Ver comentarios junto a las constantes en
        # hod_controller.py para el detalle de cada paso.
        "dependencia_first_row": 11,
        "dependencia_last_row": 24,
        "dependencia_name_col": 14,
        "dependencia_name_len": 40,
        "dependencia_opc_col": 2,
        "patient_page_notes_row": 13,
        "patient_page_opc_col": 2,
        "dependencia_avpag_key": "[pf8]",
        "dependencia_repag_key": "[pf7]",

        # Detección del aviso "Medicamento ingresado, está agotado" entre el
        # primer y segundo [enter] al seleccionar un medicamento.
        "agotado_msg_row": 14,
        "agotado_msg_col": 23,
        "agotado_msg_len": 60,
        "agotado_check_delay_seconds": 0.2,
    },

    "fuzzy_cutoff": 0.75,
    "name_synonyms": {
        "SOLUCION SALINA": "CLORURO DE SODIO",
        "SOL SALINA": "CLORURO DE SODIO",
        "SS0.9": "CLORURO DE SODIO",
        "SSN": "CLORURO DE SODIO",
    },
    "route_synonyms": {
        "IV": "PARENTERAL",
        "EV": "PARENTERAL",
        "INTRAVENOSO": "PARENTERAL",
        "INTRAVENOSA": "PARENTERAL",
        "VENOSA": "PARENTERAL",
        "VIA VENOSA": "PARENTERAL",
        "SC": "PARENTERAL",
        "SUBCUTANEA": "PARENTERAL",
        "IM": "PARENTERAL",
        "INTRAMUSCULAR": "PARENTERAL",
        "VIA ORAL": "ORAL",
        "PO": "ORAL",
        "ORAL": "ORAL",
    },

    "note_font_size": 10,
    "theme": "light",  # "light" | "dark"

    # Medicamentos "favoritos" para agregar con un solo clic desde la barra
    # de marcadores, cada uno como {"codigo", "descripcion", "presentacion"}.
    "bookmarks": [],

    # Registro personal de coincidencias EXACTAS: línea de prescripción
    # normalizada (ver catalog.normalize_prescription_key) -> el medicamento
    # {"codigo", "descripcion", "presentacion"} que se eligió la última vez
    # para esa misma línea. A diferencia de "name_synonyms" (que solo
    # traduce el nombre y sigue dependiendo del desempate por forma/vía/
    # concentración), esto recuerda la línea completa tal cual, así que la
    # próxima vez que llegue una prescripción idéntica se descarga directo
    # ese medicamento, sin volver a pasar por la búsqueda ambigua.
    "exact_matches": {},

    # Medicamentos marcados permanentemente como agotados en la institución
    # (descubierto en tiempo real al ejecutar un descargo), como
    # {"codigo": "descripcion"} para poder mostrar el nombre sin tener que
    # buscarlo de nuevo en el catálogo.
    "out_of_stock_codes": {},

    "window_geometry": "1300x720",
}


def _deep_merge_defaults(loaded: dict, defaults: dict) -> dict:
    """Completa claves faltantes en `loaded` con las de `defaults` (recursivo en dicts),
    para que agregar una config nueva en el futuro no rompa un config.json viejo."""
    result = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            result[key] = _deep_merge_defaults(value, defaults[key])
        else:
            result[key] = value
    return result


def _read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config() -> dict:
    # 1) Per-user writable config.
    # 2) Legacy config beside the old script/exe (migration).
    # 3) Bundled config.default.json seed.
    # 4) Hard-coded defaults as final fallback.
    for path in (CONFIG_PATH, LEGACY_CONFIG_PATH, DEFAULT_CONFIG_PATH):
        try:
            if path.exists():
                loaded = _read_json(path)
                merged = _deep_merge_defaults(loaded, DEFAULT_CONFIG)
                if path != CONFIG_PATH:
                    try:
                        save_config(merged)
                    except Exception:
                        pass
                return merged
        except Exception:
            continue
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config: dict):
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
