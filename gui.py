# -*- coding: utf-8 -*-
"""
gui.py
Interfaz gráfica (Tkinter) para revisar y ejecutar el descargo de medicación.

Versión simplificada, 100% tema oscuro:
- Barra de acciones con 6 botones grandes, sin menú ni barra de íconos:
    📥 Leer         -> captura la nota desde AS400 (antes de conectar,
                        pregunta si ya estás dentro de la nota a descargar,
                        para evitar leer la pantalla equivocada).
    ➕ Añadir        -> agrega un medicamento a mano (búsqueda en catálogo).
    ▲ Aumentar / ▼ Disminuir -> cantidad del/los medicamento(s) seleccionado(s).
    🗑️ Eliminar      -> quita de la lista el/los medicamento(s) seleccionado(s).
    📤 Descargar     -> ejecuta el descargo SIEMPRE solo con los medicamentos
                        listos (verde), sin importar la selección actual.
- Panel izquierdo: lista de medicamentos (selección múltiple tipo Explorador:
  clic, Ctrl+clic, Shift+clic). Doble clic o Enter abre el buscador para
  reasignar/confirmar un medicamento; clic derecho da más opciones
  (buscar/reasignar, +/-, marcar agotado, eliminar).
- Panel derecho: la nota completa; se resalta la línea del medicamento
  seleccionado.
- Encabezado: nombre del paciente + contador de estado (verde/amarillo/
  rojo/gris) + botón de configuración (⚙️, sesión AS400, catálogo,
  coordenadas de pantalla, sinónimos, etc.).
- Barra inferior: estado de texto + barra de progreso durante captura/descargo.

Uso:
    python gui.py [--acs-window-title "5250"] [--catalog farmacos.csv]

La automatización de la sesión activa se ejecuta mediante macros HOD 11.0.8
instaladas en IBM i Access Client Solutions y asignadas a un atajo de teclado.
La configuración se guarda en config.json.
"""

import argparse
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from dataclasses import dataclass, replace
from typing import Optional, List

from note_parser import parse_note, MedicationLine, set_route_synonyms
from catalog import (
    load_catalog, candidates_by_name, CatalogRow, set_name_synonyms, set_fuzzy_cutoff,
    search_catalog, normalize_prescription_key,
)
from med_matcher import match_medication
from hod_controller import HODController, OrderFields, MAX_CAPTURE_PAGES
import app_config
import license_manager


# PNG 32x32 embebido (cruz médica blanca sobre fondo teal) para no depender
# de ningún archivo externo. Si además existe app_icon.ico junto a este
# script, se usa para el ícono de la barra de título/taskbar en Windows.
APP_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAoUlEQVR4nO2Xyw2AIAxAS+O2uoAOIAvIvHjQRCOtUOTjoT2C9r0A"
    "5QPQOQzbM4++OM26gBcK1AC/iGBz+IODVGNLiSHnX79ubJ9ZJlEuc7f5Cs+RwPgndUMFVICtgpTVLoYR1UGOQA04l7f7FKiACvxT"
    "QHqkpgaVV49jFVCBQ4B4sXARW+GiErbOZF3LS+4T1xQIRqFInDykGlvBAX7wOt4BFtMx1e5NlWoAAAAASUVORK5CYII="
)

HIGHLIGHT_BG = "#4a3f00"
HIGHLIGHT_FG = "#ffe680"

# ----------------------------------------------------------------------
# Paleta única, oscura. Ya no existe modo claro: se simplifica a propósito
# para que la app siempre se vea y se sienta igual sin importar el equipo.
# ----------------------------------------------------------------------
BG = "#171717"           # fondo raíz
PANEL_BG = "#1e1e1e"      # encabezado / barra de acciones / barra de estado
CARD_BG = "#242424"       # botones normales
LIST_BG = "#1c1c1c"       # lista de medicamentos / entradas / listboxes
NOTE_BG = "#111111"       # panel de nota
NOTE_FG = "#d6d6d6"
FG = "#eaeaea"
MUTED_FG = "#9a9a9a"
BORDER = "#333333"

ACCENT = "#2f7de1"        # azul de foco/selección
ACCENT_HOVER = "#458af0"

SUCCESS = "#1f7a3d"
SUCCESS_HOVER = "#249144"
SUCCESS_PRESS = "#155c2d"

DANGER = "#7a2020"
DANGER_HOVER = "#8f2626"
DANGER_PRESS = "#5c1717"

STATUS_COLORS = {
    "ok": "#20321f",
    "ambiguo": "#3c3212",
    "manual_review": "#3c3212",
    "sin_match": "#3b1a1c",
    "suspendido": "#2a2a2a",
}
STATUS_FG = {
    "ok": "#92c353", "ambiguo": "#fce100", "manual_review": "#fce100",
    "sin_match": "#ff99a4", "suspendido": "#b0b0b0",
}

STATUS_LABELS = {
    "ok": "Listo",
    "ambiguo": "Revisar",
    "manual_review": "Revisar",
    "sin_match": "Sin match",
    "suspendido": "Suspendido",
    "pendiente": "Pendiente",
}

# Colores fijos para los indicadores del contador (como cualquier luz de
# estado: verde, amarillo, rojo, gris).
COUNTER_COLORS = {
    "ok": "#2e7d32",
    "dudoso": "#c9a227",
    "sin_match": "#c62828",
    "suspendido": "#9e9e9e",
}


# ----------------------------------------------------------------------
# Tooltip simple para los botones
# ----------------------------------------------------------------------
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip, text=self.text, background="#2c2c2c", foreground="#ffffff",
            relief="solid", borderwidth=1, padx=8, pady=3, font=("Segoe UI", 9)
        )
        label.pack()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


@dataclass
class MedRow:
    med: MedicationLine
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    presentacion: Optional[str] = None
    status: str = "pendiente"  # "ok" | "ambiguo" | "sin_match" | "manual_review" | "suspendido"
    cantidad: int = 1
    # La selección múltiple usa la selección nativa del Treeview (clic,
    # Ctrl+clic, Shift+clic), igual que en el Explorador de Windows.


