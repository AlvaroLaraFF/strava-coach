"""Localize the English session-analysis narrative to Spanish for the web GUI.

session_analysis.py emits English bullets by design (the chat assistant
translates them at presentation time). The web GUI can't do that, so this
module translates the known templates at the API boundary. Numbers are
preserved (we only substitute the surrounding words). Anything that doesn't
match a known phrase passes through unchanged.
"""
from __future__ import annotations

# Ordered (english_fragment -> spanish_fragment). Applied sequentially to each
# bullet, so more specific / longer phrases MUST come before generic ones
# (e.g. "s/km faster than the first" before the bare "s/km faster").
_SUBS: list[tuple[str, str]] = [
    # Header line
    ("Session: ", "Sesión: "),
    (" km at ", " km a "),
    (", avg HR ", ", FC media "),
    # Pace pattern
    ("Pace pattern: progressive — last third ", "Patrón de ritmo: progresivo — último tercio "),
    (" s/km faster than the first.", " s/km más rápido que el primero."),
    ("Pace pattern: clear fade — last third ", "Patrón de ritmo: caída clara — último tercio "),
    (" s/km slower than the first.", " s/km más lento que el primero."),
    ("Pace pattern: U-shape — middle of the session was the slowest stretch.",
     "Patrón de ritmo: forma de U — la parte central fue el tramo más lento."),
    ("Pace pattern: middle surge — the centre was the fastest stretch.",
     "Patrón de ritmo: acelerón central — el centro fue el tramo más rápido."),
    ("Pace pattern: even across the session.",
     "Patrón de ritmo: constante durante toda la sesión."),
    # Cardiac drift
    ("High cardiac drift: +", "Deriva cardíaca alta: +"),
    ("% HR between halves — sign of aerobic fatigue.",
     "% de FC entre mitades — señal de fatiga aeróbica."),
    ("Moderate cardiac drift: +", "Deriva cardíaca moderada: +"),
    ("% (acceptable for long runs or hot conditions).",
     "% (aceptable en tiradas largas o con calor)."),
    ("Cardiac drift contained (+", "Deriva cardíaca contenida (+"),
    ("%) — solid aerobic base for this intensity.",
     "%) — base aeróbica sólida para esta intensidad."),
    # Elevation
    ("Hilly terrain (", "Terreno con desnivel ("),
    (" m gain): actual pace ", " m de subida): ritmo real "),
    ("/km equals ", "/km equivale a "),
    ("/km on flat (GAP, ", "/km en llano (GAP, "),
    (" s/km cost).", " s/km de coste)."),
    ("Net descending terrain: GAP ", "Terreno neto descendente: GAP "),
    ("/km vs actual ", "/km vs real "),
    ("% of the route was uphill (>3% grade), avg pace ",
     "% del recorrido fue en subida (>3% de pendiente), ritmo medio "),
    # Closest match (side-by-side)
    ("Closest match: ", "Sesión más parecida: "),
    (" d ago, ", " d atrás, "),
    ("% distance diff)", "% dif. de distancia)"),
    (" — today ", " — hoy "),
    (" — pace within ±5 s/km", " — ritmo dentro de ±5 s/km"),
    (", elevation ", ", desnivel "),
    # Similar-median (before the bare 's/km faster/slower' fragments)
    ("Faster than your median of the last ", "Más rápido que tu mediana de las últimas "),
    ("Slower than your median of the last ", "Más lento que tu mediana de las últimas "),
    ("In line with your median of the last ", "En línea con tu mediana de las últimas "),
    (" similar sessions (", " sesiones similares ("),
    (" s/km faster)", " s/km más rápido)"),
    (" s/km slower)", " s/km más lento)"),
    (", but at higher HR (+", ", pero a mayor FC (+"),
    (") — paid for the speed with cardiac effort.", ") — pagaste la velocidad con esfuerzo cardíaco."),
    (", at higher HR (+", ", a mayor FC (+"),
    (") — more cardiac stress for equal or worse pace.", ") — más estrés cardíaco para igual o peor ritmo."),
    (", and at lower HR (", ", y a menor FC ("),
    (") — clear aerobic progress.", ") — progreso aeróbico claro."),
    (", at lower HR (", ", a menor FC ("),
    (") — easier session than usual.", ") — sesión más fácil de lo habitual."),
    (", HR similar (", ", FC similar ("),
    # Generic side-by-side pace deltas (after the '...than the first' / '...)' cases)
    (" s/km faster", " s/km más rápido"),
    (" s/km slower", " s/km más lento"),
    # PRs
    ("All-time PR today on: ", "PR histórico hoy en: "),
    ("All-time top-5 also on: ", "Top-5 histórico también en: "),
    (" (rank ", " (puesto "),
    # Slowdown
    (" s/km below median — cause: ", " s/km por debajo de la mediana — causa: "),
    ("terrain explained", "explicado por el terreno"),
    ("cardiac drift", "deriva cardíaca"),
    ("cadence drop", "caída de cadencia"),
    ("uphill", "subida"),
    ("intrinsic", "esfuerzo propio"),
    # Intervals
    ("Detected ", "Detectadas "),
    (" reps from watch laps (avg pace ", " series por las vueltas del reloj (ritmo medio "),
    (" reps reached the target peak HR (", " series alcanzaron la FC pico objetivo ("),
    ("Intervals: ", "Series: "),
    (" reached the target peak HR.", " alcanzaron la FC pico objetivo."),
    # Recent-intervals delta
    ("Vs last interval session (", "Vs última sesión de series ("),
    ("avg rep pace ", "ritmo medio de serie "),
    ("avg rep HR ", "FC media de serie "),
    (" (lower)", " (menor)"),
    (" (higher)", " (mayor)"),
    ("cadence ", "cadencia "),
    (" reps", " series"),
    # Plan comparison
    ("HR average inside the planned range — session executed as prescribed.",
     "FC media dentro del rango planificado — sesión ejecutada según lo previsto."),
    ("HR average above the planned range — session ran harder than planned.",
     "FC media por encima del rango planificado — sesión más dura de lo previsto."),
    ("HR average below the planned range — session ran softer than planned.",
     "FC media por debajo del rango planificado — sesión más suave de lo previsto."),
    # Catch-all: any remaining "HR" -> "FC"
    ("HR", "FC"),
]


def translate_bullet(text: str) -> str:
    out = text
    for en, es in _SUBS:
        if en in out:
            out = out.replace(en, es)
    return out


def translate(bullets: list[str]) -> list[str]:
    return [translate_bullet(b) for b in (bullets or [])]
