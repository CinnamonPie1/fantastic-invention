# -*- coding: utf-8 -*-
"""
note_parser.py
Extrae líneas de medicación desde el texto crudo de la nota clínica
(el texto que devuelve el macro de captura de pantalla).

La nota es texto libre, así que el parser es tolerante:
- Ignora líneas de indicaciones no farmacológicas (heurística: deben
  contener al menos un patrón de dosis o vía para considerarse medicación).
- Detecta líneas suspendidas ("SUSPENDER", "****SUSPENDER****", "//SUSPENDER//")
  y las excluye, pero las reporta para que quede constancia en el log.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List

SUSPEND_PATTERNS = [
    r"SUSPENDER",
]

# Palabras que indican vía / forma, usadas para separar el "nombre" del resto
FORM_WORDS = ["LIQUIDO", "SOLIDO", "SEMISOLIDO"]
ROUTE_WORDS = ["ORAL", "PARENTERAL", "IV", "SC", "IM", "TOPICO"]

# Sinónimos clínicos -> término canónico usado en el catálogo (Presentación/Descripción)
ROUTE_SYNONYMS = {
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
}


def set_route_synonyms(synonyms: dict):
    """Reemplaza el diccionario de sinónimos de vía en tiempo de ejecución
    (usado por la Ventana de Configuración, sin tener que editar este archivo)."""
    global ROUTE_SYNONYMS
    ROUTE_SYNONYMS = dict(synonyms)

# Frecuencias reconocidas -> horas entre dosis (None = no calculable / requiere revisión manual)
FREQ_HOURS = {
    "CADA DIA": 24,
    "QD": 24,
    "CADA 12 HORAS": 12,
    "BID": 12,
    "CADA 8 HORAS": 8,
    "TID": 8,
    "CADA 6 HORAS": 6,
    "QID": 6,
    "HS": 24,       # una vez, al acostarse -> tratar como 1x/día
    "PRN": None,    # a demanda -> no se calcula automáticamente
}

FREQ_REGEX = re.compile(
    r"CADA\s+(\d+)\s*HORAS?|CADA\s+DIA|BID|TID|QID|QD|HS\b|PRN",
    re.IGNORECASE,
)

DOSE_REGEX = re.compile(
    r"(?P<dose>\d+[.,]?\d*)\s*(?P<unit>MG|GRAMOS?|GR|MCG|ML|G|UI)\b",
    re.IGNORECASE,
)


def _normalize_dose_unit(unit: Optional[str]) -> Optional[str]:
    if unit is None:
        return None
    unit = unit.upper()
    if unit.startswith("GRAMO"):
        return "GR"
    return unit


@dataclass
class MedicationLine:
    raw_line: str
    name: str
    form: Optional[str] = None
    route: Optional[str] = None
    dose_value: Optional[str] = None
    dose_unit: Optional[str] = None
    frequency_text: Optional[str] = None
    hours_between_doses: Optional[int] = None
    doses_per_day: Optional[int] = None
    suspended: bool = False
    needs_manual_review: bool = False
    review_reason: Optional[str] = None
    line_index: Optional[int] = None  # índice (0-based) de la línea original en el texto de la nota


def is_suspended(line: str) -> bool:
    return any(re.search(p, line, re.IGNORECASE) for p in SUSPEND_PATTERNS)


def extract_frequency(line: str):
    """Devuelve (texto_frecuencia, horas_entre_dosis) o (None, None) si no se detecta."""
    m = FREQ_REGEX.search(line.upper())
    if not m:
        return None, None
    token = m.group(0).upper()
    if token.startswith("CADA") and token[-1].isdigit() is False and "DIA" in token:
        return "CADA DIA", 24
    hour_match = re.search(r"CADA\s+(\d+)\s*HORAS?", token)
    if hour_match:
        return token, int(hour_match.group(1))
    return token, FREQ_HOURS.get(token)


def _parse_segment(segment: str, global_route, global_hours, global_freq_text, suspended) -> Optional[MedicationLine]:
    """Parsea un solo medicamento (un segmento de línea, ya sin el resto separado por 'MAS')."""
    upper = segment.upper()

    has_form = any(w in upper for w in FORM_WORDS)
    dose_match = DOSE_REGEX.search(upper)

    if not has_form and not dose_match:
        return None

    # Nombre = todo lo que precede a la primera palabra de forma/vía/dosis/SUSPENDER
    stop_words = set(FORM_WORDS + ROUTE_WORDS)
    raw_tokens = re.split(r"[\s/]+", upper)
    name_tokens = []
    for tok in raw_tokens:
        tok = tok.strip()
        if not tok:
            continue
        # Quitar puntuación pegada al inicio/fin del token (viñetas, guiones,
        # asteriscos, dos puntos, etc.), sin partir la palabra en sí. Cubre
        # tanto "- SULFAMETOXAZOL" (con espacio, ya separado por el split de
        # arriba) como "-SULFAMETOXAZOL" (pegado, mismo token) — antes solo
        # se ignoraba el primer caso (token 100% puntuación); un token mixto
        # como "-SULFAMETOXAZOL" SÍ tiene letras, así que pasaba de largo y
        # quedaba pegado al nombre extraído, rompiendo la búsqueda en el
        # catálogo (por eso a veces salía en rojo/amarillo hasta borrar el
        # guion a mano en el cuadro de búsqueda).
        core = re.sub(r"^[^A-ZÁÉÍÓÚÑ0-9]+|[^A-ZÁÉÍÓÚÑ0-9]+$", "", tok)
        if not core:
            continue  # token era pura puntuación
        if core in stop_words:
            break
        if "SUSPENDER" in core:
            continue
        if re.search(r"\d", core):
            break
        name_tokens.append(core)
    name = " ".join(name_tokens) if name_tokens else (raw_tokens[0] if raw_tokens else upper)

    form = next((w for w in FORM_WORDS if w in upper), None)
    route_raw = next((syn for syn in ROUTE_SYNONYMS if syn in upper), None)
    route = ROUTE_SYNONYMS.get(route_raw) if route_raw else None
    route = route or global_route  # si el segmento no trae vía propia, hereda la de la línea completa

    freq_text, hours = extract_frequency(upper)
    if hours is None and global_hours is not None:
        # el segmento no trae su propia frecuencia (ej. "TRAMADOL 200MG" dentro de
        # "... MAS TRAMADOL 200MG MAS ... PASAR A 10 ML/H IV PRN"): hereda la de la línea
        freq_text, hours = global_freq_text, global_hours

    doses_per_day = None
    needs_review = False
    reason = None

    if suspended:
        reason = "Medicamento suspendido"
    elif hours is None:
        needs_review = True
        reason = f"Frecuencia no reconocida o PRN: '{freq_text}'"
    else:
        doses_per_day = max(1, round(24 / hours))

    dose_unit = _normalize_dose_unit(dose_match.group("unit")) if dose_match else None

    return MedicationLine(
        raw_line=segment.strip(),
        name=name,
        form=form,
        route=route,
        dose_value=dose_match.group("dose") if dose_match else None,
        dose_unit=dose_unit,
        frequency_text=freq_text,
        hours_between_doses=hours,
        doses_per_day=doses_per_day,
        suspended=suspended,
        needs_manual_review=needs_review,
        review_reason=reason,
    )


def parse_medication_line(line: str) -> List[MedicationLine]:
    """
    Intenta interpretar una línea como uno o varios medicamentos.
    Varias líneas de la nota describen infusiones combinadas separadas por la
    palabra "MAS" (ej. "CLORURO DE SODIO 0.9% 250 ML MAS TRAMADOL 200MG MAS
    ONDANSETRON 8 MG PASAR A 10 ML/H IV PRN"); en ese caso, cada componente se
    devuelve como un medicamento separado, heredando la vía/frecuencia común
    (normalmente al final de la línea) si el segmento no trae la suya propia.
    Devuelve una lista vacía si la línea no parece contener medicación.
    """
    # Quitar numeración de lista al inicio de la línea (ej. "9.", "10.", "17.")
    line = re.sub(r"^\s*\d+[.\)]\s*", "", line)
    upper_full = line.upper()

    suspended = is_suspended(upper_full)
    global_freq_text, global_hours = extract_frequency(upper_full)
    global_route_raw = next((syn for syn in ROUTE_SYNONYMS if syn in upper_full), None)
    global_route = ROUTE_SYNONYMS.get(global_route_raw) if global_route_raw else None

    segments = re.split(r"\bMAS\b", line, flags=re.IGNORECASE)

    results = []
    for seg in segments:
        seg = seg.strip(" ,")
        if not seg:
            continue
        med = _parse_segment(seg, global_route, global_hours, global_freq_text, suspended)
        if med:
            results.append(med)
    return results


DIAGNOSTICO_MARKER = "DIAGNOSTICO DEFINITIVO"
DIAGNOSTICO_MARKER_COLUMN_TOLERANCE = (24, 36)  # ventana alrededor de la columna 29 esperada


def _truncate_before_diagnostico(full_text: str) -> str:
    """
    Corta el texto de la nota justo antes de la línea 'J. DIAGNOSTICO DEFINITIVO'
    (esa etiqueta suele aparecer alrededor de la columna 29 de la fila). Si se
    encuentra dentro de la ventana de columnas esperada, se corta ahí; si no,
    se usa como respaldo la primera aparición en cualquier columna.
    """
    lines = full_text.splitlines()
    cut_at = None
    fallback_cut_at = None

    for i, line in enumerate(lines):
        pos = line.upper().find(DIAGNOSTICO_MARKER)
        if pos == -1:
            continue
        if fallback_cut_at is None:
            fallback_cut_at = i
        low, high = DIAGNOSTICO_MARKER_COLUMN_TOLERANCE
        if low <= pos <= high:
            cut_at = i
            break

    if cut_at is None:
        cut_at = fallback_cut_at

    if cut_at is None:
        return full_text  # no se encontró el marcador; se analiza todo (comportamiento anterior)

    return "\n".join(lines[:cut_at])


def parse_note(full_text: str) -> List[MedicationLine]:
    """Parsea el texto completo de la nota y devuelve solo líneas de medicación detectadas.
    Deja de analizar todo lo que venga después de 'J. DIAGNOSTICO DEFINITIVO'."""
    full_text = _truncate_before_diagnostico(full_text)
    results = []
    for idx, line in enumerate(full_text.splitlines()):
        if not line.strip():
            continue
        meds = parse_medication_line(line)
        for med in meds:
            med.line_index = idx
            results.append(med)
    return results


if __name__ == "__main__":
    # Prueba rápida con las líneas de tus imágenes
    sample = """
    PARACETAMOL LIQUIDO PARENTERAL 1 GR IV CADA PRN
    TAMSULOSINA 0,4 MG SOLIDO ORAL VIA ORAL CADA DIA
    //SUSPENDER// LACTULOSA LIQUIDO ORAL VIA ORAL BID HORAS
    OMEPRAZOL LIQUIDO PARENTERAL 40 MG INTRAVENOSO CADA DIA
    SUSPENDER//ENOXAPARINA LIQUIDO PARENTERAL 20 MG SC CADA DIA POR PERSISTENCIA
    """
    for med in parse_note(sample):
        print(med)
