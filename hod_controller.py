# -*- coding: utf-8 -*-
"""
hod_controller.py

Controlador multiplataforma para Descargo de Medicación sobre IBM i Access
Client Solutions (ACS) 1.1.8.7 / emulador 5250 basado en Host On-Demand.

En PCOMM la aplicación usaba win32com/autECL. ACS no ofrece esa interfaz COM de PCOMM de forma multiplataforma. Para conservar la MISMA sesión 5250 visible, este port usa un
pequeño protocolo por portapapeles y tres macros HOD 11.0.8 instaladas en
ACS. La aplicación escribe el comando en el portapapeles, activa la ventana
5250 y dispara DIRECTAMENTE el macro correspondiente mediante un atajo
configurable. No se usa Play Macro ni encadenamiento, porque ACS/HOD exige que
los macros encadenados residan exactamente en la misma ubicación y eso puede
provocar el error «A chained macro ... does not exist».
El macro ejecuta la automatización dentro de la sesión y devuelve su resultado
por el mismo portapapeles.

No requiere pywin32, COM, EHLLAPI ni clases Java externas.
"""
from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

import license_manager

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MACRO_TIMEOUT_SECONDS = 600
MAX_CAPTURE_PAGES = 60

SEARCH_RESULT_ROW = 11
SEARCH_RESULT_COL = 2
ORDER_ROWS = [16, 18, 20]
COL_CANT_TENS = 17
COL_CANT = 18
COL_DOSIS = 21
COL_VIA = 30
COL_FRECUENCIA = 45
COL_DURA_CANT = 57
COL_DURA_UNIDAD = 59
GUARD_ROW = 15
GUARD_COL = 2
GUARD_LEN = 2
VIA_SELECTOR_KEY = "[pf4]"
PF4_POPUP_DELAY_SECONDS = 0.3
PF4_CONFIRM_DELAY_SECONDS = 0.2
AGOTADO_MSG_ROW = 14
AGOTADO_MSG_COL = 23
AGOTADO_MSG_LEN = 60

READ_COMMAND = "###DESCARGO_HOD1108_READ###"
READ_OK = "###DESCARGO_HOD1108_READ_OK###"
EXEC_COMMAND = "###DESCARGO_HOD1108_EXEC###"
EXEC_STARTED = "###DESCARGO_HOD1108_EXEC_STARTED###"
EXEC_OK = "###DESCARGO_HOD1108_EXEC_OK###"
EXEC_ERROR = "###DESCARGO_HOD1108_EXEC_ERROR###"
CONFIRM_COMMAND = "###DESCARGO_HOD1108_CONFIRM###"
CONFIRM_OK = "###DESCARGO_HOD1108_CONFIRM_OK###"


@dataclass
class OrderFields:
    codigo: str
    cantidad: str
    dosis: str
    unidad: str
    frecuencia: str
    dura_cantidad: str
    dura_unidad: str


