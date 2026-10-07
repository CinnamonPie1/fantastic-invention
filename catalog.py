# -*- coding: utf-8 -*-
"""
catalog.py
Carga el catálogo completo de medicamentos (farmacos.csv) a memoria.
Columnas reales del archivo: Codigo, Descripcion, Presentacion.
"""

import csv
import difflib
import re
from typing import List, Dict
from med_matcher import CatalogRow


def load_catalog(csv_path: str) -> List[CatalogRow]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                CatalogRow(
                    codigo=r["Codigo"].strip(),
                    descripcion=r["Descripcion"].strip(),
                    presentacion=r["Presentacion"].strip(),
                    screen_row_index=-1,  # se asigna en tiempo real al leer la pantalla de búsqueda
                )
            )
    return rows


NAME_SYNONYMS = {
    "SOLUCION SALINA": "CLORURO DE SODIO",
    "SOL SALINA": "CLORURO DE SODIO",
    "SS0.9": "CLORURO DE SODIO",
    "SSN": "CLORURO DE SODIO",
}

# Umbral de similitud para la búsqueda difusa (última pasada de candidates_by_name
# y de search_catalog). Editable desde la Ventana de Configuración -> set_fuzzy_cutoff().
FUZZY_CUTOFF = 0.75

# Palabras de relleno que no aportan nada al buscar (conectores en español);
# se ignoran al tokenizar para que no infl en el puntaje de coincidencia.
STOPWORDS = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "EN", "CON", "PARA", "POR", "SIN", "Y", "O", "A", "AL"}

# Palabras de forma/vía/frecuencia (y formatos de presentación) que aparecen
# en decenas de filas del catálogo por igual, sin decir nada sobre CUÁL
# medicamento es (ej. "LIQUIDO", "PARENTERAL", "CADA", "HORAS"). Si pesan lo
# mismo que el resto de las palabras al buscar, terminan dominando el
# puntaje: pegar una línea completa de la nota como "ONDANSETRON LIQUIDO
# PARENTERAL 8 MG IV CADA 8 HORAS" hacía que cualquier fila con "LIQUIDO" +
# "PARENTERAL" (docenas de medicamentos distintos) empatara o incluso le
# ganara al verdadero ONDANSETRON. Por eso valen mucho menos que el resto de
# palabras: sirven para desempatar entre variantes del mismo nombre, no para
# decidir cuál nombre es.
LOW_WEIGHT_WORDS = {
    "LIQUIDO", "SOLIDO", "SEMISOLIDO",
    "ORAL", "PARENTERAL", "TOPICO",
    "IV", "EV", "SC", "IM", "PO", "HS",
    "VENOSA", "INTRAVENOSA", "INTRAVENOSO", "SUBCUTANEA", "INTRAMUSCULAR",
    "CADA", "HORAS", "HORA", "DIA", "DIAS", "VIA", "MAS", "PRN",
    "BID", "TID", "QID", "QD",
    "TAB", "TABLETA", "TABLETAS", "CAP", "CAPSULA", "CAPSULAS", "COMP",
    "JBE", "SOL", "SUSP", "GOTAS", "AMPOLLA", "VIAL", "FCO", "BLIST", "CJ",
}
# Pesos enteros (en vez de 1.0 / 0.2) para no depender de comparaciones de
# punto flotante al buscar el puntaje máximo.
FULL_WEIGHT = 5
LOW_WEIGHT = 1


def _token_weight(token: str) -> int:
    return LOW_WEIGHT if token in LOW_WEIGHT_WORDS else FULL_WEIGHT


def set_name_synonyms(synonyms: dict):
    """Reemplaza el diccionario de sinónimos de nombre en tiempo de ejecución
    (usado por la Ventana de Configuración, sin tener que editar este archivo)."""
    global NAME_SYNONYMS
    NAME_SYNONYMS = dict(synonyms)


def set_fuzzy_cutoff(value: float):
    """Ajusta el umbral de similitud difusa en tiempo de ejecución."""
    global FUZZY_CUTOFF
    FUZZY_CUTOFF = value


def _tokenize(text: str) -> List[str]:
    """Separa un texto en palabras (cualquier caracter que no sea letra o
    número corta palabra, así que guiones, comas, '/', etc. no estorban),
    descartando conectores y palabras de 1 letra que no sirven para buscar."""
    tokens = re.split(r"[^0-9A-ZÁÉÍÓÚÑ]+", text.upper())
    return [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]


def _best_overlap_matches(catalog: List[CatalogRow], tokens: List[str]):
    """Puntúa cada fila del catálogo por cuántas palabras de `tokens`
    aparecen en su Descripción, y devuelve las filas con el puntaje más
    alto (mayor coincidencia), sin exigir coincidencia exacta ni orden.
    Las palabras de forma/vía/frecuencia (LOW_WEIGHT_WORDS) cuentan mucho
    menos que el resto, para que no dominen el puntaje por sí solas."""
    if not tokens:
        return []
    scored = []
    for c in catalog:
        text = c.descripcion.upper()
        score = sum(_token_weight(t) for t in tokens if t in text)
        if score:
            scored.append((score, c))
    if not scored:
        return []
    max_score = max(s for s, _ in scored)
    return [c for s, c in scored if s == max_score]