class DescargoApp:
    def __init__(self, root, session_name: str, catalog_path: str, config: Optional[dict] = None):
        self.root = root
        self.config = config or app_config.load_config()

        # `session_name` queda como dato legado. En ACS/macOS se trabaja sobre
        # la sesión 5250 YA abierta disparando directamente 3 macros HOD1108.
        self.session_name = session_name
        self.acs_window_title_contains = self.config.get("acs_window_title_contains", "5250")
        self.acs_read_hotkey_key = self.config.get("acs_read_hotkey_key", "l")
        self.acs_exec_hotkey_key = self.config.get("acs_exec_hotkey_key", "e")
        self.acs_confirm_hotkey_key = self.config.get("acs_confirm_hotkey_key", "c")
        self.acs_macro_hotkey_modifiers = self.config.get("acs_macro_hotkey_modifiers", "control,shift")
        self.macro_timeout_seconds = int(self.config.get("macro_timeout_seconds", 600))
        self.catalog_path = catalog_path
        self.config["session_name"] = session_name
        self.config["catalog_path"] = catalog_path
        self.timeout_seconds = self.config.get("timeout_seconds", 15)
        self.note_font_size = self.config.get("note_font_size", 10)

        # Aplicar reglas de negocio guardadas (sinónimos / umbral difuso)
        set_name_synonyms(self.config.get("name_synonyms", {}))
        set_fuzzy_cutoff(self.config.get("fuzzy_cutoff", 0.75))
        set_route_synonyms(self.config.get("route_synonyms", {}))

        # Registro personal de coincidencias exactas (línea de prescripción
        # completa -> medicamento elegido la última vez).
        self.exact_matches = dict(self.config.get("exact_matches", {}))

        # Favoritos: medicamentos guardados con una cantidad fija (ej. "Cloruro
        # de Sodio 0.9% x3"), para agregarlos a la lista con un solo clic.
        self.bookmarks: List[dict] = []
        for b in self.config.get("bookmarks", []):
            bb = dict(b)
            bb["cantidad"] = max(1, int(bb.get("cantidad", 1) or 1))
            self.bookmarks.append(bb)

        try:
            self.catalog = load_catalog(app_config.resolve_data_path(catalog_path))
        except Exception as e:
            messagebox.showerror("Error al cargar el catálogo", str(e))
            self.catalog = []

        self.rows: List[MedRow] = []
        self.controller: Optional[HODController] = None
        self.full_note_text = ""
        self._icon_img_ref = None  # mantener viva la referencia al PhotoImage del ícono
        self._suppress_select_event = False  # evita recursión al reconstruir el árbol
        self._search_popup = None

        self.style = ttk.Style(self.root)
        self._setup_window()
        self._configure_ttk_style()
        self._build_ui()
        self._setup_global_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Ventana: título, ícono, tamaño/posición recordados
    # ------------------------------------------------------------------
    def _setup_window(self):
        self.root.title("Descargo de Medicación")
        self.root.configure(bg=BG)
        self._set_app_icon()

        geometry = self.config.get("window_geometry") or "1300x720"
        try:
            self.root.geometry(geometry)
        except tk.TclError:
            self.root.geometry("1300x720")
        self.root.minsize(950, 520)

    def _set_app_icon(self):
        try:
            icon_img = tk.PhotoImage(data=APP_ICON_B64)
            self.root.iconphoto(True, icon_img)
            self._icon_img_ref = icon_img  # evitar que el garbage collector se lo lleve
        except Exception:
            pass
        ico_path = app_config.resource_path("app_icon.ico")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass

    def _on_close(self):
        try:
            self.config["window_geometry"] = self.root.geometry()
            app_config.save_config(self.config)
        except Exception:
            pass
        if self.controller is not None:
            try:
                self.controller.close()
            except Exception:
                pass
            self.controller = None
        self.root.destroy()

    def _require_valid_license(self) -> bool:
        """Revalida la licencia firmada antes de operar sobre HOD."""
        status = license_manager.verify_installed_license()
        if status.valid:
            return True
        if license_manager.show_activation_dialog(self.root, status.message):
            return license_manager.verify_installed_license().valid
        return False

    # ------------------------------------------------------------------
    # Estilo ttk: tema 'clam' forzado (es el único tema ttk multiplataforma
    # que permite pintar colores propios de verdad; el tema nativo 'vista'
    # de Windows ignora casi cualquier color a medida, así que no sirve
    # para un tema oscuro real).
    # ------------------------------------------------------------------
    def _configure_ttk_style(self):
        available = self.style.theme_names()
        self.style.theme_use("clam" if "clam" in available else available[0])

        base_font = ("Segoe UI", 10)
        self.style.configure(".", font=base_font, background=BG, foreground=FG)

        self.style.configure("Root.TFrame", background=BG)
        self.style.configure("Panel.TFrame", background=PANEL_BG)
        self.style.configure("Toolbar.TFrame", background=BG)

        self.style.configure("Root.TLabel", background=BG, foreground=FG)
        self.style.configure("Panel.TLabel", background=PANEL_BG, foreground=FG)
        self.style.configure("Header.TLabel", background=PANEL_BG, foreground=FG, font=("Segoe UI", 13, "bold"))
        self.style.configure("Counter.TLabel", background=PANEL_BG, foreground=FG, font=("Segoe UI", 10, "bold"))
        self.style.configure("Status.TLabel", background=PANEL_BG, foreground=MUTED_FG)

        # Botones grandes de la barra de acciones (los 6 principales)
        self.style.configure(
            "Big.TButton", background=CARD_BG, foreground=FG, font=("Segoe UI", 11, "bold"),
            padding=(10, 12), borderwidth=0, focusthickness=0, focuscolor=CARD_BG, relief="flat",
            justify="center",
        )
        self.style.map("Big.TButton", background=[("active", "#2f2f2f"), ("pressed", "#141414")])

        self.style.configure(
            "Accent.TButton", background=SUCCESS, foreground="#ffffff", font=("Segoe UI", 11, "bold"),
            padding=(10, 12), borderwidth=0, focusthickness=0, focuscolor=SUCCESS, relief="flat",
            justify="center",
        )
        self.style.map("Accent.TButton", background=[("active", SUCCESS_HOVER), ("pressed", SUCCESS_PRESS)])

        self.style.configure(
            "Danger.TButton", background=DANGER, foreground="#ffffff", font=("Segoe UI", 11, "bold"),
            padding=(10, 12), borderwidth=0, focusthickness=0, focuscolor=DANGER, relief="flat",
            justify="center",
        )
        self.style.map("Danger.TButton", background=[("active", DANGER_HOVER), ("pressed", DANGER_PRESS)])

        self.style.configure(
            "SmallWarn.TButton", background="#8a5a12", foreground="#ffffff", font=("Segoe UI", 9, "bold"),
            padding=(8, 6), borderwidth=0, focusthickness=0, focuscolor="#8a5a12", relief="flat",
            justify="center",
        )
        self.style.map("SmallWarn.TButton", background=[("active", "#a36b18"), ("pressed", "#70480e")])

        # Chips de favoritos (fila debajo de la barra principal)
        self.style.configure(
            "Fav.TButton", background="#2a2440", foreground=FG, font=("Segoe UI", 10, "bold"),
            padding=(10, 8), borderwidth=0, focusthickness=0, focuscolor="#2a2440", relief="flat",
        )
        self.style.map("Fav.TButton", background=[("active", "#372f57"), ("pressed", "#1e1a30")])

        # Botón chico (engranaje de configuración)
        self.style.configure(
            "MiniIcon.TButton", background=PANEL_BG, foreground=FG, font=("Segoe UI", 13),
            padding=4, borderwidth=0, focusthickness=0, focuscolor=PANEL_BG, relief="flat",
        )
        self.style.map("MiniIcon.TButton", background=[("active", "#333333")])

        # Botones normales (usados dentro de diálogos de configuración/búsqueda)
        self.style.configure(
            "TButton", background=CARD_BG, foreground=FG, borderwidth=0,
            focusthickness=0, focuscolor=CARD_BG, padding=6, relief="flat",
        )
        self.style.map("TButton", background=[("active", "#2f2f2f")])

        self.style.configure("TSeparator", background=BORDER)

        self.style.configure("TEntry", fieldbackground=LIST_BG, foreground=FG, insertcolor=FG, borderwidth=1)
        self.style.map("TEntry", fieldbackground=[("readonly", LIST_BG)])

        self.style.configure("TSpinbox", fieldbackground=LIST_BG, foreground=FG, arrowcolor=FG, borderwidth=1)
        self.style.configure("TCheckbutton", background=BG, foreground=FG)
        self.style.map("TCheckbutton", background=[("active", BG)])
        self.style.configure("TRadiobutton", background=BG, foreground=FG)

        self.style.configure("TNotebook", background=BG, borderwidth=0)
        self.style.configure("TNotebook.Tab", background=CARD_BG, foreground=FG, padding=(12, 6))
        self.style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])

        self.style.configure(
            "Meds.Treeview", background=LIST_BG, fieldbackground=LIST_BG, foreground=FG,
            rowheight=32, borderwidth=0,
        )
        self.style.configure("Meds.Treeview.Heading", background=PANEL_BG, foreground=FG, borderwidth=0)
        self.style.map("Meds.Treeview.Heading", background=[("active", PANEL_BG)])
        self.style.map(
            "Meds.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")]
        )

        self.style.configure(
            "Vertical.TScrollbar", background=PANEL_BG, troughcolor=BG, bordercolor=BG,
            arrowcolor=FG, gripcount=0,
        )
        self.style.configure(
            "Horizontal.TScrollbar", background=PANEL_BG, troughcolor=BG, bordercolor=BG,
            arrowcolor=FG, gripcount=0,
        )

        self.style.configure("TProgressbar", background=ACCENT, troughcolor=CARD_BG, borderwidth=0)

    # ------------------------------------------------------------------
    # Encabezado: paciente + contador de estado + botón de configuración
    # ------------------------------------------------------------------
    def _build_status_counter(self, parent):
        counter_frame = ttk.Frame(parent, style="Panel.TFrame")
        counter_frame.pack(side="left", padx=(4, 0))

        self.counter_vars = {}
        specs = [
            ("ok", COUNTER_COLORS["ok"], "Listos"),
            ("dudoso", COUNTER_COLORS["dudoso"], "Para revisar"),
            ("sin_match", COUNTER_COLORS["sin_match"], "Sin match"),
            ("suspendido", COUNTER_COLORS["suspendido"], "Suspendidos"),
        ]
        for key, color, label_text in specs:
            swatch = tk.Frame(counter_frame, width=12, height=12, bg=color, highlightthickness=1,
                               highlightbackground="#555555")
            swatch.pack(side="left", padx=(10, 3), pady=10)
            swatch.pack_propagate(False)
            Tooltip(swatch, label_text)
            var = tk.StringVar(value="0")
            self.counter_vars[key] = var
            count_label = ttk.Label(counter_frame, textvariable=var, style="Counter.TLabel")
            count_label.pack(side="left")
            Tooltip(count_label, label_text)

    def _build_header(self):
        self.header = ttk.Frame(self.root, style="Panel.TFrame")
        self.header.pack(fill="x")

        self.patient_label = ttk.Label(
            self.header, text="Paciente: (sin capturar)", style="Header.TLabel", padding=(10, 8)
        )
        self.patient_label.pack(side="left")

        self._build_status_counter(self.header)

        gear = ttk.Button(self.header, text="⚙️", command=self.open_settings, style="MiniIcon.TButton", cursor="hand2")
        gear.pack(side="right", padx=8, pady=6)
        Tooltip(gear, "Configuración (sesión AS400, catálogo, coordenadas...)")

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

    # ------------------------------------------------------------------
    # Barra de acciones: los 6 botones principales, grandes y con texto,
    # repartidos a lo ancho de la ventana. Es la única barra de la app.
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        self.toolbar = ttk.Frame(self.root, style="Toolbar.TFrame")
        self.toolbar.pack(fill="x", padx=8, pady=8)
        for i in range(6):
            self.toolbar.columnconfigure(i, weight=1)
        self.toolbar.columnconfigure(6, weight=0)

        def make(col, icon, text, shortcut, command, style="Big.TButton", tooltip=None):
            b = ttk.Button(
                self.toolbar, text=f"{icon}\n{text}\n{shortcut}", command=command, style=style, cursor="hand2"
            )
            b.grid(row=0, column=col, sticky="nsew", padx=4)
            if tooltip:
                Tooltip(b, f"{tooltip} ({shortcut})")
            return b

        make(0, "📥", "Leer", "Ctrl+1", self.leer_nota,
             tooltip="Leer la nota desde AS400")
        make(1, "➕", "Añadir", "Ctrl+2", self.add_new_medication,
             tooltip="Añadir un medicamento manualmente")
        make(2, "▲", "Aumentar", "Ctrl+3", lambda: self._change_qty_selected(1),
             tooltip="Aumentar cantidad del/los seleccionado(s)")
        make(3, "▼", "Disminuir", "Ctrl+4", lambda: self._change_qty_selected(-1),
             tooltip="Disminuir cantidad del/los seleccionado(s)")
        make(4, "🗑️", "Eliminar", "Ctrl+5", self._delete_selected, style="Danger.TButton",
             tooltip="Eliminar el/los medicamento(s) seleccionado(s)")
        make(5, "📤", "Descargar", "Ctrl+6", self.run_descargo_ok_only, style="Accent.TButton",
             tooltip="Descargar SOLO los medicamentos listos en verde")

        remove_btn = ttk.Button(
            self.toolbar,
            text="⚠️\nDescargar\nsacando\npaciente\nCtrl+7",
            command=self.run_descargo_ok_only_removing_patient,
            style="SmallWarn.TButton",
            cursor="hand2",
        )
        remove_btn.grid(row=0, column=6, sticky="ns", padx=(8, 4))
        Tooltip(
            remove_btn,
            "Descargar sacando al paciente del sistema. Úsalo solo si estás seguro/a. (Ctrl+7)",
        )

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

    # ------------------------------------------------------------------
    # Barra de favoritos: chips opcionales debajo de la barra de acciones,
    # uno por cada medicamento guardado con una cantidad fija (ej. "Cloruro
    # de Sodio 0.9% x3"). Clic = lo agrega a la lista con esa cantidad
    # (o suma esa cantidad si ya está en la lista). Clic derecho = quitarlo
    # de favoritos. Se oculta por completo cuando no hay ninguno guardado.
    # ------------------------------------------------------------------
    def _build_favorites_bar(self):
        self.fav_outer = ttk.Frame(self.root, style="Root.TFrame")

        ttk.Label(
            self.fav_outer, text="⭐ Favoritos:", style="Root.TLabel", font=("Segoe UI", 9, "bold")
        ).pack(side="left", padx=(8, 6), pady=4)

        canvas_wrap = tk.Frame(self.fav_outer, bg=BG)
        canvas_wrap.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=(4, 6))

        self.fav_canvas = tk.Canvas(canvas_wrap, bg=BG, highlightthickness=0, height=52)
        fav_scroll = ttk.Scrollbar(canvas_wrap, orient="horizontal", command=self.fav_canvas.xview)
        self.fav_canvas.configure(xscrollcommand=fav_scroll.set)
        self.fav_canvas.pack(side="top", fill="x")
        fav_scroll.pack(side="top", fill="x")

        self.fav_inner = ttk.Frame(self.fav_canvas, style="Root.TFrame")
        self.fav_canvas.create_window((0, 0), window=self.fav_inner, anchor="nw")
        self.fav_inner.bind(
            "<Configure>", lambda e: self.fav_canvas.configure(scrollregion=self.fav_canvas.bbox("all"))
        )

        def on_wheel(event):
            self.fav_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

        self.fav_canvas.bind("<Enter>", lambda e: self.fav_canvas.bind_all("<MouseWheel>", on_wheel))
        self.fav_canvas.bind("<Leave>", lambda e: self.fav_canvas.unbind_all("<MouseWheel>"))

        self._refresh_favorites_bar()

    def _refresh_favorites_bar(self):
        for child in self.fav_inner.winfo_children():
            child.destroy()

        if not self.bookmarks:
            self.fav_outer.pack_forget()
            return

        for bookmark in self.bookmarks:
            desc = bookmark.get("descripcion") or bookmark.get("codigo") or "?"
            short = desc if len(desc) <= 22 else desc[:21] + "…"
            cantidad = bookmark.get("cantidad", 1)
            chip = ttk.Button(
                self.fav_inner, text=f"⭐ {short}\n×{cantidad}", style="Fav.TButton", cursor="hand2",
                command=lambda b=bookmark: self._add_favorite_to_list(b),
            )
            chip.pack(side="left", padx=3, pady=2)
            chip.bind("<Button-3>", lambda e, b=bookmark: self._remove_favorite(b))
            Tooltip(
                chip,
                f"{desc}\n{bookmark.get('presentacion') or ''}\nClic: agregar ×{cantidad}   "
                "Clic derecho: quitar de favoritos",
            )

        self.fav_outer.pack(fill="x", before=self._body_widget if hasattr(self, "_body_widget") else None)

    def _add_favorite_to_list(self, bookmark: dict):
        codigo = bookmark.get("codigo")
        cantidad = max(1, int(bookmark.get("cantidad", 1) or 1))
        desc = bookmark.get("descripcion") or codigo or "medicamento"

        for r in self.rows:
            if codigo and r.codigo == codigo:
                r.cantidad += cantidad
                self._refresh_list()
                self.set_status(f"{desc}: cantidad aumentada a {r.cantidad} (ya estaba en la lista).")
                return

        fake_med = MedicationLine(raw_line=f"(favorito) {desc}", name="", line_index=None)
        row = MedRow(
            med=fake_med, codigo=codigo, descripcion=bookmark.get("descripcion"),
            presentacion=bookmark.get("presentacion"), status="ok" if codigo else "sin_match",
            cantidad=cantidad,
        )
        self.rows.append(row)
        self._refresh_list()
        self.set_status(f"{desc} añadido desde favoritos (×{cantidad}).")

    def _remove_favorite(self, bookmark: dict):
        desc = bookmark.get("descripcion") or bookmark.get("codigo") or "este favorito"
        if not self._confirm(
            "Quitar de favoritos", f"¿Quitar '{desc}' de favoritos?",
            ok_label="Quitar", cancel_label="Cancelar",
        ):
            return
        self.bookmarks = [b for b in self.bookmarks if b is not bookmark]
        self.config["bookmarks"] = self.bookmarks
        try:
            app_config.save_config(self.config)
        except Exception:
            pass
        self._refresh_favorites_bar()

    def _ask_favorite_quantity(self, descripcion: str, default_qty: int = 1) -> Optional[int]:
        """Diálogo chico para elegir la cantidad con la que se guarda un
        favorito (ej. 3 para 'Cloruro de Sodio x3')."""
        result = {"value": None}

        win = tk.Toplevel(self.root)
        win.title("Agregar a favoritos")
        win.configure(bg=BG)
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        body = ttk.Frame(win, style="Root.TFrame", padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text=f"Cantidad a guardar para:\n{descripcion}", style="Root.TLabel",
            justify="left", wraplength=320,
        ).pack(anchor="w")

        qty_var = tk.IntVar(value=max(1, default_qty))
        ttk.Spinbox(body, from_=1, to=999, textvariable=qty_var, width=6, font=("Segoe UI", 11)).pack(
            anchor="w", pady=(10, 0)
        )

        btn_frame = ttk.Frame(body, style="Root.TFrame")
        btn_frame.pack(fill="x", pady=(16, 0))

        def save():
            result["value"] = max(1, qty_var.get())
            win.destroy()

        ttk.Button(btn_frame, text="Guardar en favoritos", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(btn_frame, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

        win.bind("<Return>", lambda e: save())
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        win.wait_window()
        return result["value"]

    def _add_selected_to_favorites(self):
        sel = self._selected_indices()
        if not sel:
            messagebox.showinfo("Nada seleccionado", "Selecciona un medicamento de la lista.")
            return
        row = self.rows[sel[0]]
        if not row.codigo:
            messagebox.showinfo(
                "Sin asignar", "Este medicamento todavía no tiene un código asignado; búscalo primero."
            )
            return

        cantidad = self._ask_favorite_quantity(row.descripcion or row.codigo, row.cantidad)
        if cantidad is None:
            return

        existing = next((b for b in self.bookmarks if b.get("codigo") == row.codigo), None)
        if existing:
            existing["cantidad"] = cantidad
            existing["descripcion"] = row.descripcion
            existing["presentacion"] = row.presentacion
        else:
            self.bookmarks.append({
                "codigo": row.codigo, "descripcion": row.descripcion,
                "presentacion": row.presentacion, "cantidad": cantidad,
            })
        self.config["bookmarks"] = self.bookmarks
        try:
            app_config.save_config(self.config)
        except Exception:
            pass
        self._refresh_favorites_bar()
        self.set_status(f"{row.descripcion} guardado en favoritos (×{cantidad}).")

    def _build_ui(self):
        self._build_header()
        self._build_toolbar()
        self._build_favorites_bar()

        # --- Cuerpo: lista de medicamentos (izq) + nota completa (der) ---
        body = tk.PanedWindow(self.root, orient="horizontal", sashwidth=4, sashrelief="flat", bd=0, bg=BG)
        body.pack(fill="both", expand=True)
        self._body_widget = body

        left_container = ttk.Frame(body, style="Root.TFrame")
        body.add(left_container, minsize=650)

        columns = ("cant", "medicamento", "detalle", "estado")
        self.tree = ttk.Treeview(
            left_container, columns=columns, show="headings",
            selectmode="extended", style="Meds.Treeview"
        )
        self.tree.heading("cant", text="Cant.")
        self.tree.column("cant", width=55, anchor="center", stretch=False)
        self.tree.heading("medicamento", text="Medicamento")
        self.tree.column("medicamento", width=280, anchor="w")
        self.tree.heading("detalle", text="Presentación")
        self.tree.column("detalle", width=220, anchor="w")
        self.tree.heading("estado", text="Estado")
        self.tree.column("estado", width=100, anchor="center", stretch=False)

        tree_vsb = ttk.Scrollbar(left_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_vsb.pack(side="right", fill="y")

        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(status, background=color, foreground=STATUS_FG.get(status, FG))

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Delete>", lambda e: self._delete_selected())
        self.tree.bind("<Button-3>", self._show_row_context_menu)
        self.tree.bind("<Control-a>", self._on_select_all_shortcut)
        self.tree.bind("<Command-a>", self._on_select_all_shortcut)
        self.tree.bind("<plus>", lambda e: self._change_qty_selected(1))
        self.tree.bind("<minus>", lambda e: self._change_qty_selected(-1))
        self.tree.bind("<Up>", lambda e: self._move_tree_selection(-1) or "break")
        self.tree.bind("<Down>", lambda e: self._move_tree_selection(1) or "break")
        self.tree.bind("<Home>", lambda e: self._move_tree_selection_to(0) or "break")
        self.tree.bind("<End>", lambda e: self._move_tree_selection_to(-1) or "break")
        self.tree.bind("<Right>", lambda e: self._change_qty_selected(1) or "break")
        self.tree.bind("<Left>", lambda e: self._change_qty_selected(-1) or "break")
        self.tree.bind("<Return>", lambda e: self._search_selected() or "break")
        self.tree.focus_set()

        self._row_menu = tk.Menu(
            self.tree, tearoff=0, bg=CARD_BG, fg=FG,
            activebackground=ACCENT, activeforeground="#ffffff", bd=0,
        )
        self._row_menu.add_command(label="🔍 Buscar / reasignar", command=self._search_selected)
        self._row_menu.add_command(label="▲ Aumentar cantidad", command=lambda: self._change_qty_selected(1))
        self._row_menu.add_command(label="▼ Disminuir cantidad", command=lambda: self._change_qty_selected(-1))
        self._row_menu.add_separator()
        self._row_menu.add_command(label="⛔ Marcar/quitar como agotado", command=self._toggle_agotado_selected)
        self._row_menu.add_separator()
        self._row_menu.add_command(label="⭐ Agregar a favoritos...", command=self._add_selected_to_favorites)
        self._row_menu.add_separator()
        self._row_menu.add_command(label="🗑️ Eliminar", command=self._delete_selected)

        # Panel derecho: nota completa
        self.right_container = ttk.Frame(body, style="Root.TFrame")
        body.add(self.right_container, minsize=400)

        self.note_label = ttk.Label(self.right_container, text="Nota del día", style="Header.TLabel", font=("Segoe UI", 10, "bold"))
        self.note_label.pack(anchor="w", padx=6, pady=(6, 0))
        self.note_text = tk.Text(
            self.right_container, bg=NOTE_BG, fg=NOTE_FG, insertbackground=NOTE_FG, relief="flat", bd=0,
            font=("Consolas", self.note_font_size), wrap="none", highlightthickness=0,
        )
        self.note_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.note_text.tag_configure("highlight", background=HIGHLIGHT_BG, foreground=HIGHLIGHT_FG)
        self.note_text.config(state="disabled")

        # --- Barra de estado + progreso ---
        ttk.Separator(self.root, orient="horizontal").pack(fill="x")
        self.status_frame = ttk.Frame(self.root, style="Panel.TFrame")
        self.status_frame.pack(fill="x")

        self.status_label = ttk.Label(self.status_frame, text="Listo.", padding=6, style="Status.TLabel")
        self.status_label.pack(side="left", fill="x", expand=True)

        self.progress = ttk.Progressbar(self.status_frame, orient="horizontal", mode="determinate", length=220)
        self.progress.pack(side="right", padx=8, pady=4)

        self._refresh_list()

    # ------------------------------------------------------------------
    def set_status(self, text: str):
        self.status_label.config(text=text)
        self.root.update_idletasks()

    # ------------------------------------------------------------------
    # Barra de progreso
    # ------------------------------------------------------------------
    def _progress_start_indeterminate(self):
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.root.update_idletasks()

    def _progress_set_determinate(self, maximum: int):
        self.progress.stop()
        self.progress.config(mode="determinate", maximum=max(1, maximum), value=0)
        self.root.update_idletasks()

    def _progress_step(self, value: int):
        self.progress["value"] = value
        self.root.update_idletasks()

    def _progress_stop(self):
        self.progress.stop()
        self.progress.config(mode="determinate", value=0, maximum=1)
        self.root.update_idletasks()

    # ------------------------------------------------------------------
    # Atajos de teclado globales. Se usan combinaciones Ctrl+<número> a
    # propósito: Tk trae de fábrica atajos con letras (Ctrl+A/E/etc.)
    # dentro de cualquier campo de texto, así que reusarlas a nivel de
    # programa completo pisaría la edición normal de texto en los cuadros
    # de búsqueda. Los números no tienen ese conflicto.
    # ------------------------------------------------------------------
    def _setup_global_shortcuts(self):
        bindings = {
            "<Control-Key-1>": lambda e: self.leer_nota(),
            "<Control-Key-2>": lambda e: self.add_new_medication(),
            "<Control-Key-3>": lambda e: self._change_qty_selected(1),
            "<Control-Key-4>": lambda e: self._change_qty_selected(-1),
            "<Control-Key-5>": lambda e: self._delete_selected(),
            "<Control-Key-6>": lambda e: self.run_descargo_ok_only(),
            "<Control-Key-7>": lambda e: self.run_descargo_ok_only_removing_patient(),
            "<Control-Shift-Key-F>": lambda e: self._search_selected(),
        }
        # En macOS se aceptan también equivalentes con Command; Control se
        # conserva para no cambiar hábitos ni romper configuraciones previas.
        if os.sys.platform == "darwin":
            bindings.update({
                "<Command-Key-1>": lambda e: self.leer_nota(),
                "<Command-Key-2>": lambda e: self.add_new_medication(),
                "<Command-Key-3>": lambda e: self._change_qty_selected(1),
                "<Command-Key-4>": lambda e: self._change_qty_selected(-1),
                "<Command-Key-5>": lambda e: self._delete_selected(),
                "<Command-Key-6>": lambda e: self.run_descargo_ok_only(),
                "<Command-Key-7>": lambda e: self.run_descargo_ok_only_removing_patient(),
                "<Command-Shift-Key-F>": lambda e: self._search_selected(),
            })
        for keyseq, handler in bindings.items():
            self.root.bind_all(keyseq, handler)

    # ------------------------------------------------------------------
    # Leer / capturar la nota desde AS400
    # ------------------------------------------------------------------
    def leer_nota(self):
        """Antes de capturar, confirma que la sesión de AS400 ya está
        posicionada dentro de la nota que se quiere descargar (si no lo
        está, la captura leería la pantalla equivocada)."""
        if not self._require_valid_license():
            return
        if not self._confirm(
            "Confirmar antes de leer",
            "¿Ya te encuentras dentro de la nota que quieres descargar en AS400?",
            ok_label="Sí, ya estoy en la nota",
            cancel_label="Todavía no",
        ):
            return
        self.capture_from_hod()

    def capture_from_hod(self):
        """Captura en un hilo para que la ventana no quede como 'No responde' mientras ACS trabaja."""
        self.set_status("Conectando a HOD/AS400...")
        self._progress_start_indeterminate()

        if self.controller is not None:
            try:
                self.controller.close()
            except Exception:
                pass
            self.controller = None

        params = dict(
            session_name=self.session_name,
            timeout_seconds=self.timeout_seconds,
            screen_coords=self.config.get("screen_coords"),
            acs_window_title_contains=self.acs_window_title_contains,
            acs_read_hotkey_key=self.acs_read_hotkey_key,
            acs_exec_hotkey_key=self.acs_exec_hotkey_key,
            acs_confirm_hotkey_key=self.acs_confirm_hotkey_key,
            acs_macro_hotkey_modifiers=self.acs_macro_hotkey_modifiers,
            macro_timeout_seconds=self.macro_timeout_seconds,
        )
        self.set_status("Buscando la sesión 5250 y ejecutando DescargoLeer_HOD1108...")

        def finish_ok(controller, text, patient):
            self.controller = controller
            self.patient_label.config(text=f"Paciente: {patient}")
            self._process_note_text(text)
            self._progress_stop()

        def finish_error(message):
            self._progress_stop()
            messagebox.showerror("Error de conexión a AS400", message)
            self.set_status("Error al capturar la nota.")

        def worker():
            try:
                controller = HODController(**params)
                text = controller.capture_note_text()
                patient = controller.get_patient_name()
                self.root.after(0, lambda: finish_ok(controller, text, patient))
            except Exception as exc:
                msg = str(exc)
                self.root.after(0, lambda m=msg: finish_error(m))

        threading.Thread(target=worker, name="HOD-READ", daemon=True).start()

    def _process_note_text(self, text: str):
        self.full_note_text = text
        self.note_text.config(state="normal")
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", text)
        self.note_text.config(state="disabled")

        med_lines = parse_note(text)
        self.rows = []
        for med in med_lines:
            row = MedRow(med=med, cantidad=med.doses_per_day or 1)
            if med.suspended:
                row.status = "suspendido"
            else:
                exact_key = normalize_prescription_key(med.raw_line)
                remembered = self.exact_matches.get(exact_key)
                if remembered:
                    # Ya se descargó esta misma línea de prescripción antes
                    # y el usuario confirmó a qué medicamento correspondía:
                    # se usa directo, sin pasar por la búsqueda por nombre
                    # ni por el desempate de candidatos.
                    row.codigo = remembered.get("codigo")
                    row.descripcion = remembered.get("descripcion")
                    row.presentacion = remembered.get("presentacion")
                    row.status = "ok"
                else:
                    candidates, name_match_type = candidates_by_name(self.catalog, med.name)
                    result = match_medication(med, candidates)
                    if result.confidence == "alta":
                        row.codigo = result.row.codigo
                        row.descripcion = result.row.descripcion
                        row.presentacion = result.row.presentacion
                        if name_match_type == "exacta":
                            row.status = "ok"
                        else:
                            # El nombre no matcheó exacto (fue por "contiene" o difusa):
                            # aunque el resto del matching haya quedado único, es un
                            # resultado dudoso que conviene confirmar manualmente.
                            row.status = "ambiguo"
                    elif med.needs_manual_review:
                        row.status = "manual_review"
                    else:
                        row.status = "ambiguo" if result.candidates else "sin_match"
            self.rows.append(row)
        self._refresh_list()
        self.set_status(f"{len(self.rows)} medicamentos detectados.")

    # ------------------------------------------------------------------
    def _update_counter(self):
        counts = {"ok": 0, "dudoso": 0, "sin_match": 0, "suspendido": 0}
        for r in self.rows:
            if r.status == "ok":
                counts["ok"] += 1
            elif r.status in ("ambiguo", "manual_review"):
                counts["dudoso"] += 1
            elif r.status == "suspendido":
                counts["suspendido"] += 1
            else:
                counts["sin_match"] += 1
        for key, var in self.counter_vars.items():
            var.set(str(counts[key]))

    # ------------------------------------------------------------------
    # Lista de medicamentos (ttk.Treeview)
    # ------------------------------------------------------------------
    def _refresh_list(self, preserve_selection=True):
        selected_before = set(self.tree.selection()) if preserve_selection else set()

        self._suppress_select_event = True
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(self.rows):
            iid = str(idx)
            desc = row.descripcion or f"(sin resolver) {row.med.raw_line.strip()[:60]}"
            if self._is_codigo_agotado(row.codigo):
                desc = f"⛔ {desc}"  # marca permanente: institución sin stock de este código
            presentacion = row.presentacion or ""
            estado = STATUS_LABELS.get(row.status, row.status)
            self.tree.insert(
                "", "end", iid=iid,
                values=(row.cantidad, desc, presentacion, estado),
                tags=(row.status,),
            )
        restored = selected_before & set(self.tree.get_children())
        if restored:
            self.tree.selection_set(tuple(restored))
        self._suppress_select_event = False

        self._update_counter()

    def _selected_indices(self) -> List[int]:
        return sorted(int(iid) for iid in self.tree.selection())

    def _move_tree_selection(self, delta: int):
        """Mueve la selección una fila arriba/abajo (flechas), reemplazando
        la selección actual por una sola fila, igual que en el Explorador
        de Windows."""
        children = self.tree.get_children()
        if not children:
            return
        sel = self._selected_indices()
        if sel:
            idx = (sel[-1] if delta > 0 else sel[0]) + delta
        else:
            idx = 0
        idx = min(max(idx, 0), len(children) - 1)
        self._move_tree_selection_to(idx)

    def _move_tree_selection_to(self, index: int):
        children = self.tree.get_children()
        if not children:
            return
        if index < 0:
            index = len(children) - 1
        index = min(max(index, 0), len(children) - 1)
        iid = children[index]
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def _on_tree_select(self, _event=None):
        if self._suppress_select_event:
            return
        sel = self._selected_indices()
        if sel:
            self._highlight_line(sel[-1])

    def _on_tree_double_click(self, event=None):
        iid = self.tree.identify_row(event.y) if event is not None else None
        column = self.tree.identify_column(event.x) if event is not None else None
        if iid and column == "#1":  # columna "Cant."
            self._edit_qty_inline(int(iid))
            return
        sel = self._selected_indices()
        if sel:
            self._open_search_dialog(sel[0])

    def _edit_qty_inline(self, idx: int):
        """Edita la cantidad a mano con doble clic sobre la celda, en vez de
        depender solo de los botones +/-: útil para saltar directo a un
        número específico (ej. 12) sin hacer clic 11 veces."""
        iid = str(idx)
        if iid not in self.tree.get_children():
            return
        bbox = self.tree.bbox(iid, "cant")
        if not bbox:
            return
        x, y, width, height = bbox

        edit_var = tk.StringVar(value=str(self.rows[idx].cantidad))
        editor = ttk.Entry(self.tree, textvariable=edit_var, justify="center", font=("Segoe UI", 10))
        editor.place(x=x, y=y, width=width, height=height)
        editor.select_range(0, "end")
        editor.focus_set()

        def commit(_event=None):
            value = edit_var.get().strip()
            try:
                cantidad = max(1, int(value))
            except ValueError:
                cantidad = self.rows[idx].cantidad  # valor inválido: no se cambia
            self.rows[idx].cantidad = cantidad
            editor.destroy()
            self._refresh_list()

        def cancel(_event=None):
            editor.destroy()

        editor.bind("<Return>", commit)
        editor.bind("<KP_Enter>", commit)
        editor.bind("<Escape>", cancel)
        editor.bind("<FocusOut>", commit)

    def _show_row_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        if self.tree.selection():
            self._row_menu.tk_popup(event.x_root, event.y_root)

    def _highlight_line(self, idx: int):
        self.note_text.config(state="normal")
        self.note_text.tag_remove("highlight", "1.0", "end")
        line_index = self.rows[idx].med.line_index
        if line_index is not None:
            line_num = line_index + 1  # Tkinter Text usa líneas 1-based
            self.note_text.tag_add("highlight", f"{line_num}.0", f"{line_num}.end")
            self.note_text.see(f"{line_num}.0")
        self.note_text.config(state="disabled")

    # ------------------------------------------------------------------
    # Selección múltiple (nativa del Treeview: clic, Ctrl+clic, Shift+clic
    # o Ctrl+A, igual que en el Explorador de Windows)
    # ------------------------------------------------------------------
    def _on_select_all_shortcut(self, _event=None):
        self._toggle_select_all(force_select=True)
        return "break"

    def _toggle_select_all(self, force_select=False):
        if not self.rows:
            return
        all_iids = self.tree.get_children()
        if force_select or len(self.tree.selection()) < len(all_iids):
            self.tree.selection_set(all_iids)
        else:
            self.tree.selection_remove(all_iids)

    def _change_qty_selected(self, delta: int):
        sel = self._selected_indices()
        if not sel:
            messagebox.showinfo("Nada seleccionado", "Selecciona uno o más medicamentos de la lista.")
            return
        for i in sel:
            self.rows[i].cantidad = max(1, self.rows[i].cantidad + delta)
        self._refresh_list()

    def _search_selected(self):
        sel = self._selected_indices()
        if not sel:
            messagebox.showinfo("Nada seleccionado", "Selecciona un medicamento de la lista.")
            return
        self._open_search_dialog(sel[0])

    def _delete_selected(self):
        sel = self._selected_indices()
        if not sel:
            messagebox.showinfo("Nada seleccionado", "No hay medicamentos seleccionados.")
            return
        if not self._confirm(
            "Eliminar seleccionados", f"¿Eliminar {len(sel)} medicamento(s) seleccionados?",
            ok_label=f"Eliminar {len(sel)}", cancel_label="No eliminar",
        ):
            return
        sel_set = set(sel)
        self.rows = [r for i, r in enumerate(self.rows) if i not in sel_set]
        self._refresh_list(preserve_selection=False)
        self.set_status(f"{len(sel)} medicamento(s) eliminado(s).")

    # ------------------------------------------------------------------
    def add_new_medication(self):
        """Agrega una fila vacía para un medicamento que no vino de la nota (búsqueda manual)."""
        fake_med = MedicationLine(raw_line="(agregado manualmente)", name="", line_index=None)
        self.rows.append(MedRow(med=fake_med, status="sin_match"))
        self._refresh_list()
        self._open_search_dialog(len(self.rows) - 1)

    # ------------------------------------------------------------------
    # Búsqueda en catálogo por "mayor coincidencia": delega en la misma
    # función que usa el matching automático (catalog.search_catalog).
    def _catalog_search(self, query: str, limit: int = 150) -> List[CatalogRow]:
        return search_catalog(self.catalog, query, limit=limit)

    def _save_name_synonym(self, original_name: str, chosen: CatalogRow):
        """Guarda `original_name` -> (primera palabra de la descripción elegida)
        en el diccionario de sinónimos persistente, para que la próxima nota
        que traiga ese mismo nombre (typo, abreviatura, nombre de casa) se
        resuelva sola sin pasar por la búsqueda manual otra vez."""
        canon = (chosen.descripcion or "").split()
        if not canon:
            return
        key = original_name.strip().upper()
        value = canon[0]
        if not key or key == value:
            return
        synonyms = self.config.setdefault("name_synonyms", {})
        synonyms[key] = value
        try:
            app_config.save_config(self.config)
        except Exception:
            pass
        set_name_synonyms(synonyms)

    def _save_exact_match(self, raw_line: str, chosen: CatalogRow):
        """Guarda en el registro personal `exact_matches` la línea de
        prescripción completa (normalizada) -> el medicamento exacto
        elegido, para que la próxima vez que llegue una nota con esa MISMA
        línea se descargue directo ese medicamento."""
        key = normalize_prescription_key(raw_line)
        if not key:
            return
        self.exact_matches[key] = {
            "codigo": chosen.codigo,
            "descripcion": chosen.descripcion,
            "presentacion": chosen.presentacion,
        }
        self.config["exact_matches"] = self.exact_matches
        try:
            app_config.save_config(self.config)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Medicamentos agotados: marca permanente por código, descubierta en
    # tiempo real al ejecutar un descargo (AS400 avisa "está agotado" tras
    # seleccionar el medicamento).
    # ------------------------------------------------------------------
    def _is_codigo_agotado(self, codigo: Optional[str]) -> bool:
        if not codigo:
            return False
        return codigo in self.config.get("out_of_stock_codes", {})

    def _mark_codigo_agotado(self, codigo: str, descripcion: str = ""):
        if not codigo or self._is_codigo_agotado(codigo):
            return
        out_of_stock = self.config.setdefault("out_of_stock_codes", {})
        out_of_stock[codigo] = descripcion or out_of_stock.get(codigo, "")
        try:
            app_config.save_config(self.config)
        except Exception:
            pass
        self._refresh_list()

    def _unmark_codigo_agotado(self, codigo: str):
        out_of_stock = self.config.get("out_of_stock_codes", {})
        if codigo not in out_of_stock:
            return
        del out_of_stock[codigo]
        try:
            app_config.save_config(self.config)
        except Exception:
            pass
        self._refresh_list()

    def _toggle_agotado_selected(self):
        sel = self._selected_indices()
        rows = [self.rows[i] for i in sel if self.rows[i].codigo]
        if not rows:
            messagebox.showinfo("Nada seleccionado", "Selecciona un medicamento con código asignado.")
            return
        any_marked = any(self._is_codigo_agotado(r.codigo) for r in rows)
        for r in rows:
            if any_marked:
                self._unmark_codigo_agotado(r.codigo)
            else:
                self._mark_codigo_agotado(r.codigo, r.descripcion or "")

    # ------------------------------------------------------------------
    # Ventana de búsqueda/reasignación de un medicamento
    # ------------------------------------------------------------------
    def _open_search_dialog(self, idx: int, anchor_widget=None):
        row = self.rows[idx]

        if self._search_popup is not None:
            try:
                self._search_popup.destroy()
            except Exception:
                pass
            self._search_popup = None

        popup = tk.Toplevel(self.root)
        self._search_popup = popup
        popup.wm_overrideredirect(True)
        popup.configure(bg=BORDER, bd=1, relief="solid")

        if anchor_widget is not None:
            x = anchor_widget.winfo_rootx()
            y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height() + 2
        else:
            x = self.tree.winfo_rootx() + 40
            y = self.tree.winfo_rooty() + 40
        popup.wm_geometry(f"860x520+{x}+{y}")

        inner = tk.Frame(popup, bg=LIST_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        placeholder_line = "(agregado manualmente)"
        original_name = (row.med.name or "").strip()
        has_real_line = bool(row.med.raw_line) and row.med.raw_line.strip() not in ("", placeholder_line)
        seed_text = row.med.raw_line.strip() if has_real_line else original_name
        search_var = tk.StringVar(value=seed_text)
        entry = ttk.Entry(inner, textvariable=search_var, font=("Segoe UI", 12))
        entry.pack(fill="x", padx=6, pady=6)
        entry.focus()
        entry.icursor("end")

        list_frame = tk.Frame(inner, bg=LIST_BG)
        list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        results_list = tk.Listbox(
            list_frame, font=("Consolas", 11), bg=LIST_BG, fg=FG,
            selectbackground=ACCENT, selectforeground="#ffffff", highlightthickness=0, bd=0,
        )
        h_scroll = ttk.Scrollbar(list_frame, orient="horizontal", command=results_list.xview)
        v_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=results_list.yview)
        results_list.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        results_list.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        save_synonym_var = tk.BooleanVar(value=bool(original_name or has_real_line))
        if original_name and has_real_line:
            checkbox_text = f"Recordar '{original_name}' (nombre + línea exacta) para la próxima vez"
        elif has_real_line:
            checkbox_text = "Recordar esta línea exacta para la próxima vez"
        else:
            checkbox_text = f"Recordar '{original_name}' como sinónimo para la próxima vez" if original_name \
                else "Recordar este nombre como sinónimo para la próxima vez"
        synonym_check = ttk.Checkbutton(inner, variable=save_synonym_var, text=checkbox_text)
        if original_name or has_real_line:
            synonym_check.pack(anchor="w", padx=6, pady=(0, 6))

        def do_search(*_):
            results_list.delete(0, "end")
            matches = self._catalog_search(search_var.get())
            for c in matches:
                results_list.insert("end", f"{c.codigo:8s} | {c.descripcion:30s} | {c.presentacion}")
            results_list._matches = matches

        search_var.trace_add("write", do_search)
        do_search()

        def select_row(_event=None):
            sel = results_list.curselection()
            if not sel:
                return
            chosen: CatalogRow = results_list._matches[sel[0]]
            row.codigo = chosen.codigo
            row.descripcion = chosen.descripcion
            row.presentacion = chosen.presentacion
            row.status = "ok"
            if save_synonym_var.get():
                if original_name:
                    self._save_name_synonym(original_name, chosen)
                if has_real_line:
                    self._save_exact_match(row.med.raw_line, chosen)
            popup.destroy()
            self._search_popup = None
            self._refresh_list()

        def close_popup(_event=None):
            popup.destroy()
            self._search_popup = None

        results_list.bind("<Double-1>", select_row)
        results_list.bind("<Return>", select_row)
        entry.bind("<Return>", lambda e: select_row() if results_list.size() == 1 else None)
        entry.bind("<Down>", lambda e: results_list.focus_set() or results_list.selection_set(0))
        popup.bind("<Escape>", close_popup)
        popup.bind("<FocusOut>", lambda e: popup.after(150, lambda: close_popup() if popup.focus_get() is None else None))

    # ------------------------------------------------------------------
    def _merge_duplicate_rows(self, rows: List[MedRow]):
        """Combina en una sola línea los medicamentos repetidos (mismo
        código), sumando su cantidad. No modifica self.rows."""
        merged_by_codigo = {}
        result = []
        for r in rows:
            if not r.codigo:
                result.append(r)
                continue
            existing = merged_by_codigo.get(r.codigo)
            if existing is None:
                new_row = replace(r)
                merged_by_codigo[r.codigo] = new_row
                result.append(new_row)
            else:
                existing.cantidad += r.cantidad
        return result

    def _delete_duplicate_rows(self, rows: List[MedRow]):
        """Elimina los medicamentos repetidos (mismo código), dejando solo
        la primera aparición de cada uno tal cual estaba. No modifica self.rows."""
        seen = set()
        result = []
        for r in rows:
            if r.codigo:
                if r.codigo in seen:
                    continue
                seen.add(r.codigo)
            result.append(r)
        return result

    def _confirm(self, title: str, message: str, ok_label: str, cancel_label: str = "Cancelar") -> bool:
        """Confirmación de dos botones cuyo texto describe la acción en vez
        de un genérico 'Sí/No' (ej. 'Sí, ya estoy en la nota' / 'Todavía no')."""
        choice = self._ask_choice_dialog(title, message, [ok_label, cancel_label])
        return choice == 0

    def _ask_choice_dialog(self, title: str, message: str, options: List[str]) -> Optional[int]:
        """Diálogo modal con un botón por cada opción de `options` (el texto
        del botón ES la opción, nada de 'Sí/No/Cancelar' genéricos). Devuelve
        el índice de la opción elegida, o None si se cerró sin elegir."""
        result = {"choice": None}

        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=BG)
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        body = ttk.Frame(win, style="Root.TFrame", padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text=message, style="Root.TLabel", justify="left", wraplength=440
        ).pack(anchor="w")

        btn_frame = ttk.Frame(body, style="Root.TFrame")
        btn_frame.pack(fill="x", pady=(16, 0))

        def choose(i):
            result["choice"] = i
            win.destroy()

        buttons = []

        # Última opción (normalmente "Cancelar") queda a la izquierda y
        # visualmente separada; el resto en orden, alineadas a la derecha.
        for i, label in enumerate(options):
            style = "TButton"
            if i == 0:
                style = "Accent.TButton"
            b = ttk.Button(btn_frame, text=label, style=style, command=lambda i=i: choose(i))
            b.pack(side="left" if i == len(options) - 1 else "right", padx=4)
            buttons.append(b)

        def focused_index() -> int:
            focused = win.focus_get()
            return buttons.index(focused) if focused in buttons else 0

        # Los botones se empaquetan con el primario a la derecha y el resto
        # hacia la izquierda (ver bucle de arriba), así que el orden visual
        # izquierda->derecha es el inverso del orden de `options`.
        visual_order = list(range(len(options) - 1, -1, -1))

        def move_focus(delta):
            pos = visual_order.index(focused_index())
            new_pos = (pos + delta) % len(visual_order)
            buttons[visual_order[new_pos]].focus_set()
            return "break"

        def activate_focused(_event=None):
            choose(focused_index())
            return "break"

        for b in buttons:
            b.bind("<Return>", activate_focused)
            b.bind("<KP_Enter>", activate_focused)
            b.bind("<Left>", lambda e: move_focus(-1))
            b.bind("<Right>", lambda e: move_focus(1))
            b.bind("<Up>", lambda e: move_focus(-1))
            b.bind("<Down>", lambda e: move_focus(1))

        buttons[0].focus_set()

        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x,0)}+{max(y,0)}")

        win.wait_window()
        return result["choice"]

    def _resolve_duplicates_for_descargo(self, rows: List[MedRow]):
        """
        Detecta medicamentos repetidos (mismo código) en `rows` y, si hay,
        le pregunta al usuario cómo resolverlos antes de descargar.
        Devuelve (rows_resueltas, continuar).
        """
        counts = {}
        for r in rows:
            if r.codigo:
                counts.setdefault(r.codigo, []).append(r)
        duplicated = {c: rs for c, rs in counts.items() if len(rs) > 1}
        if not duplicated:
            return rows, True

        detalle = "\n".join(
            f"- {rs[0].descripcion or codigo}  (x{len(rs)}, cantidades: {', '.join(str(r.cantidad) for r in rs)})"
            for codigo, rs in duplicated.items()
        )
        choice = self._ask_choice_dialog(
            "Medicamentos repetidos",
            f"Este descargo tiene medicamentos repetidos (mismo código):\n\n{detalle}\n\n"
            "¿Cómo quieres resolverlos?",
            ["Unir (sumar cantidades)", "Preservar solamente uno", "Cancelar"],
        )
        if choice is None or choice == 2:
            return rows, False
        if choice == 0:
            return self._merge_duplicate_rows(rows), True
        return self._delete_duplicate_rows(rows), True

    def _build_order_fields(self, rows: List[MedRow]) -> List[OrderFields]:
        """Arma los campos a enviar a AS400. Solo la cantidad final (editada
        por el usuario en la lista) importa; frecuencia y duración quedan
        fijas en "qd" / "1" / "d", y la vía se selecciona en pantalla con
        [pf4] -> "1" -> [enter]."""
        fields = []
        for r in rows:
            med = r.med
            cantidad = r.cantidad
            fields.append(
                OrderFields(
                    codigo=r.codigo,
                    cantidad=str(cantidad),
                    dosis=med.dose_value or "1",
                    unidad=(med.dose_unit or "ml").lower(),
                    frecuencia="qd",
                    dura_cantidad="1",
                    dura_unidad="d",
                )
            )
        return fields

    def _execute_descargo(self, rows: List[MedRow], remove_patient: bool = False):
        """Ejecuta el descargo en segundo plano.

        HOD puede tardar varios segundos/minutos. Nunca debe bloquearse el hilo de
        Tkinter esperando el marcador final del macro.
        """
        if not self._require_valid_license():
            return
        if getattr(self, "_descargo_running", False):
            messagebox.showinfo("Descargo en curso", "Ya hay un descargo HOD1108 ejecutándose.")
            return

        rows, should_continue = self._resolve_duplicates_for_descargo(rows)
        if not should_continue:
            return
        if remove_patient:
            if not self._confirm(
                "ATENCIÓN: sacar paciente del sistema",
                "Este modo hará el descargo SACANDO al paciente del sistema médico.\n\n"
                "Úsalo solo si estás completamente seguro/a, porque al continuar el paciente dejará de quedar "
                "activo en ese flujo del sistema antes de iniciar la búsqueda de medicamentos.\n\n"
                f"Se van a descargar {len(rows)} medicamentos con este procedimiento especial.",
                ok_label="Sí, descargar sacando al paciente", cancel_label="Cancelar",
            ):
                return
        else:
            if not self._confirm(
                "Confirmar descargo",
                f"Se va a ejecutar el descargo de {len(rows)} medicamentos en AS400 mediante HOD1108.",
                ok_label=f"Descargar {len(rows)}", cancel_label="Cancelar",
            ):
                return

        self._descargo_running = True
        self._progress_start_indeterminate()
        order_fields = self._build_order_fields(rows)
        params = dict(
            session_name=self.session_name,
            timeout_seconds=self.timeout_seconds,
            screen_coords=self.config.get("screen_coords"),
            acs_window_title_contains=self.acs_window_title_contains,
            acs_read_hotkey_key=self.acs_read_hotkey_key,
            acs_exec_hotkey_key=self.acs_exec_hotkey_key,
            acs_confirm_hotkey_key=self.acs_confirm_hotkey_key,
            acs_macro_hotkey_modifiers=self.acs_macro_hotkey_modifiers,
            macro_timeout_seconds=self.macro_timeout_seconds,
        )
        self.set_status(
            "Ejecutando macro HOD1108 (sacando al paciente)..." if remove_patient
            else "Ejecutando macro HOD1108 de descargo..."
        )

        def finish_error(message):
            self._descargo_running = False
            self._progress_stop()
            messagebox.showerror("Error durante el descargo", message)
            self.set_status("Error durante el descargo.")

        def finish_ok(controller, agotados):
            self.controller = controller
            self._descargo_running = False
            self._progress_stop()
            newly_agotados = []
            newly_restocked = []
            for f, r in zip(order_fields, rows):
                if f.codigo in agotados:
                    self._mark_codigo_agotado(f.codigo, r.descripcion or "")
                    newly_agotados.append(r.descripcion or f.codigo)
                elif self._is_codigo_agotado(f.codigo):
                    self._unmark_codigo_agotado(f.codigo)
                    newly_restocked.append(r.descripcion or f.codigo)

            self.set_status("Descargo cargado correctamente mediante HOD1108.")
            if newly_agotados:
                lista = "\n".join(f"- {n}" for n in newly_agotados)
                messagebox.showwarning(
                    "Medicamento(s) agotado(s) detectado(s)",
                    "AS400 avisó que estos medicamentos están agotados en la institución "
                    f"(quedaron marcados con ⛔ para la próxima vez):\n\n{lista}"
                )
            if newly_restocked:
                lista = "\n".join(f"- {n}" for n in newly_restocked)
                messagebox.showinfo(
                    "Medicamento(s) con stock de nuevo",
                    "Estos medicamentos estaban marcados como agotados, pero esta vez AS400 "
                    f"no mostró ese aviso, así que se desmarcaron (⛔):\n\n{lista}"
                )

            choice = self._ask_choice_dialog(
                "Confirmar descargo",
                "El descargo ya se cargó en AS400.\n\n"
                "¿Confirmo automáticamente mediante el macro HOD (F24, F3, F11, F3, F3) "
                "o prefieres revisar la pantalla final tú mismo primero?",
                ["Confirmar en AS400", "Revisar manualmente"],
            )
            if choice == 0:
                self._confirm_descargo_natively()
            else:
                self.set_status("Descargo cargado. Pendiente de confirmar manualmente en AS400.")

        def worker():
            try:
                controller = self.controller or HODController(**params)
                agotados = controller.execute_descargo(order_fields, remove_patient=remove_patient)
                self.root.after(0, lambda c=controller, a=agotados: finish_ok(c, a))
            except Exception as exc:
                msg = str(exc)
                self.root.after(0, lambda m=msg: finish_error(m))

        threading.Thread(target=worker, name="HOD-EXEC", daemon=True).start()

    def _confirm_descargo_natively(self):
        """Confirma en segundo plano mediante DescargoConfirmar_HOD1108."""
        if getattr(self, "_confirm_running", False):
            return
        self._confirm_running = True
        self._progress_start_indeterminate()
        self.set_status("Confirmando descargo mediante HOD1108 (F24, F3, F11, F3, F3)...")
        params = dict(
            session_name=self.session_name,
            timeout_seconds=self.timeout_seconds,
            screen_coords=self.config.get("screen_coords"),
            acs_window_title_contains=self.acs_window_title_contains,
            acs_read_hotkey_key=self.acs_read_hotkey_key,
            acs_exec_hotkey_key=self.acs_exec_hotkey_key,
            acs_confirm_hotkey_key=self.acs_confirm_hotkey_key,
            acs_macro_hotkey_modifiers=self.acs_macro_hotkey_modifiers,
            macro_timeout_seconds=self.macro_timeout_seconds,
        )

        def ok(controller):
            self.controller = controller
            self._confirm_running = False
            self._progress_stop()
            self.set_status("Descargo confirmado en AS400.")

        def error(message):
            self._confirm_running = False
            self._progress_stop()
            messagebox.showerror("Error al confirmar en AS400", message)
            self.set_status("Error al confirmar el descargo en AS400.")

        def worker():
            try:
                controller = self.controller or HODController(**params)
                controller.confirm_descargo()
                self.root.after(0, lambda c=controller: ok(c))
            except Exception as exc:
                msg = str(exc)
                self.root.after(0, lambda m=msg: error(m))

        threading.Thread(target=worker, name="HOD-CONFIRM", daemon=True).start()

    def run_descargo_ok_only(self):
        """Descarga SIEMPRE solo los medicamentos listos (verde), sin
        importar qué esté seleccionado en la lista en ese momento."""
        ok_rows = [r for r in self.rows if r.status == "ok" and r.codigo]
        if not ok_rows:
            messagebox.showinfo("Nada para descargar", "No hay medicamentos marcados como listos (verde).")
            return
        self._execute_descargo(ok_rows)

    def run_descargo_ok_only_removing_patient(self):
        """Descarga solo los medicamentos listos, pero usando la secuencia
        especial que saca al paciente del sistema antes de entrar al flujo
        de descargos."""
        ok_rows = [r for r in self.rows if r.status == "ok" and r.codigo]
        if not ok_rows:
            messagebox.showinfo("Nada para descargar", "No hay medicamentos marcados como listos (verde).")
            return
        self._execute_descargo(ok_rows, remove_patient=True)

    # ------------------------------------------------------------------
    # Ventana de configuración
    # ------------------------------------------------------------------
    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Configuración")
        win.geometry("620x560")
        win.configure(bg=BG)
        win.transient(self.root)
        win.grab_set()

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # ---------------- Tab Conexión ----------------
        tab_conn = ttk.Frame(notebook, style="Root.TFrame")
        notebook.add(tab_conn, text="Conexión ACS/HOD")

        ttk.Label(tab_conn, text="Título de ventana ACS contiene:", style="Root.TLabel").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        acs_title_var = tk.StringVar(value=self.acs_window_title_contains)
        ttk.Entry(tab_conn, textvariable=acs_title_var, width=28).grid(row=0, column=1, padx=8, pady=8, sticky="w")

        def detect_acs_windows():
            if os.name != "nt":
                messagebox.showinfo("Detectar ventana ACS", "Este botón de detección automática es para la prueba en Windows.")
                return
            try:
                items = HODController.windows_debug_titles()
            except Exception as e:
                messagebox.showerror("Detectar ventana ACS", str(e))
                return
            # Ocultar la propia app; dejamos el lanzador visible solo como referencia,
            # pero lo marcamos para que no se seleccione por accidente.
            clean = []
            for item in items:
                low = item.lower()
                if "descargo de medicación" in low or "descargo de medicacion" in low:
                    continue
                clean.append(item)
            pick = tk.Toplevel(win)
            pick.title("Ventanas visibles de Windows")
            pick.geometry("760x360")
            pick.transient(win)
            lb = tk.Listbox(pick, font=("Consolas", 9))
            lb.pack(fill="both", expand=True, padx=10, pady=10)
            for item in clean:
                lb.insert("end", item)
            ttk.Label(
                pick,
                text="Selecciona la ventana de la SESIÓN 5250 (la terminal), NO 'IBM i Access Client Solutions' a secas.",
                wraplength=720, justify="left",
            ).pack(anchor="w", padx=10, pady=(0, 6))

            def use_selected():
                sel = lb.curselection()
                if not sel:
                    return
                raw = clean[sel[0]]
                title = raw.split("    [clase=", 1)[0].strip()
                if title.casefold() == "ibm i access client solutions":
                    messagebox.showwarning(
                        "Esa no es la sesión",
                        "Esa ventana es el lanzador general de ACS. Selecciona la ventana donde ves la pantalla 5250."
                    )
                    return
                acs_title_var.set(title)
                pick.destroy()

            ttk.Button(pick, text="Usar esta ventana", command=use_selected).pack(pady=(0, 10))

        ttk.Button(tab_conn, text="Detectar...", command=detect_acs_windows).grid(row=0, column=2, padx=4)

        ttk.Label(tab_conn, text="Tecla macro LEER:", style="Root.TLabel").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        acs_read_key_var = tk.StringVar(value=self.acs_read_hotkey_key)
        ttk.Entry(tab_conn, textvariable=acs_read_key_var, width=8).grid(row=1, column=1, padx=8, pady=8, sticky="w")

        ttk.Label(tab_conn, text="Tecla macro DESCARGAR:", style="Root.TLabel").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        acs_exec_key_var = tk.StringVar(value=self.acs_exec_hotkey_key)
        ttk.Entry(tab_conn, textvariable=acs_exec_key_var, width=8).grid(row=2, column=1, padx=8, pady=8, sticky="w")

        ttk.Label(tab_conn, text="Tecla macro CONFIRMAR:", style="Root.TLabel").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        acs_confirm_key_var = tk.StringVar(value=self.acs_confirm_hotkey_key)
        ttk.Entry(tab_conn, textvariable=acs_confirm_key_var, width=8).grid(row=3, column=1, padx=8, pady=8, sticky="w")

        ttk.Label(tab_conn, text="Modificadores comunes:", style="Root.TLabel").grid(row=4, column=0, sticky="w", padx=8, pady=8)
        acs_mods_var = tk.StringVar(value=self.acs_macro_hotkey_modifiers if isinstance(self.acs_macro_hotkey_modifiers, str) else ",".join(self.acs_macro_hotkey_modifiers))
        ttk.Entry(tab_conn, textvariable=acs_mods_var, width=28).grid(row=4, column=1, padx=8, pady=8, sticky="w")

        ttk.Label(
            tab_conn,
            text="En ACS asigna directamente: Leer = Ctrl+Shift+L, Descargar = Ctrl+Shift+E, "
                 "Confirmar = Ctrl+Shift+C. Esta versión NO usa Dispatcher ni macros encadenados.",
            style="Root.TLabel", wraplength=500, justify="left",
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        ttk.Label(tab_conn, text="Catálogo (CSV) por defecto:", style="Root.TLabel").grid(row=6, column=0, sticky="w", padx=8, pady=8)
        catalog_var = tk.StringVar(value=self.catalog_path)
        ttk.Entry(tab_conn, textvariable=catalog_var, width=28).grid(row=6, column=1, padx=8, pady=8, sticky="w")

        def browse_catalog():
            path = filedialog.askopenfilename(title="Elegir catálogo CSV", filetypes=[("CSV", "*.csv"), ("Todos", "*.*")])
            if path:
                catalog_var.set(path)

        ttk.Button(tab_conn, text="Examinar...", command=browse_catalog).grid(row=6, column=2, padx=4)

        ttk.Label(tab_conn, text="Timeout corto HOD (segundos):", style="Root.TLabel").grid(row=7, column=0, sticky="w", padx=8, pady=8)
        timeout_var = tk.IntVar(value=self.timeout_seconds)
        ttk.Spinbox(tab_conn, from_=5, to=120, textvariable=timeout_var, width=6).grid(row=7, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(tab_conn, text="Timeout macro completo (segundos):", style="Root.TLabel").grid(row=8, column=0, sticky="w", padx=8, pady=8)
        macro_timeout_var = tk.IntVar(value=self.macro_timeout_seconds)
        ttk.Spinbox(tab_conn, from_=60, to=1800, increment=30, textvariable=macro_timeout_var, width=8).grid(row=8, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(tab_conn, text="Tamaño de fuente del panel de nota:", style="Root.TLabel").grid(row=9, column=0, sticky="w", padx=8, pady=8)
        font_size_var = tk.IntVar(value=self.note_font_size)
        ttk.Spinbox(tab_conn, from_=8, to=20, textvariable=font_size_var, width=6).grid(row=9, column=1, sticky="w", padx=8, pady=8)

        # ---------------- Tab Coordenadas ----------------
        tab_coords = ttk.Frame(notebook, style="Root.TFrame")
        notebook.add(tab_coords, text="Coordenadas")

        coords = self.config.get("screen_coords", {})
        coord_labels = [
            ("search_result_row", "Fila resultado de búsqueda"),
            ("search_result_col", "Columna resultado de búsqueda"),
            ("col_cant_tens", "Columna cantidad (decena)"),
            ("col_cant", "Columna cantidad"),
            ("col_dosis", "Columna dosis"),
            ("col_via", "Columna vía"),
            ("col_frecuencia", "Columna frecuencia"),
            ("col_dura_cant", "Columna duración (cantidad)"),
            ("col_dura_unidad", "Columna duración (unidad)"),
            ("guard_row", "Fila 'canario' (debe quedar vacía)"),
            ("guard_col", "Columna 'canario'"),
            ("guard_len", "Largo 'canario' (caracteres)"),
        ]
        coord_vars = {}
        for i, (key, label) in enumerate(coord_labels):
            ttk.Label(tab_coords, text=label + ":", style="Root.TLabel").grid(row=i, column=0, sticky="w", padx=8, pady=3)
            var = tk.IntVar(value=coords.get(key, 1))
            ttk.Spinbox(tab_coords, from_=1, to=200, textvariable=var, width=6).grid(row=i, column=1, sticky="w", padx=8, pady=3)
            coord_vars[key] = var

        row_after = len(coord_labels)
        ttk.Label(tab_coords, text="Filas de la grilla de orden (separadas por coma):", style="Root.TLabel").grid(
            row=row_after, column=0, sticky="w", padx=8, pady=(12, 3)
        )
        order_rows_var = tk.StringVar(value=",".join(str(x) for x in coords.get("order_rows", [16, 18, 20])))
        ttk.Entry(tab_coords, textvariable=order_rows_var, width=18).grid(
            row=row_after, column=1, sticky="w", padx=8, pady=(12, 3)
        )

        row_after += 1
        ttk.Label(tab_coords, text="Espera tras [pf4] antes de escribir la vía (segundos):", style="Root.TLabel").grid(
            row=row_after, column=0, sticky="w", padx=8, pady=3
        )
        pf4_popup_delay_var = tk.DoubleVar(value=coords.get("pf4_popup_delay_seconds", 0.3))
        ttk.Spinbox(tab_coords, from_=0.0, to=3.0, increment=0.1, textvariable=pf4_popup_delay_var,
                    width=6, format="%.1f").grid(row=row_after, column=1, sticky="w", padx=8, pady=3)

        row_after += 1
        ttk.Label(tab_coords, text="Espera tras confirmar la vía con [enter] (segundos):", style="Root.TLabel").grid(
            row=row_after, column=0, sticky="w", padx=8, pady=3
        )
        pf4_confirm_delay_var = tk.DoubleVar(value=coords.get("pf4_confirm_delay_seconds", 0.2))
        ttk.Spinbox(tab_coords, from_=0.0, to=3.0, increment=0.1, textvariable=pf4_confirm_delay_var,
                    width=6, format="%.1f").grid(row=row_after, column=1, sticky="w", padx=8, pady=3)

        row_after += 1
        ttk.Label(tab_coords, text="Tecla que abre el selector de vía (ej. [pf4]):", style="Root.TLabel").grid(
            row=row_after, column=0, sticky="w", padx=8, pady=3
        )
        via_selector_key_var = tk.StringVar(value=coords.get("via_selector_key", "[pf4]"))
        ttk.Entry(tab_coords, textvariable=via_selector_key_var, width=12).grid(
            row=row_after, column=1, sticky="w", padx=8, pady=3
        )

        # ---------------- Tab Reglas de negocio ----------------
        tab_rules = ttk.Frame(notebook, style="Root.TFrame")
        notebook.add(tab_rules, text="Reglas de negocio")

        ttk.Label(tab_rules, text="Umbral de similitud difusa (0.50 - 1.00):", style="Root.TLabel").grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 2), columnspan=2
        )
        cutoff_var = tk.DoubleVar(value=self.config.get("fuzzy_cutoff", 0.75))
        ttk.Spinbox(tab_rules, from_=0.5, to=1.0, increment=0.01, textvariable=cutoff_var, width=6, format="%.2f").grid(
            row=1, column=0, sticky="w", padx=8
        )

        name_synonyms = dict(self.config.get("name_synonyms", {}))
        ttk.Label(tab_rules, text="Sinónimos de nombre (ej. SOLUCION SALINA → CLORURO DE SODIO):", style="Root.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(14, 2)
        )
        name_syn_list = tk.Listbox(tab_rules, height=5, width=58, bg=LIST_BG, fg=FG,
                                    selectbackground=ACCENT, selectforeground="#ffffff", highlightthickness=0, bd=0)
        name_syn_list.grid(row=3, column=0, columnspan=2, padx=8, sticky="we")

        def refresh_name_syn_list():
            name_syn_list.delete(0, "end")
            for alias, canon in sorted(name_synonyms.items()):
                name_syn_list.insert("end", f"{alias}   →   {canon}")

        refresh_name_syn_list()

        name_alias_var = tk.StringVar()
        name_canon_var = tk.StringVar()
        entry_frame1 = ttk.Frame(tab_rules, style="Root.TFrame")
        entry_frame1.grid(row=4, column=0, columnspan=2, sticky="we", padx=8, pady=4)
        ttk.Entry(entry_frame1, textvariable=name_alias_var, width=20).pack(side="left")
        ttk.Label(entry_frame1, text=" → ", style="Root.TLabel").pack(side="left")
        ttk.Entry(entry_frame1, textvariable=name_canon_var, width=20).pack(side="left")

        def add_name_syn():
            alias = name_alias_var.get().strip().upper()
            canon = name_canon_var.get().strip().upper()
            if not alias or not canon:
                return
            name_synonyms[alias] = canon
            refresh_name_syn_list()
            name_alias_var.set("")
            name_canon_var.set("")

        def remove_name_syn():
            sel = name_syn_list.curselection()
            if not sel:
                return
            alias = sorted(name_synonyms.items())[sel[0]][0]
            del name_synonyms[alias]
            refresh_name_syn_list()

        ttk.Button(entry_frame1, text="Agregar", command=add_name_syn).pack(side="left", padx=4)
        ttk.Button(tab_rules, text="Eliminar seleccionado", command=remove_name_syn).grid(row=5, column=0, sticky="w", padx=8, pady=(0, 8))

        route_synonyms = dict(self.config.get("route_synonyms", {}))
        ttk.Label(tab_rules, text="Sinónimos de vía (ej. IV → PARENTERAL):", style="Root.TLabel").grid(
            row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2)
        )
        route_syn_list = tk.Listbox(tab_rules, height=5, width=58, bg=LIST_BG, fg=FG,
                                     selectbackground=ACCENT, selectforeground="#ffffff", highlightthickness=0, bd=0)
        route_syn_list.grid(row=7, column=0, columnspan=2, padx=8, sticky="we")

        def refresh_route_syn_list():
            route_syn_list.delete(0, "end")
            for alias, canon in sorted(route_synonyms.items()):
                route_syn_list.insert("end", f"{alias}   →   {canon}")

        refresh_route_syn_list()

        route_alias_var = tk.StringVar()
        route_canon_var = tk.StringVar()
        entry_frame2 = ttk.Frame(tab_rules, style="Root.TFrame")
        entry_frame2.grid(row=8, column=0, columnspan=2, sticky="we", padx=8, pady=4)
        ttk.Entry(entry_frame2, textvariable=route_alias_var, width=20).pack(side="left")
        ttk.Label(entry_frame2, text=" → ", style="Root.TLabel").pack(side="left")
        ttk.Entry(entry_frame2, textvariable=route_canon_var, width=20).pack(side="left")

        def add_route_syn():
            alias = route_alias_var.get().strip().upper()
            canon = route_canon_var.get().strip().upper()
            if not alias or not canon:
                return
            route_synonyms[alias] = canon
            refresh_route_syn_list()
            route_alias_var.set("")
            route_canon_var.set("")

        def remove_route_syn():
            sel = route_syn_list.curselection()
            if not sel:
                return
            alias = sorted(route_synonyms.items())[sel[0]][0]
            del route_synonyms[alias]
            refresh_route_syn_list()

        ttk.Button(entry_frame2, text="Agregar", command=add_route_syn).pack(side="left", padx=4)
        ttk.Button(tab_rules, text="Eliminar seleccionado", command=remove_route_syn).grid(row=9, column=0, sticky="w", padx=8, pady=(0, 8))

        # ---------------- Tab Coincidencias exactas ----------------
        tab_exact = ttk.Frame(notebook, style="Root.TFrame")
        notebook.add(tab_exact, text="Coincidencias exactas")

        ttk.Label(
            tab_exact,
            text="Líneas de prescripción recordadas tal cual (registro que se llena al tildar "
                 "\"Recordar línea exacta\" en el buscador). La próxima vez que aparezca la MISMA "
                 "línea, se descarga directo el medicamento indicado, sin volver a buscar.",
            wraplength=520, justify="left", style="Root.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))

        exact_matches_local = dict(self.exact_matches)

        exact_list_frame = ttk.Frame(tab_exact, style="Root.TFrame")
        exact_list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8)
        tab_exact.grid_rowconfigure(1, weight=1)
        tab_exact.grid_columnconfigure(0, weight=1)

        exact_list = tk.Listbox(exact_list_frame, height=12, width=68, bg=LIST_BG, fg=FG,
                                 selectbackground=ACCENT, selectforeground="#ffffff", highlightthickness=0, bd=0)
        exact_scroll = ttk.Scrollbar(exact_list_frame, orient="vertical", command=exact_list.yview)
        exact_list.configure(yscrollcommand=exact_scroll.set)
        exact_list.pack(side="left", fill="both", expand=True)
        exact_scroll.pack(side="left", fill="y")

        def refresh_exact_list():
            exact_list.delete(0, "end")
            for key, value in sorted(exact_matches_local.items()):
                codigo = value.get("codigo", "")
                desc = value.get("descripcion", "")
                exact_list.insert("end", f"{key[:48]:48s} → {codigo} {desc}")

        refresh_exact_list()

        def remove_exact_selected():
            sel = exact_list.curselection()
            if not sel:
                return
            key = sorted(exact_matches_local.items())[sel[0]][0]
            del exact_matches_local[key]
            refresh_exact_list()

        def clear_all_exact():
            if not exact_matches_local:
                return
            if self._confirm(
                "Borrar todo",
                f"¿Borrar las {len(exact_matches_local)} coincidencias exactas guardadas?\n"
                "Esto no se puede deshacer; las próximas notas volverán a pasar por la "
                "búsqueda normal hasta que se confirmen de nuevo.",
                ok_label="Borrar todo", cancel_label="No borrar",
            ):
                exact_matches_local.clear()
                refresh_exact_list()

        exact_btn_frame = ttk.Frame(tab_exact, style="Root.TFrame")
        exact_btn_frame.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 8))
        ttk.Button(exact_btn_frame, text="Eliminar seleccionada", command=remove_exact_selected).pack(side="left")
        ttk.Button(exact_btn_frame, text="Borrar todo", command=clear_all_exact).pack(side="left", padx=6)

        # ---------------- Tab Favoritos ----------------
        tab_fav = ttk.Frame(notebook, style="Root.TFrame")
        notebook.add(tab_fav, text="Favoritos")

        ttk.Label(
            tab_fav,
            text="Medicamentos guardados con una cantidad fija. Aparecen como botones "
                 "(⭐) debajo de la barra de acciones; clic derecho sobre un botón también "
                 "lo quita de favoritos.",
            wraplength=520, justify="left", style="Root.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))

        fav_local = [dict(b) for b in self.bookmarks]

        fav_list_frame = ttk.Frame(tab_fav, style="Root.TFrame")
        fav_list_frame.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=8)
        tab_fav.grid_rowconfigure(1, weight=1)
        tab_fav.grid_columnconfigure(0, weight=1)

        fav_listbox = tk.Listbox(
            fav_list_frame, height=10, width=64, bg=LIST_BG, fg=FG,
            selectbackground=ACCENT, selectforeground="#ffffff", highlightthickness=0, bd=0,
        )
        fav_scrollbar = ttk.Scrollbar(fav_list_frame, orient="vertical", command=fav_listbox.yview)
        fav_listbox.configure(yscrollcommand=fav_scrollbar.set)
        fav_listbox.pack(side="left", fill="both", expand=True)
        fav_scrollbar.pack(side="left", fill="y")

        def refresh_fav_listbox():
            fav_listbox.delete(0, "end")
            for b in fav_local:
                desc = (b.get("descripcion") or "")[:38]
                fav_listbox.insert("end", f"{desc:38s}  x{b.get('cantidad', 1):<4} [{b.get('codigo', '')}]")

        refresh_fav_listbox()

        fav_qty_frame = ttk.Frame(tab_fav, style="Root.TFrame")
        fav_qty_frame.grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=6)
        ttk.Label(fav_qty_frame, text="Cantidad:", style="Root.TLabel").pack(side="left")
        fav_qty_var = tk.IntVar(value=1)
        ttk.Spinbox(fav_qty_frame, from_=1, to=999, textvariable=fav_qty_var, width=6).pack(side="left", padx=4)

        def on_fav_select(_event=None):
            sel = fav_listbox.curselection()
            if sel:
                fav_qty_var.set(fav_local[sel[0]].get("cantidad", 1))

        fav_listbox.bind("<<ListboxSelect>>", on_fav_select)

        def update_fav_qty():
            sel = fav_listbox.curselection()
            if not sel:
                return
            fav_local[sel[0]]["cantidad"] = max(1, fav_qty_var.get())
            refresh_fav_listbox()

        ttk.Button(fav_qty_frame, text="Actualizar cantidad", command=update_fav_qty).pack(side="left", padx=6)

        def remove_fav_selected():
            sel = fav_listbox.curselection()
            if not sel:
                return
            del fav_local[sel[0]]
            refresh_fav_listbox()

        def clear_all_fav():
            if not fav_local:
                return
            if self._confirm(
                "Borrar todo", f"¿Borrar los {len(fav_local)} favoritos guardados?",
                ok_label="Borrar todo", cancel_label="No borrar",
            ):
                fav_local.clear()
                refresh_fav_listbox()

        fav_btn_frame = ttk.Frame(tab_fav, style="Root.TFrame")
        fav_btn_frame.grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(fav_btn_frame, text="Eliminar seleccionado", command=remove_fav_selected).pack(side="left")
        ttk.Button(fav_btn_frame, text="Borrar todo", command=clear_all_fav).pack(side="left", padx=6)

        # ---------------- Botones ----------------
        btn_frame = ttk.Frame(win, style="Root.TFrame")
        btn_frame.pack(fill="x", pady=8, padx=8)

        def do_save():
            try:
                order_rows = [int(x.strip()) for x in order_rows_var.get().split(",") if x.strip()]
                if not order_rows:
                    raise ValueError("la lista no puede quedar vacía")
            except ValueError as e:
                messagebox.showerror("Valor inválido", f"Filas de la grilla de orden inválidas: {e}")
                return

            new_coords = {key: var.get() for key, var in coord_vars.items()}
            new_coords["order_rows"] = order_rows
            new_coords["pf4_popup_delay_seconds"] = float(pf4_popup_delay_var.get())
            new_coords["pf4_confirm_delay_seconds"] = float(pf4_confirm_delay_var.get())
            new_coords["via_selector_key"] = via_selector_key_var.get().strip() or "[pf4]"

            self.acs_window_title_contains = acs_title_var.get().strip() or "5250"
            self.acs_read_hotkey_key = acs_read_key_var.get().strip().lower() or "l"
            self.acs_exec_hotkey_key = acs_exec_key_var.get().strip().lower() or "e"
            self.acs_confirm_hotkey_key = acs_confirm_key_var.get().strip().lower() or "c"
            self.acs_macro_hotkey_modifiers = acs_mods_var.get().strip().lower() or "control,shift"
            self.macro_timeout_seconds = int(macro_timeout_var.get())
            new_catalog_path = catalog_var.get().strip() or self.catalog_path
            catalog_changed = new_catalog_path != self.catalog_path
            self.catalog_path = new_catalog_path
            self.timeout_seconds = int(timeout_var.get())

            self.config.update({
                "session_name": "ACS 5250 activo",
                "acs_window_title_contains": self.acs_window_title_contains,
                "acs_read_hotkey_key": self.acs_read_hotkey_key,
                "acs_exec_hotkey_key": self.acs_exec_hotkey_key,
                "acs_confirm_hotkey_key": self.acs_confirm_hotkey_key,
                "acs_macro_hotkey_modifiers": self.acs_macro_hotkey_modifiers,
                "macro_timeout_seconds": self.macro_timeout_seconds,
                "catalog_path": self.catalog_path,
                "timeout_seconds": self.timeout_seconds,
                "screen_coords": new_coords,
                "fuzzy_cutoff": float(cutoff_var.get()),
                "name_synonyms": name_synonyms,
                "route_synonyms": route_synonyms,
                "exact_matches": exact_matches_local,
                "bookmarks": fav_local,
                "note_font_size": int(font_size_var.get()),
            })
            app_config.save_config(self.config)

            # Aplicar de inmediato (sin reiniciar la app)
            set_name_synonyms(self.config["name_synonyms"])
            set_fuzzy_cutoff(self.config["fuzzy_cutoff"])
            set_route_synonyms(self.config["route_synonyms"])
            self.exact_matches = exact_matches_local
            self.bookmarks = fav_local
            self._refresh_favorites_bar()

            # Si cambió cualquier dato de ACS/coordenadas, recrear el controlador
            # para que el próximo Leer/Descargar use la configuración nueva.
            if self.controller is not None:
                try:
                    self.controller.close()
                except Exception:
                    pass
                self.controller = None

            if catalog_changed:
                try:
                    self.catalog = load_catalog(app_config.resolve_data_path(self.catalog_path))
                    self.set_status(f"Catálogo recargado: {self.catalog_path}")
                except Exception as e:
                    messagebox.showerror("Error al cargar catálogo", str(e))

            self.note_font_size = int(font_size_var.get())
            self.note_text.configure(font=("Consolas", self.note_font_size))

            win.destroy()
            self.set_status("Configuración guardada.")

        ttk.Button(btn_frame, text="Guardar", command=do_save).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="Cancelar", command=win.destroy).pack(side="right")


def main():
    cfg = app_config.load_config()

    parser = argparse.ArgumentParser(description="UI de descargo de medicación - ACS/HOD1108")
    parser.add_argument("--session", default=None, help=argparse.SUPPRESS)  # compatibilidad antigua
    parser.add_argument("--acs-window-title", default=None, help="Texto contenido en el título de la ventana 5250 de ACS")
    parser.add_argument("--catalog", default=None, help="Ruta al CSV del catálogo (si no se indica, usa config.json)")
    args = parser.parse_args()

    if args.acs_window_title:
        cfg["acs_window_title_contains"] = args.acs_window_title

    session_name = "ACS 5250 activo"
    catalog_path = args.catalog or cfg.get("catalog_path", "farmacos.csv")

    root = tk.Tk()
    root.withdraw()
    if not license_manager.ensure_activated(root):
        root.destroy()
        return
    root.deiconify()
    DescargoApp(root, session_name, catalog_path, cfg)
    root.mainloop()


if __name__ == "__main__":
    main()