class HODController:
    def __init__(
        self,
        session_name: str = "",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        screen_coords: Optional[dict] = None,
        acs_window_title_contains: str = "5250",
        acs_read_hotkey_key: str = "l",
        acs_exec_hotkey_key: str = "e",
        acs_confirm_hotkey_key: str = "c",
        acs_macro_hotkey_modifiers: str | Sequence[str] = "control,shift",
        macro_timeout_seconds: int = DEFAULT_MACRO_TIMEOUT_SECONDS,
    ):
        status = license_manager.verify_installed_license()
        if not status.valid:
            raise PermissionError(f"Licencia no válida: {status.message}")

        self.session_name = session_name or "ACS 5250 activo"
        self.timeout_seconds = max(1, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
        self.macro_timeout_seconds = max(
            self.timeout_seconds, int(macro_timeout_seconds or DEFAULT_MACRO_TIMEOUT_SECONDS)
        )
        self.acs_window_title_contains = (acs_window_title_contains or "5250").strip()
        self.acs_read_hotkey_key = (acs_read_hotkey_key or "l").strip().lower()
        self.acs_exec_hotkey_key = (acs_exec_hotkey_key or "e").strip().lower()
        self.acs_confirm_hotkey_key = (acs_confirm_hotkey_key or "c").strip().lower()
        self.acs_macro_hotkey_modifiers = self._normalise_modifiers(acs_macro_hotkey_modifiers)
        self._last_patient_name = ""

        coords = screen_coords or {}
        self.search_result_row = int(coords.get("search_result_row", SEARCH_RESULT_ROW))
        self.search_result_col = int(coords.get("search_result_col", SEARCH_RESULT_COL))
        self.order_rows = [int(x) for x in coords.get("order_rows", ORDER_ROWS)]
        self.col_cant_tens = int(coords.get("col_cant_tens", COL_CANT_TENS))
        self.col_cant = int(coords.get("col_cant", COL_CANT))
        self.col_dosis = int(coords.get("col_dosis", COL_DOSIS))
        self.col_via = int(coords.get("col_via", COL_VIA))
        self.col_frecuencia = int(coords.get("col_frecuencia", COL_FRECUENCIA))
        self.col_dura_cant = int(coords.get("col_dura_cant", COL_DURA_CANT))
        self.col_dura_unidad = int(coords.get("col_dura_unidad", COL_DURA_UNIDAD))
        self.guard_row = int(coords.get("guard_row", GUARD_ROW))
        self.guard_col = int(coords.get("guard_col", GUARD_COL))
        self.guard_len = int(coords.get("guard_len", GUARD_LEN))
        self.agotado_msg_row = int(coords.get("agotado_msg_row", AGOTADO_MSG_ROW))
        self.agotado_msg_col = int(coords.get("agotado_msg_col", AGOTADO_MSG_COL))
        self.agotado_msg_len = int(coords.get("agotado_msg_len", AGOTADO_MSG_LEN))
        self.pf4_popup_delay_seconds = float(
            coords.get("pf4_popup_delay_seconds", PF4_POPUP_DELAY_SECONDS)
        )
        self.pf4_confirm_delay_seconds = float(
            coords.get("pf4_confirm_delay_seconds", PF4_CONFIRM_DELAY_SECONDS)
        )
        self.via_selector_key = str(coords.get("via_selector_key", VIA_SELECTOR_KEY) or VIA_SELECTOR_KEY)

        if len(self.order_rows) != 3:
            raise ValueError(
                "HOD1108 requiere exactamente 3 filas visibles en la grilla de orden "
                "(por defecto 16,18,20)."
            )

    @staticmethod
    def _normalise_modifiers(value: str | Sequence[str]) -> List[str]:
        if isinstance(value, str):
            items = [x.strip().lower() for x in value.split(",") if x.strip()]
        else:
            items = [str(x).strip().lower() for x in value if str(x).strip()]
        aliases = {
            "ctrl": "control",
            "control": "control",
            "cmd": "command",
            "command": "command",
            "option": "option",
            "alt": "option",
            "shift": "shift",
        }
        out: List[str] = []
        for item in items:
            norm = aliases.get(item)
            if norm and norm not in out:
                out.append(norm)
        return out or ["control", "shift"]

    # ------------------------------------------------------------------
    # Portapapeles
    # ------------------------------------------------------------------
    @staticmethod
    def _set_clipboard(text: str) -> None:
        if platform.system() == "Darwin":
            proc = subprocess.run(
                ["/usr/bin/pbcopy"], input=text, text=True, encoding="utf-8",
                capture_output=True, check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"No se pudo escribir al portapapeles de macOS: {proc.stderr.strip()}")
            return

        if platform.system() == "Windows":
            # IMPORTANTE: en Windows de 64 bits los handles HGLOBAL son punteros
            # de 64 bits. Si ctypes usa sus tipos por defecto (c_int), GlobalAlloc
            # y GlobalLock quedan truncados y GlobalLock falla aun cuando la
            # reserva fue correcta. Declaramos todas las firmas explícitamente.
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002

            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL

            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
            kernel32.GlobalFree.restype = ctypes.c_void_p

            # create_unicode_buffer incluye el terminador NUL y en Windows
            # ctypes.c_wchar usa UTF-16, exactamente lo requerido por
            # CF_UNICODETEXT.
            buf = ctypes.create_unicode_buffer(text)
            nbytes = ctypes.sizeof(buf)

            for _ in range(80):  # hasta ~2 s si otra app retiene el clipboard
                if user32.OpenClipboard(None):
                    break
                time.sleep(0.025)
            else:
                err = ctypes.get_last_error()
                raise RuntimeError(f"No se pudo abrir el portapapeles de Windows (error {err}).")

            hglobal = None
            try:
                if not user32.EmptyClipboard():
                    err = ctypes.get_last_error()
                    raise RuntimeError(f"No se pudo vaciar el portapapeles de Windows (error {err}).")

                hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE, nbytes)
                if not hglobal:
                    err = ctypes.get_last_error()
                    raise RuntimeError(f"No se pudo reservar memoria para el portapapeles (error {err}).")

                ptr = kernel32.GlobalLock(hglobal)
                if not ptr:
                    err = ctypes.get_last_error()
                    kernel32.GlobalFree(hglobal)
                    hglobal = None
                    raise RuntimeError(f"No se pudo bloquear memoria del portapapeles (error {err}).")

                try:
                    ctypes.memmove(ptr, ctypes.addressof(buf), nbytes)
                finally:
                    kernel32.GlobalUnlock(hglobal)

                if not user32.SetClipboardData(CF_UNICODETEXT, hglobal):
                    err = ctypes.get_last_error()
                    kernel32.GlobalFree(hglobal)
                    hglobal = None
                    raise RuntimeError(f"Windows rechazó el contenido del portapapeles (error {err}).")

                # Después de SetClipboardData exitoso, Windows es propietario
                # del HGLOBAL y NO debemos liberarlo nosotros.
                hglobal = None
            finally:
                user32.CloseClipboard()
                if hglobal:
                    kernel32.GlobalFree(hglobal)
            return

        # Fallback para otros sistemas.
        import tkinter as tk
        root = tk.Tk(); root.withdraw()
        try:
            root.clipboard_clear(); root.clipboard_append(text); root.update()
        finally:
            root.destroy()

    @staticmethod
    def _get_clipboard() -> str:
        if platform.system() == "Darwin":
            proc = subprocess.run(
                ["/usr/bin/pbpaste"], text=True, encoding="utf-8",
                capture_output=True, check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"No se pudo leer el portapapeles de macOS: {proc.stderr.strip()}")
            return proc.stdout

        if platform.system() == "Windows":
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            CF_UNICODETEXT = 13

            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.GetClipboardData.argtypes = [wintypes.UINT]
            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = wintypes.BOOL

            for _ in range(80):
                if user32.OpenClipboard(None):
                    break
                time.sleep(0.025)
            else:
                return ""

            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return ""
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()

        import tkinter as tk
        root = tk.Tk(); root.withdraw()
        try:
            try:
                return root.clipboard_get()
            except tk.TclError:
                return ""
        finally:
            root.destroy()

    # ------------------------------------------------------------------
    # Disparo del macro dentro de la ventana ACS que YA está abierta
    # ------------------------------------------------------------------
    @staticmethod
    def _apple_script_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _trigger_macro(self, macro_key: str) -> None:
        """Activa la ventana ACS/5250 y dispara el atajo del macro.

        macOS: System Events/AppleScript.
        Windows: API Win32 (ctypes), sin pywin32 ni dependencias externas.
        """
        if not self.acs_window_title_contains:
            raise RuntimeError("Configura un texto que identifique la ventana 5250 de ACS.")
        macro_key = (macro_key or "").strip().lower()
        if len(macro_key) != 1:
            raise RuntimeError("La tecla del macro debe ser un solo carácter, por ejemplo: l")

        system = platform.system()
        if system == "Windows":
            self._trigger_macro_windows(macro_key)
            return
        if system != "Darwin":
            raise RuntimeError(
                "La ejecución automática de macros está implementada para Windows y macOS."
            )

        title = self._apple_script_string(self.acs_window_title_contains)
        key = self._apple_script_string(macro_key)
        mod_map = {
            "control": "control down",
            "shift": "shift down",
            "command": "command down",
            "option": "option down",
        }
        mods = ", ".join(mod_map[m] for m in self.acs_macro_hotkey_modifiers if m in mod_map)
        using_clause = f" using {{{mods}}}" if mods else ""

        script = f'''
        tell application "System Events"
            set targetText to "{title}"
            set foundOne to false
            repeat with p in application processes
                try
                    repeat with w in windows of p
                        if ((name of w) as text) contains targetText then
                            set frontmost of p to true
                            set foundOne to true
                            exit repeat
                        end if
                    end repeat
                end try
                if foundOne then exit repeat
            end repeat
            if not foundOne then error "No se encontró una ventana ACS/5250 que contenga: {title}"
            delay 0.20
            keystroke "{key}"{using_clause}
        end tell
        '''
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", script], text=True, encoding="utf-8",
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            if "not authorized" in detail.lower() or "assistive" in detail.lower() or "-1743" in detail:
                raise RuntimeError(
                    "macOS bloqueó el control de la ventana ACS. Ve a Ajustes del Sistema > "
                    "Privacidad y seguridad > Accesibilidad y autoriza DescargoMedicacion "
                    "(o Terminal/Python si lo ejecutas en desarrollo)."
                )
            raise RuntimeError(f"No se pudo activar ACS/disparar el macro HOD: {detail}")

    @staticmethod
    def _visible_windows_windows():
        """Devuelve ventanas superiores visibles: (hwnd, título, clase, pid)."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        matches = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        @WNDENUMPROC
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            title_buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, title_buf, n + 1)
            title = title_buf.value.strip()
            if not title:
                return True
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 255)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            matches.append((hwnd, title, class_buf.value, int(pid.value)))
            return True

        user32.EnumWindows(enum_proc, 0)
        return matches

    @classmethod
    def windows_debug_titles(cls) -> list[str]:
        if platform.system() != "Windows":
            return []
        return [f"{title}    [clase={klass}, pid={pid}]" for _h, title, klass, pid in cls._visible_windows_windows()]

    def _trigger_macro_windows(self, macro_key: str) -> None:
        """Activa SOLO la ventana de sesión 5250, nunca el lanzador general de ACS."""
        import ctypes

        user32 = ctypes.windll.user32
        target = (self.acs_window_title_contains or "").strip().casefold()
        all_windows = self._visible_windows_windows()
        launcher_exact = "ibm i access client solutions"

        def is_our_app(title: str) -> bool:
            t = title.casefold()
            return "descargo de medicación" in t or "descargo de medicacion" in t

        # Nunca enviar teclas al lanzador azul de ACS mostrado en la captura.
        usable = [w for w in all_windows
                  if w[1].strip().casefold() != launcher_exact and not is_our_app(w[1])]

        matches = [w for w in usable if target and target in w[1].casefold()]

        # Si el texto guardado es demasiado genérico o viene de una versión anterior,
        # intentamos detectar una única ventana Java de sesión, pero no adivinamos si hay varias.
        if not matches:
            java_candidates = [w for w in usable if "sunawt" in w[2].casefold()]
            strong = [w for w in java_candidates if any(tok in w[1].casefold() for tok in
                      ("5250", "session", "sesion", "sesión", "display"))]
            candidates = strong or java_candidates
            if len(candidates) == 1:
                matches = candidates
            else:
                titles = "\n".join(f"  • {w[1]}" for w in candidates[:12]) or "  (ninguna candidata)"
                raise RuntimeError(
                    "No pude identificar de forma segura la ventana de la SESIÓN 5250.\n\n"
                    "La ventana 'IBM i Access Client Solutions' es solo el lanzador y NO debe usarse.\n"
                    "Abre la sesión 5250 y en Configuración > Conexión ACS/HOD coloca una parte "
                    "del título que aparece ARRIBA de la ventana negra/verde del terminal.\n\n"
                    "Ventanas Java candidatas detectadas:\n" + titles
                )

        def rank(w):
            text = w[1].casefold()
            score = 0
            if target and target in text: score += 50
            if "5250" in text: score += 30
            if "session" in text or "sesion" in text or "sesión" in text: score += 15
            if "display" in text: score += 10
            if "sunawt" in w[2].casefold(): score += 5
            if text == launcher_exact: score -= 1000
            return score

        matches.sort(key=rank, reverse=True)
        hwnd, found_title, _klass, _pid = matches[0]
        if found_title.strip().casefold() == launcher_exact:
            raise RuntimeError(
                "La configuración está apuntando al lanzador general de IBM i Access Client Solutions, "
                "no a la sesión 5250. Abre la sesión y usa parte del título de ESA ventana."
            )

        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        KEYEVENTF_KEYUP = 0x0002
        VK_MENU = 0x12
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        if not user32.SetForegroundWindow(hwnd):
            raise RuntimeError(
                f"Windows encontró la sesión ('{found_title}') pero no pudo ponerla al frente."
            )
        time.sleep(0.25)

        # Confirmar que Windows realmente dejó esa ventana al frente.
        fg = user32.GetForegroundWindow()
        if fg != hwnd:
            raise RuntimeError(
                f"Windows no dejó al frente la sesión 5250 seleccionada ('{found_title}')."
            )

        vk_mods = {
            "control": 0x11, "shift": 0x10, "option": 0x12, "command": 0x5B,
        }
        pressed = []
        for mod in self.acs_macro_hotkey_modifiers:
            vk = vk_mods.get(mod)
            if vk is not None:
                user32.keybd_event(vk, 0, 0, 0)
                pressed.append(vk)

        ch = macro_key.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            vk_key = ord(ch)
        else:
            scan = user32.VkKeyScanW(ord(ch))
            if scan == -1:
                for vk in reversed(pressed):
                    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                raise RuntimeError(f"No se puede convertir la tecla '{macro_key}' a un hotkey de Windows.")
            vk_key = scan & 0xFF

        user32.keybd_event(vk_key, 0, 0, 0)
        user32.keybd_event(vk_key, 0, KEYEVENTF_KEYUP, 0)
        for vk in reversed(pressed):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def _invoke_macro(
        self,
        payload: str,
        success_prefix: str,
        error_prefixes: Iterable[str] = (),
        timeout_seconds: Optional[int] = None,
        macro_key: str = "",
        started_prefix: str = "",
        start_timeout_seconds: float = 6.0,
    ) -> str:
        """Dispara un macro y espera su respuesta por portapapeles.

        Para macros largos puede suministrarse ``started_prefix``. En ese caso el
        macro debe escribir ese marcador apenas haya leído el payload. Esto permite
        distinguir un macro que nunca arrancó de uno que sí está trabajando.
        """
        self._set_clipboard(payload)
        self._trigger_macro(macro_key)
        now = time.monotonic()
        deadline = now + float(timeout_seconds or self.macro_timeout_seconds)
        start_deadline = now + max(1.0, float(start_timeout_seconds))
        error_prefixes = tuple(error_prefixes)
        started = not bool(started_prefix)
        last_clip = ""
        while time.monotonic() < deadline:
            time.sleep(0.12)
            try:
                current = self._get_clipboard()
            except Exception:
                continue
            if current == payload:
                if not started and time.monotonic() >= start_deadline:
                    raise RuntimeError(
                        "La aplicación dejó preparada la orden, pero DescargoEjecutar_HOD1108 "
                        "no confirmó que haya arrancado. Comprueba que Ctrl+Shift+E esté asignado "
                        "a DescargoEjecutar_HOD1108 en ESTA sesión 5250. Puedes probar Ctrl+Shift+E "
                        "manualmente: si el macro arranca, el problema está en el atajo/configuración."
                    )
                continue
            last_clip = current
            if started_prefix and current.startswith(started_prefix):
                started = True
                continue
            if current.startswith(success_prefix):
                return current
            if any(current.startswith(p) for p in error_prefixes):
                first = current.splitlines()[0] if current else "error HOD"
                details = "\n".join(current.splitlines()[1:]).strip()
                raise RuntimeError(f"El macro HOD devolvió {first}" + (f": {details}" if details else ""))
            if not started and time.monotonic() >= start_deadline:
                raise RuntimeError(
                    "DescargoEjecutar_HOD1108 no confirmó el inicio dentro del tiempo esperado. "
                    f"Último contenido del portapapeles: {current[:160]!r}"
                )

        state = "arrancó pero no terminó" if started else "no confirmó el arranque"
        raise TimeoutError(
            f"El macro HOD {state} dentro del tiempo configurado. "
            f"Atajo: {self.hotkey_display(macro_key)}. Ventana ACS: '{self.acs_window_title_contains}'."
            + (f" Último contenido del portapapeles: {last_clip[:160]!r}" if last_clip else "")
        )

    def hotkey_display(self, macro_key: str) -> str:
        labels = {"control": "Ctrl", "shift": "Shift", "command": "Cmd", "option": "Option"}
        parts = [labels.get(x, x.title()) for x in self.acs_macro_hotkey_modifiers]
        parts.append((macro_key or "?").upper())
        return "+".join(parts)

    # ------------------------------------------------------------------
    # Operaciones de alto nivel usadas por la GUI
    # ------------------------------------------------------------------
    def capture_note_text(self, on_progress=None) -> str:
        response = self._invoke_macro(READ_COMMAND, READ_OK, timeout_seconds=min(self.macro_timeout_seconds, 90), macro_key=self.acs_read_hotkey_key)
        # Respuesta: marcador + nombre paciente + texto completo.
        parts = response.replace("\r\n", "\n").replace("\r", "\n").split("\n", 2)
        if len(parts) < 3:
            raise RuntimeError("Respuesta incompleta del macro DescargoLeer_HOD1108.")
        self._last_patient_name = parts[1].strip()
        if on_progress:
            try:
                on_progress(1, MAX_CAPTURE_PAGES)
            except Exception:
                pass
        return parts[2]

    def get_patient_name(self) -> str:
        return self._last_patient_name or "(sin identificar)"

    def _build_exec_payload(self, all_fields: List[OrderFields], remove_patient: bool) -> str:
        if not all_fields:
            raise ValueError("No hay medicamentos para descargar.")
        if len(all_fields) > 200:
            raise ValueError("Cantidad de medicamentos fuera del límite de seguridad (200).")

        rows = self.order_rows
        cfg = [
            1 if remove_patient else 0,
            len(all_fields),
            self.search_result_row,
            self.search_result_col,
            rows[0], rows[1], rows[2],
            self.col_cant_tens,
            self.col_cant,
            self.col_dosis,
            self.col_via,
            self.col_frecuencia,
            self.col_dura_cant,
            self.col_dura_unidad,
            self.guard_row,
            self.guard_col,
            self.guard_len,
            self.agotado_msg_row,
            self.agotado_msg_col,
            self.agotado_msg_len,
            max(0, round(self.pf4_popup_delay_seconds * 1000)),
            max(0, round(self.pf4_confirm_delay_seconds * 1000)),
            self.via_selector_key,
        ]
        lines = [EXEC_COMMAND, "CFG=" + "|".join(str(x) for x in cfg)]
        for f in all_fields:
            code = str(f.codigo or "").strip()
            qty = str(f.cantidad or "").strip()
            if not code or "|" in code or "\n" in code or "\r" in code:
                raise ValueError(f"Código de medicamento inválido: {code!r}")
            if not qty.isdigit() or not (1 <= int(qty) <= 99):
                raise ValueError(
                    f"Cantidad inválida para {code}: {qty!r}. HOD1108 admite 1 a 99."
                )
            lines.append(f"{code}|{int(qty)}")
        return "\n".join(lines)

    def execute_descargo(self, all_fields: List[OrderFields], remove_patient: bool = False) -> Set[str]:
        payload = self._build_exec_payload(all_fields, remove_patient)
        response = self._invoke_macro(
            payload, EXEC_OK, (EXEC_ERROR,), macro_key=self.acs_exec_hotkey_key,
            started_prefix=EXEC_STARTED, start_timeout_seconds=8.0,
        )
        exhausted: Set[str] = set()
        for line in response.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if line.startswith("AGOTADOS="):
                raw = line[len("AGOTADOS="):]
                exhausted = {x.strip() for x in raw.split(";") if x.strip()}
                break
        return exhausted

    def confirm_descargo(self) -> None:
        self._invoke_macro(
            CONFIRM_COMMAND, CONFIRM_OK,
            timeout_seconds=min(self.macro_timeout_seconds, 180),
            macro_key=self.acs_confirm_hotkey_key,
        )

    def close(self) -> None:
        # No se mantiene socket ni sesión externa. La sesión pertenece a ACS.
        return


# Alias para minimizar cambios en código auxiliar antiguo.
PcommController = HODController