def search_catalog(catalog: List[CatalogRow], query: str, limit: int = 150) -> List[CatalogRow]:
    """Búsqueda de propósito general (usada por la ventana de búsqueda manual
    y por favoritos): separa `query` en palabras y devuelve las filas del
    catálogo ordenadas por cuántas palabras coinciden en Descripción +
    Presentación (de mayor a menor coincidencia), sin exigir que el texto
    completo aparezca tal cual. Así, pegar una línea entera de la nota (con
    dosis, vía, guiones, etc.) igual encuentra el medicamento correcto.

    Las palabras de forma/vía/frecuencia (LOW_WEIGHT_WORDS, ej. "LIQUIDO",
    "PARENTERAL", "CADA", "HORAS") pesan mucho menos que el resto: aparecen
    en decenas de filas de nombres distintos, así que si contaran igual que
    el nombre del medicamento terminarían dominando el orden (ej. pegar
    "ONDANSETRON LIQUIDO PARENTERAL 8 MG IV" ya no hace que cualquier fila
    con "LIQUIDO PARENTERAL" (de otro medicamento) se cuele antes que el
    ONDANSETRON real)."""
    tokens = _tokenize(query)
    if not tokens:
        return []
    scored = []
    for c in catalog:
        text = f"{c.descripcion} {c.presentacion}".upper()
        score = sum(_token_weight(t) for t in tokens if t in text)
        if score:
            scored.append((score, c))
    scored.sort(key=lambda sc: (-sc[0], sc[1].descripcion))
    return [c for _, c in scored[:limit]]


def normalize_prescription_key(raw_line: str) -> str:
    """Normaliza una línea de prescripción para usarla como llave del
    registro personal de coincidencias exactas (ver 'exact_matches' en
    config.json, manejado desde gui.py): mayúsculas, sin la numeración de
    lista al inicio ('9.', '10)'), espacios múltiples colapsados a uno.
    Dos líneas que solo difieren en esos detalles pero dicen exactamente lo
    mismo deben resolver a la misma llave, para que una "prescripción
    exactamente igual" encuentre el registro guardado la próxima vez."""
    text = re.sub(r"^\s*\d+[.\)]\s*", "", (raw_line or "").strip().upper())
    text = re.sub(r"\s+", " ", text)
    return text


def candidates_by_name(catalog: List[CatalogRow], name: str):
    """
    Busca candidatos por nombre en varias pasadas, cada vez más permisivas,
    deteniéndose en la primera que encuentre algo (para no diluir con
    resultados de baja calidad si ya hay una coincidencia buena):
      1. Prefijo exacto: la Descripcion empieza con el nombre.
      2. Contiene: el nombre aparece tal cual en cualquier parte de la Descripcion.
      3. Mayor coincidencia: el nombre no aparece completo en ningún lado,
         pero se compara palabra por palabra y se toman las filas que más
         palabras tienen en común (cubre nombres con orden distinto, con una
         palabra de más/de menos, o solo parcialmente iguales — antes esto
         caía directo a "sin_match" si no había prefijo ni "contiene" exacto).
      4. Difusa: como último recurso, nombres parecidos por typos comparando
         similitud de texto sobre la primera palabra de cada fila (cubre
         casos donde ni una sola palabra coincidió tal cual, ej. "PARASETAMOL").

    Devuelve (candidatos, tipo_match), donde tipo_match es "exacta", "contiene"
    o "difusa" — útil para marcar como dudoso (amarillo) cualquier resultado
    que no venga de una coincidencia exacta, aunque termine siendo único.
    """
    name_upper = name.strip().upper()
    if len(name_upper) < 3:
        return [], "exacta"  # nombre vacío/insuficiente: no adivinar, dejar sin_match

    lookup_name = NAME_SYNONYMS.get(name_upper, name_upper)

    # Pasada 1: prefijo
    prefix_matches = [c for c in catalog if c.descripcion.upper().startswith(lookup_name)]
    if prefix_matches:
        return prefix_matches, "exacta"

    # Pasada 2: contiene en cualquier parte
    contains_matches = [c for c in catalog if lookup_name in c.descripcion.upper()]
    if contains_matches:
        return contains_matches, "contiene"

    # Pasada 3 (NUEVA): mayor coincidencia por palabras
    overlap_matches = _best_overlap_matches(catalog, _tokenize(lookup_name))
    if overlap_matches:
        return overlap_matches, "difusa"

    # Pasada 4: difusa por typos, comparando contra la primera palabra de cada fila del catálogo
    first_words = {}
    for c in catalog:
        first_word = c.descripcion.upper().split()[0] if c.descripcion.strip() else ""
        first_words.setdefault(first_word, []).append(c)

    query_first_word = lookup_name.split()[0] if lookup_name else ""
    close = difflib.get_close_matches(query_first_word, first_words.keys(), n=5, cutoff=FUZZY_CUTOFF)
    fuzzy_matches = []
    for w in close:
        fuzzy_matches.extend(first_words[w])
    return fuzzy_matches, "difusa"


if __name__ == "__main__":
    catalog = load_catalog("farmacos.csv")
    print(f"Total filas cargadas: {len(catalog)}")
    paracetamol_rows, match_type = candidates_by_name(catalog, "PARACETAMOL")
    print(f"Tipo de coincidencia: {match_type}")
    for row in paracetamol_rows:
        print(row)
