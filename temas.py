"""
Temas de color de La bestia.

Un tema son cinco colores base (BASE). Todo lo demás (bordes, el gris de un
botón con el mouse encima, los textos apagados, lo seleccionado) se calcula a
partir de esos cinco en paleta(), así que un tema armado por alguien no puede
quedar a medias. Si el texto elegido no se lee sobre el fondo, se corrige.

Lo que tiene significado propio no cambia con el tema: los colores del
contador (bronce, plata, oro...), los festejos y el cofre.

No depende de Qt: son cuentas sobre "#RRGGBB", para poder probarlas solas.
"""

import re
from string import Template

# Los cinco colores de un tema, en el orden en que se muestran.
BASE = ("fondo", "paneles", "texto", "acento", "escanear")
NOMBRES_BASE = {
    "fondo": "Fondo",
    "paneles": "Botones",
    "texto": "Texto",
    "acento": "Acento",
    "escanear": "Escanear",
}
AYUDA_BASE = {
    "fondo": "El fondo de la ventana",
    "paneles": "Botones, desplegables y casilleros",
    "texto": "Las letras (se corrige solo si no se lee)",
    "acento": "Enlaces, foco y botones de confirmar",
    "escanear": "El botón grande de escanear",
}

# Los colores para elegir al armar un tema: pasteles medios, en columnas por
# tono (rosa, durazno, manteca, menta, salvia, celeste, lavanda, lila) y en
# filas de más suave a más intenso. La última fila son neutros, apenas
# lilas, para poder armar fondos y textos oscuros o claros.
PASTELES = [
    ["#F8D7DD", "#FBDCC8", "#FBEFC4", "#D3F0DF", "#DDEBCF", "#D2E7F7", "#DCDDF6", "#EBD9F2"],
    ["#F2A7B5", "#F6B998", "#F5DC8B", "#9FDDBB", "#B7D49B", "#9CCBEE", "#AFB3EC", "#D2AEE3"],
    ["#D9778C", "#E08F67", "#D9B556", "#5FB98D", "#86AE64", "#5D9FD3", "#7B80CF", "#A87BC4"],
]
NEUTROS = ["#1F1D24", "#2C2A33", "#3D3A45", "#6B6775", "#A8A4B0", "#D9D6DE", "#F2F0F4", "#FFFFFF"]

TEMAS = [
    {"nombre": "Oscuro", "colores": {
        "fondo": "#1E1E1E", "paneles": "#333333", "texto": "#D4D4D4",
        "acento": "#007ACC", "escanear": "#D84315"}},
    {"nombre": "Claro", "colores": {
        "fondo": "#F3F3F3", "paneles": "#FFFFFF", "texto": "#1F1F1F",
        "acento": "#0067C0", "escanear": "#D84315"}},
    {"nombre": "Bosque", "colores": {
        "fondo": "#15201A", "paneles": "#25362C", "texto": "#D5E5DA",
        "acento": "#3FAF77", "escanear": "#E09A2D"}},
    {"nombre": "Uva", "colores": {
        "fondo": "#1C1626", "paneles": "#302641", "texto": "#E3DBF1",
        "acento": "#9D78EA", "escanear": "#E0457B"}},
    # Rojinegro, como la camiseta de Patronato de Paraná.
    {"nombre": "Patronato", "colores": {
        "fondo": "#111111", "paneles": "#2B1B1C", "texto": "#F2F2F2",
        "acento": "#D7262E", "escanear": "#C8102E"}},
    {"nombre": "Alto contraste", "colores": {
        "fondo": "#000000", "paneles": "#1A1A1A", "texto": "#FFFFFF",
        "acento": "#FFD400", "escanear": "#FF5A1F"}},
]
POR_DEFECTO = TEMAS[0]

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# --- Cuentas de color ---

def _rgb(c):
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _hex(r, g, b):
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(v))) for v in (r, g, b)))


def mezcla(a, b, t):
    """El color que está a `t` (0 a 1) del camino de `a` a `b`."""
    (r1, g1, b1), (r2, g2, b2) = _rgb(a), _rgb(b)
    return _hex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)


def luminancia(c):
    """Luminancia relativa (WCAG), de 0 (negro) a 1 (blanco)."""
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(c)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(a, b):
    """Contraste entre dos colores (WCAG): de 1 (iguales) a 21 (negro y blanco)."""
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def legible(color, fondo, minimo=4.5):
    """
    `color`, aclarado u oscurecido lo justo para leerse sobre `fondo`. Va
    hacia el blanco o el negro, el que más contraste dé con el fondo.
    """
    if contraste(color, fondo) >= minimo:
        return color
    extremo = "#FFFFFF" if contraste("#FFFFFF", fondo) >= contraste("#000000", fondo) else "#000000"
    for paso in range(1, 21):
        c = mezcla(color, extremo, paso / 20)
        if contraste(c, fondo) >= minimo:
            return c
    return extremo


