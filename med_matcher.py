# -*- coding: utf-8 -*-
"""
med_matcher.py
Empareja una MedicationLine (de note_parser) contra las filas que PCOMM
devuelve en la pantalla de búsqueda (img 3-4), usando forma farmacéutica,
vía/presentación y concentración para desambiguar entre variantes
(ej. PARACETAMOL LIQUIDO ORAL 100 MG/ML vs 120 MG/5ML vs 160 MG/5ML).

Este módulo NO habla con PCOMM directamente; recibe las filas ya leídas
de pantalla (como texto) para que se pueda probar sin conexión.
"""

import re
from dataclasses import dataclass
from typing import List, Optional
from note_parser import MedicationLine


@dataclass
class CatalogRow:
    codigo: str
    descripcion: str       # ej. "PARACETAMOL LIQUIDO ORAL (GOTAS)"
    presentacion: str      # ej. "SOL.GOTAS. 100 MG/ML CJ X FCO G"
    screen_row_index: int  # fila en pantalla (para SetCursorPos / marcar Op)


@dataclass
class MatchResult:
    row: Optional[CatalogRow]
    confidence: str  # "alta" | "ambigua" | "sin_match"
    reason: str
    candidates: List[CatalogRow]


CONCENTRATION_REGEX = re.compile(r"(\d[\d.,]*)\s*(MG|MCG|GR|G|UI|ML|CC|MEQ|%)\b", re.IGNORECASE)

UNIT_ALIASES = {"CC": "ML"}  # unidades equivalentes para efectos de comparación


def _parse_number(raw: str) -> float:
    """
    Convierte un número con formato hispano (punto = miles, coma = decimal)
    a float. Ej: '1.000' -> 1000.0, '0,9' -> 0.9, '3,4' -> 3.4, '250' -> 250.0.
    """
    s = raw.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")  # solo separadores de miles, sin parte decimal
    return float(s)


def _extract_quantities(text: str):
    """Extrae TODAS las parejas (valor, unidad) numéricas de un texto, no solo la primera.
    Se usa tanto para la línea de la nota como para la Presentación del catálogo,
    para comparar cuántas coinciden en vez de comparar un solo número a ciegas."""
    out = []
    for m in CONCENTRATION_REGEX.finditer(text.upper()):
        try:
            value = _parse_number(m.group(1))
        except ValueError:
            continue
        unit = m.group(2).upper()
        unit = UNIT_ALIASES.get(unit, unit)
        out.append((value, unit))
    return out


def _extract_concentration(text: str):
    quantities = _extract_quantities(text)
    return quantities[0] if quantities else None


ROUTE_ABBREVIATIONS = {
    "PARENTERAL": ["PARENTERAL", "PAR.", "LQ.PAR", "SD.PAR", ".INY", "INY."],
    "ORAL": ["ORAL"],
}


def _route_matches(route: str, descripcion: str, presentacion: str) -> bool:
    text = (descripcion + " " + presentacion).upper()
    tokens = ROUTE_ABBREVIATIONS.get(route, [route])
    return any(tok in text for tok in tokens)


