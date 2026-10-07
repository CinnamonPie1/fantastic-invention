# -*- coding: utf-8 -*-
"""Offline machine-bound license verification for Descargo de Medicación.

The distributed app contains ONLY the RSA public key. Licenses are JSON files
signed by the separate owner tool. Copying the EXE and license.dat to another
computer will fail because the signed license contains a different
machine/installation ID.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

APP_ID = "descargo-medicacion"
LICENSE_FORMAT_VERSION = 1
PUBLIC_E = 65537
PUBLIC_N = int("b0a3dc865163c9e71cf7f02978e6061582b556644f2a3cbd2ea43cfd6b907ea30ec4e2a69ade7553ca283611a86b96e3035fe954e2dcae1be09ea8b52d067a081fda674b5ad36e024ca51b04fac4ac8ac1b7a575da04193226c62d3385d49f5b5659c6a32f2a663131733d7f45aa823465a77372af520b711fb75818862e44d8e410642611641d696cc6743b78dcf05c6a3188f610af33678ce5a5a5d400996ff1d1c6f3fd07f1a508870e5297ff97f29c0cc69b167f945393a30b3a37bf50e6a73013cd7be403f9cb54e0114252fb41dc57eadf25a1d5626d8627ee01b28c224f816103cbc661a4895e112470f53b58b343a3e94e2373445d601b95ab66bce7", 16)
_SHA256_DIGESTINFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "DescargoMedicacion"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DescargoMedicacion"
    return Path.home() / ".descargo_medicacion"


APP_DATA_DIR = _app_data_dir()
LICENSE_PATH = APP_DATA_DIR / "license.dat"


def _read_windows_machine_guid() -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import winreg
        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            access,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        value = str(value).strip()
        return value or None
    except Exception:
        return None


def _read_macos_platform_uuid() -> Optional[str]:
    """Lee IOPlatformUUID, estable para la instalación/equipo macOS."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def _read_linux_machine_id() -> Optional[str]:
    if not sys.platform.startswith("linux"):
        return None
    for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
            if value:
                return value
        except Exception:
            pass
    return None


def get_machine_id() -> str:
    """Identificador estable derivado de la instalación del sistema operativo.

    Windows: MachineGuid. macOS: IOPlatformUUID. Linux: /etc/machine-id.
    Como último recurso usa hostname + MAC, para mantener un fallback portable.
    El identificador bruto nunca se guarda en license.dat.
    """
    machine_guid = _read_windows_machine_guid()
    if machine_guid:
        material = f"{APP_ID}|v1|machineguid|{machine_guid}".encode("utf-8")
    else:
        mac_uuid = _read_macos_platform_uuid()
        if mac_uuid:
            material = f"{APP_ID}|v1|macos-platformuuid|{mac_uuid}".encode("utf-8")
        else:
            linux_id = _read_linux_machine_id()
            if linux_id:
                material = f"{APP_ID}|v1|linux-machineid|{linux_id}".encode("utf-8")
            else:
                fallback = f"{platform.node()}|{uuid.getnode():012x}"
                material = f"{APP_ID}|v1|fallback|{fallback}".encode("utf-8")
    return hashlib.sha256(material).hexdigest().upper()[:32]


def get_installation_id() -> str:
    raw = get_machine_id()
    return "DM1-" + "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def machine_id_from_installation_id(value: str) -> Optional[str]:
    text = re.sub(r"[^0-9A-Fa-f]", "", (value or "").strip())
    # Strip the hexadecimal-looking part of the DM1 prefix only by parsing the
    # canonical form first. The compact form is also accepted below.
    canonical = (value or "").strip().upper()
    if canonical.startswith("DM1-"):
        text = re.sub(r"[^0-9A-F]", "", canonical[4:])
    if len(text) == 32 and re.fullmatch(r"[0-9A-Fa-f]{32}", text):
        return text.upper()
    return None


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _rsa_verify_sha256(message: bytes, signature: bytes) -> bool:
    k = (PUBLIC_N.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    sig_int = int.from_bytes(signature, "big")
    if sig_int >= PUBLIC_N:
        return False
    em = pow(sig_int, PUBLIC_E, PUBLIC_N).to_bytes(k, "big")
    digest_info = _SHA256_DIGESTINFO_PREFIX + hashlib.sha256(message).digest()
    pad_len = k - len(digest_info) - 3
    if pad_len < 8:
        return False
    expected = b"\x00\x01" + (b"\xff" * pad_len) + b"\x00" + digest_info
    return hmac.compare_digest(em, expected)


@dataclass
class LicenseStatus:
    valid: bool
    message: str
    payload: Optional[dict] = None

    @property
    def customer(self) -> str:
        return str((self.payload or {}).get("customer") or "")


def verify_license_file(path: os.PathLike | str, expected_machine_id: Optional[str] = None) -> LicenseStatus:
    path = Path(path)
    if not path.exists():
        return LicenseStatus(False, "No se encontró una licencia activada en este equipo.")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return LicenseStatus(False, "El archivo de licencia no es un JSON válido.")

    payload = doc.get("payload")
    signature_b64 = doc.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature_b64, str):
        return LicenseStatus(False, "El archivo de licencia está incompleto.")

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception:
        return LicenseStatus(False, "La firma de la licencia no tiene un formato válido.")

    if not _rsa_verify_sha256(_canonical_payload(payload), signature):
        return LicenseStatus(False, "La firma de la licencia no es válida; el archivo pudo ser modificado.")

    if payload.get("version") != LICENSE_FORMAT_VERSION or payload.get("app_id") != APP_ID:
        return LicenseStatus(False, "Esta licencia pertenece a otra aplicación o versión de licencia.")

    expected_machine_id = expected_machine_id or get_machine_id()
    licensed_machine = str(payload.get("machine_id") or "").upper()
    if not hmac.compare_digest(licensed_machine, expected_machine_id.upper()):
        return LicenseStatus(False, "Esta licencia fue emitida para otro equipo.", payload)

    expires = payload.get("expires_at")
    if expires:
        try:
            expiry_date = date.fromisoformat(str(expires))
        except ValueError:
            return LicenseStatus(False, "La fecha de expiración de la licencia no es válida.", payload)
        if date.today() > expiry_date:
            return LicenseStatus(False, f"La licencia expiró el {expiry_date.isoformat()}.", payload)

    customer = str(payload.get("customer") or "Licencia válida")
    return LicenseStatus(True, f"Licencia válida para {customer}.", payload)