def sobre(color):
    """
    Blanco o casi negro para escribir encima de `color`. Blanco mientras se
    lea (como en el naranja de siempre); casi negro sobre colores claros.
    """
    return "#FFFFFF" if contraste("#FFFFFF", color) >= 3.0 else "#141414"


def es_color(c):
    return isinstance(c, str) and bool(_HEX.match(c))


def es_tema(t):
    """Si `t` (leído de la configuración) es un tema bien formado."""
    return (isinstance(t, dict) and isinstance(t.get("nombre"), str) and t["nombre"].strip() != ""
            and isinstance(t.get("colores"), dict)
            and all(es_color(t["colores"].get(k)) for k in BASE))


# --- La paleta completa ---

def paleta(colores):
    """Todos los colores de la ventana a partir de los cinco de un tema."""
    f = colores["fondo"].upper()
    p = colores["paneles"].upper()
    a = colores["acento"].upper()
    e = colores["escanear"].upper()
    oscuro = luminancia(f) < 0.3
    extremo = "#FFFFFF" if oscuro else "#000000"
    # El texto tiene que leerse sobre el fondo y sobre los botones.
    t = legible(legible(colores["texto"].upper(), f, 4.5), p, 4.5)

    c = {
        "oscuro": oscuro,
        "texto_ajustado": t != colores["texto"].upper(),
        "fondo": f,
        "texto": t,
        "texto2": mezcla(t, f, 0.04),
        "titulo": mezcla(t, extremo, 0.7),
        "tenue": legible(mezcla(t, f, 0.33), f, 3.5),
        "tenue2": legible(mezcla(t, f, 0.42), f, 3.0),
        "apagado_texto": legible(mezcla(t, f, 0.6), f, 2.5),
        "marca_baja": mezcla(t, f, 0.77),
        "paneles": p,
        "paneles_hover": mezcla(p, t, 0.07),
        "borde": mezcla(p, t, 0.12),
        "scroll": mezcla(p, t, 0.12),
        "scroll_hover": mezcla(p, t, 0.2),
        "hundido": mezcla(f, "#000000", 0.2) if oscuro else mezcla(f, "#FFFFFF", 0.6),
        "apagado": mezcla(f, p, 0.5),
        "apagado_hover": mezcla(mezcla(f, p, 0.5), t, 0.06),
        "apagado_borde": mezcla(mezcla(f, p, 0.5), t, 0.08),
        "flotante": mezcla(f, p, 0.3),
        "barra_semana": mezcla(p, t, 0.2),
        "acento": a,
        "acento_hover": mezcla(a, "#FFFFFF", 0.2),
        "acento_pressed": mezcla(a, "#000000", 0.25),
        "sobre_acento": sobre(a),
        "seleccion": mezcla(a, f, 0.45),
        "escanear": e,
        "escanear_hover": mezcla(e, "#FFFFFF", 0.12),
        "escanear_pressed": mezcla(e, "#000000", 0.17),
        "sobre_escanear": sobre(e),
        "debug_fondo": "#2E7D32" if oscuro else "#B9E2BB",
        "debug_borde": "#4CAF50",
        "sombra_alfa": 230 if oscuro else 80,
    }
    c["link"] = legible(mezcla(a, extremo, 0.3), f, 4.5)
    c["link_hover"] = mezcla(c["link"], extremo, 0.35)
    c["sobre_seleccion"] = sobre(c["seleccion"])
    c["linea_hundido"] = mezcla(c["hundido"], t, 0.1)
    c["tirador"] = mezcla(t, extremo, 0.5)
    c["tirador_hover"] = mezcla(t, extremo, 0.85)
    # Avisos: el ámbar, el rojo y el verde de siempre, corregidos si el
    # fondo es claro y no se leerían.
    for nombre, color in (("aviso", "#F0C36B"), ("error", "#F48771"), ("ok", "#6FCF73")):
        c[nombre] = legible(color, f, 4.0)
    # El dorado del récord, en el panel de la semana.
    c["dorado"] = legible("#FFC83D", c["flotante"], 2.5)
    c["dorado_texto"] = legible("#FFE08A", c["flotante"], 3.0)
    return c


# La paleta en uso. Se actualiza en el lugar (usar), así quien la importó
# siempre lee la vigente.
PALETA = {}


def usar(colores):
    PALETA.clear()
    PALETA.update(paleta(colores))
    return PALETA


usar(POR_DEFECTO["colores"])


# --- Hoja de estilos ---