def match_medication(med: MedicationLine, candidates: List[CatalogRow]) -> MatchResult:
    """
    Filtra candidatos por forma y vía, y desempata por concentración.
    Devuelve confidence="ambigua" si más de una fila sobrevive el filtro
    (para forzar detención manual en vez de adivinar).
    """
    if not candidates:
        return MatchResult(None, "sin_match", "No se encontraron filas para el nombre buscado", [])

    filtered = candidates
    form_mismatch = False
    route_mismatch = False

    if med.form:
        by_form = [c for c in filtered if med.form in c.descripcion.upper()]
        if by_form:
            filtered = by_form
        else:
            form_mismatch = True  # el catálogo no tiene esa forma; no se descarta en silencio

    if med.route:
        by_route = [c for c in filtered if _route_matches(med.route, c.descripcion, c.presentacion)]
        if by_route:
            filtered = by_route
        else:
            route_mismatch = True

    if form_mismatch or route_mismatch:
        motivo = []
        if form_mismatch:
            motivo.append(f"forma '{med.form}' no encontrada en el catálogo para este nombre")
        if route_mismatch:
            motivo.append(f"vía '{med.route}' no encontrada en el catálogo para este nombre")
        # Se marca como ambigua (para que la UI lo muestre y permita elegir),
        # pero se conservan los candidatos sin filtrar por si el usuario
        # quiere revisar todas las opciones igual.
        return MatchResult(
            None, "ambigua",
            "Posible discrepancia forma/vía nota vs. catálogo: " + "; ".join(motivo),
            candidates,
        )

    if len(filtered) == 1:
        return MatchResult(filtered[0], "alta", "Único candidato tras filtrar por forma/vía", filtered)

    # Seguridad: si la nota NO especificó vía/forma y los candidatos restantes
    # abarcan vías administrativas distintas (ej. ORAL vs PARENTERAL), no se
    # debe desambiguar solo por concentración — la vía es una decisión clínica,
    # no una coincidencia numérica.
    if not med.route and not med.form:
        vias_presentes = set()
        for c in filtered:
            if _route_matches("PARENTERAL", c.descripcion, c.presentacion):
                vias_presentes.add("PARENTERAL")
            if _route_matches("ORAL", c.descripcion, c.presentacion):
                vias_presentes.add("ORAL")
        if len(vias_presentes) > 1:
            return MatchResult(
                None, "ambigua",
                "La nota no especifica vía/forma y los candidatos abarcan "
                "presentaciones clínicamente distintas (oral vs parenteral); "
                "no se puede decidir solo por concentración",
                filtered,
            )

    # Desempatar comparando TODAS las cantidades numéricas de la línea completa
    # (dosis, %, volumen, mEq, etc.) contra la Presentación de cada candidato,
    # en vez de comparar solo la primera dosis extraída a ciegas.
    line_quantities = _extract_quantities(med.raw_line)
    if line_quantities:
        scored = []
        for c in filtered:
            cand_quantities = _extract_quantities(c.presentacion)
            overlap = 0
            for lv, lu in line_quantities:
                for cv, cu in cand_quantities:
                    if lu == cu and abs(lv - cv) < 0.001:
                        overlap += 1
                        break
            if overlap > 0:
                scored.append((overlap, c))

        if scored:
            max_overlap = max(o for o, _ in scored)
            best = [c for o, c in scored if o == max_overlap]
            if len(best) == 1:
                return MatchResult(
                    best[0], "alta",
                    f"Coincidencia de {max_overlap} cantidad(es) numérica(s) exacta(s) con la presentación",
                    filtered,
                )
            filtered = best  # varios empatan en el mismo número de coincidencias; sigue ambiguo pero más acotado

    # Compatibilidad: si además se detectó una dosis simple explícita, intentar
    # el desempate clásico por concentración única (cubre casos que el paso anterior no resolvió).
    if med.dose_value:
        try:
            target_value = _parse_number(med.dose_value)
        except ValueError:
            target_value = None

        if target_value is not None:
            scored = []
            for c in filtered:
                conc = _extract_concentration(c.presentacion)
                if conc and abs(conc[0] - target_value) < 0.001 and (
                    med.dose_unit is None or conc[1] == med.dose_unit.upper()
                ):
                    scored.append(c)
            if len(scored) == 1:
                return MatchResult(scored[0], "alta", "Coincidencia exacta de concentración", filtered)
            if len(scored) > 1:
                filtered = scored  # sigue ambiguo, pero más acotado

    if len(filtered) == 1:
        return MatchResult(filtered[0], "alta", "Único candidato tras desempate por concentración", filtered)

    return MatchResult(
        None,
        "ambigua",
        f"{len(filtered)} candidatos posibles tras filtrar, requiere revisión manual",
        filtered,
    )


if __name__ == "__main__":
    # Ejemplo con las filas de tu imagen 4 (PARACETAMOL)
    rows = [
        CatalogRow("4102031", "PARACETAMOL LIQUIDO ORAL (GOTAS)", "SOL.GOTAS. 100 MG/ML CJ X FCO G", 1),
        CatalogRow("4102028", "PARACETAMOL LIQUIDO ORAL", "JBE/SOL/SUSP. 120 MG/5 ML CJ X", 2),
        CatalogRow("4102030", "PARACETAMOL LIQUIDO ORAL", "JBE/SOL/SUSP. 160 MG/5 ML CJ X", 3),
        CatalogRow("4102037", "PARACETAMOL LIQUIDO PARENTERAL", "SOL.INY. 10 MG/ML CJ X VIAL(ES)", 4),
        CatalogRow("4102027", "PARACETAMOL SOLIDO ORAL", "TAB/CAP/COMP. 500 MG CJ X BLIST", 5),
    ]
    med = MedicationLine(
        raw_line="PARACETAMOL LIQUIDO PARENTERAL 1 GR IV CADA PRN",
        name="PARACETAMOL", form="LIQUIDO", route="PARENTERAL",
        dose_value="1", dose_unit="GR",
    )
    result = match_medication(med, rows)
    print(result)