def verify_installed_license() -> LicenseStatus:
    return verify_license_file(LICENSE_PATH, get_machine_id())


def install_license_file(source_path: os.PathLike | str) -> LicenseStatus:
    status = verify_license_file(source_path, get_machine_id())
    if not status.valid:
        return status
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source_path, LICENSE_PATH)
    except Exception as exc:
        return LicenseStatus(False, f"No se pudo guardar la licencia: {exc}")
    return verify_installed_license()


def show_activation_dialog(parent, initial_message: str = "") -> bool:
    """Modal activation window. Returns True only after a valid license is installed."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    result = {"activated": False}
    win = tk.Toplevel(parent)
    win.title("Activación - Descargo de Medicación")
    win.geometry("610x365")
    win.resizable(False, False)

    # IMPORTANT: at first launch the main Tk root is intentionally withdrawn.
    # On Windows, making this dialog transient to a withdrawn root can cause the
    # activation window to remain hidden while python keeps running, which looks
    # like a blank CMD window. Only use transient() when the parent is visible.
    try:
        if parent.winfo_viewable():
            win.transient(parent)
    except Exception:
        pass

    win.update_idletasks()
    try:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww = win.winfo_width() or 610
        wh = win.winfo_height() or 365
        win.geometry(f"{ww}x{wh}+{max(0, (sw-ww)//2)}+{max(0, (sh-wh)//2)}")
    except Exception:
        pass

    # Bring the activation dialog to the foreground on first launch, then
    # release topmost so it behaves like a normal application window.
    win.deiconify()
    win.lift()
    try:
        win.attributes("-topmost", True)
        win.after(500, lambda: win.attributes("-topmost", False))
    except Exception:
        pass
    try:
        win.focus_force()
    except Exception:
        pass
    win.grab_set()

    outer = ttk.Frame(win, padding=18)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Activación requerida", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(
        outer,
        text=(
            "Esta instalación necesita una licencia firmada para este equipo. "
            "Envíe el ID de instalación al administrador y luego importe el archivo license.dat recibido."
        ),
        wraplength=560,
        justify="left",
    ).pack(anchor="w", pady=(8, 14))

    ttk.Label(outer, text="ID de instalación:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    installation_id = get_installation_id()
    id_var = tk.StringVar(value=installation_id)
    id_entry = ttk.Entry(outer, textvariable=id_var, state="readonly", width=58, font=("Consolas", 11))
    id_entry.pack(anchor="w", fill="x", pady=(4, 8))

    status_var = tk.StringVar(value=initial_message or "Aún no hay una licencia válida instalada.")
    ttk.Label(outer, textvariable=status_var, wraplength=560, justify="left").pack(anchor="w", pady=(4, 14))

    btns = ttk.Frame(outer)
    btns.pack(fill="x", pady=(4, 0))

    def copy_id():
        win.clipboard_clear()
        win.clipboard_append(installation_id)
        win.update()
        status_var.set("ID de instalación copiado al portapapeles.")

    def import_license():
        src = filedialog.askopenfilename(
            parent=win,
            title="Seleccionar licencia",
            filetypes=[("Licencia", "*.dat"), ("JSON", "*.json"), ("Todos los archivos", "*.*")],
        )
        if not src:
            return
        status = install_license_file(src)
        status_var.set(status.message)
        if status.valid:
            result["activated"] = True
            messagebox.showinfo("Activación completada", status.message, parent=win)
            win.destroy()
        else:
            messagebox.showerror("Licencia rechazada", status.message, parent=win)

    def close():
        win.destroy()

    ttk.Button(btns, text="Copiar ID", command=copy_id).pack(side="left")
    ttk.Button(btns, text="Importar license.dat", command=import_license).pack(side="left", padx=8)
    ttk.Button(btns, text="Salir", command=close).pack(side="right")

    win.protocol("WM_DELETE_WINDOW", close)
    parent.wait_window(win)
    return bool(result["activated"])


def ensure_activated(parent) -> bool:
    status = verify_installed_license()
    if status.valid:
        return True
    return show_activation_dialog(parent, status.message)