_HOJA = Template("""
QWidget {
    background-color: $fondo;
    color: $texto;
    font-family: 'Segoe UI', 'Roboto', 'Inter', sans-serif;
    font-size: 13px;
}
QToolTip {
    background-color: $flotante;
    color: $texto;
    border: 1px solid $borde;
    padding: 4px 6px;
}
QLineEdit {
    background-color: $paneles_hover;
    border: 1px solid $paneles_hover;
    border-radius: 4px;
    padding: 5px 10px;
    color: $texto2;
}
QLineEdit:focus {
    border: 1px solid $acento;
    background-color: $paneles_hover;
}
/* Desplegable plano, con el mismo aspecto que los botones secundarios.
   La flecha la dibuja FlatComboBox. */
QComboBox {
    background-color: $paneles;
    border: 1px solid $borde;
    border-radius: 6px;
    padding: 5px 30px 5px 10px;
    color: $texto2;
}
QComboBox:hover {
    background-color: $paneles_hover;
}
QComboBox:on {
    border: 1px solid $acento;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 28px;
}
QComboBox::down-arrow {
    image: none;
}
QComboBox QAbstractItemView {
    background-color: $flotante;
    border: 1px solid $borde;
    padding: 4px;
    outline: 0;
    color: $texto2;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding-left: 8px;
    border-radius: 4px;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background-color: $seleccion;
    color: $sobre_seleccion;
}
/* Barra de desplazamiento fina, sin flechas. */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: $scroll;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: $scroll_hover;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
#previewCanvas {
    background: transparent;
    border: none;
    color: $apagado_texto;
    font-size: 14px;
}
#destinoPath {
    color: $tenue;
}
#statusLine {
    color: $tenue2;
    font-size: 12px;
}
#linkButton {
    background: transparent;
    border: none;
    color: $link;
    padding: 2px 2px;
}
#linkButton:hover {
    color: $link_hover;
}
/* Contador de escaneos, al lado de Registro. Este es el gris de
   apagado; los colores de cada escalón los pone ContadorEscaneos. */
#contadorEscaneos {
    background-color: $apagado;
    color: $tenue2;
    border: 1px solid $apagado_borde;
    border-radius: 10px;
    min-width: 22px;
    padding: 1px 6px;
    font-size: 12px;
}
#contadorEscaneos:enabled:hover {
    background-color: $apagado_hover;
    color: $texto2;
    border: 1px solid $borde;
}
#mutedLabel {
    color: $tenue;
    font-size: 12px;
}
#valueLabel {
    color: $texto;
    font-size: 12px;
}
#captionInfo {
    color: $texto2;
    font-size: 12px;
}
#scanButton {
    background-color: $escanear;
    border: none;
    border-radius: 6px;
}
#scanButton:hover {
    background-color: $escanear_hover;
}
#scanButton:pressed {
    background-color: $escanear_pressed;
}
#scanButton:disabled {
    background-color: $paneles;
}
#scanText {
    background: transparent;
    color: $sobre_escanear;
    font-size: 15px;
    font-weight: bold;
}
#scanText:disabled {
    color: $tenue2;
}
#scanKey {
    background: transparent;
    color: $sobre_escanear;
    border: 1px solid $sobre_escanear;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 11px;
}
#scanKey:disabled {
    color: $tenue2;
    border: 1px solid $tenue2;
}
#secondaryButton:disabled {
    background-color: $apagado;
    border: 1px solid $apagado_borde;
}
#secondaryButton {
    background-color: $paneles;
    color: $texto2;
    border: 1px solid $borde;
    border-radius: 6px;
    padding: 6px 15px;
}
#secondaryButton:hover {
    background-color: $paneles_hover;
}
#debugButton, #infoButton, #temaButton {
    background-color: $paneles;
    border: 1px solid $borde;
    border-radius: 6px;
    font-size: 16px;
    padding: 5px 12px;
}
#infoButton {
    color: $texto2;
    font-size: 12px;
}
#debugButton:hover, #infoButton:hover, #temaButton:hover {
    background-color: $paneles_hover;
}
#updateButton {
    background-color: $acento;
    color: $sobre_acento;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
}
#updateButton:hover {
    background-color: $acento_hover;
}
#updateButton:disabled {
    background-color: $apagado;
    color: $apagado_texto;
}
#acercaTitulo {
    color: $titulo;
    font-size: 18px;
    font-weight: bold;
}
#debugButton:checked {
    background-color: $debug_fondo;
    border: 1px solid $debug_borde;
}
#novedades {
    background-color: $hundido;
    color: $texto2;
    border: 1px solid $linea_hundido;
    border-radius: 6px;
    padding: 4px 6px;
    font-size: 12px;
}
#consoleOutput {
    background-color: $hundido;
    color: $texto2;
    border: 1px solid $linea_hundido;
    border-radius: 6px;
    font-family: 'Consolas', monospace;
    font-size: 11px;
}
""")


def hoja(c=None):
    """La hoja de estilos de la ventana con la paleta `c` (la vigente si no se pasa)."""
    return _HOJA.substitute(c if c is not None else PALETA)
