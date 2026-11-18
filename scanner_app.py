import sys
import os
import stat
import time
import datetime
import glob
import json
import html
import math
import random
import threading

import actualizador
import temas
from temas import PALETA as C     # los colores del tema en uso (ver temas.py)


def run_selftest():
    """
    Verifica que las extensiones nativas carguen dentro del ejecutable
    empaquetado. Existe porque compilar sin error no garantiza que el .exe
    funcione: numpy y OpenCV cargan DLLs recien al importarse, y un fallo ahi
    solo aparece en tiempo de ejecucion.

    Escribe selftest.log junto al ejecutable y devuelve 0 si todo carga.
    Se usa en CI y sirve para diagnosticar una maquina concreta:
        LaBestia.exe --selftest
    """
    lineas, ok = [], True
    lineas.append(f"version  : {actualizador.VERSION}")
    lineas.append(f"python   : {sys.version.split()[0]}")
    lineas.append(f"ejecutable: {sys.executable}")
    lineas.append(f"congelado : {getattr(sys, 'frozen', False)}")

    modulos = ["numpy", "cv2", "PyQt6.QtCore", "PyQt6.QtSvg"]
    if sys.platform == "win32":
        modulos += ["win32com.client", "pythoncom"]

    for modulo in modulos:
        try:
            m = __import__(modulo)
            ver = getattr(m, "__version__", "sin version")
            lineas.append(f"OK   {modulo} {ver}")
        except Exception as e:
            ok = False
            lineas.append(f"FALLA {modulo}: {type(e).__name__}: {e}")

    # No alcanza con importar: numpy y cv2 cargan DLLs adicionales de forma
    # perezosa, asi que hay que ejercitarlas de verdad.
    if ok:
        try:
            import numpy as np, cv2
            a = np.ones((8, 8, 3), dtype=np.uint8) * 127
            g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            lineas.append(f"OK   operaciones numpy+cv2 (media {float(a.mean()):.1f})")
        except Exception as e:
            ok = False
            lineas.append(f"FALLA operaciones numpy+cv2: {type(e).__name__}: {e}")

    # fast_io lee el crudo y escribe el PNG por su cuenta (hilos + zlib): tiene
    # que venir empaquetado y dar lo mismo que OpenCV con las versiones del
    # ejecutable, que no son las de la maquina donde se desarrolla.
    if ok:
        try:
            import tempfile
            import numpy as np, cv2, fast_io
            a = np.random.default_rng(0).integers(0, 256, (1400, 2000, 3), dtype=np.uint8)
            a[200:600, 300:1500] = 230  # zona lisa: ejercita la otra estrategia de compresion
            with tempfile.TemporaryDirectory() as d:
                if not d.isascii():
                    # OpenCV en Windows no abre rutas con acentos; no es una
                    # falla del ejecutable.
                    lineas.append("OMITIDO fast_io: la carpeta temporal tiene caracteres no ASCII")
                else:
                    bmp, png = os.path.join(d, "selftest.bmp"), os.path.join(d, "selftest.png")
                    cv2.imwrite(bmp, a)
                    leida = fast_io.read_image(bmp)
                    fast_io.write_png(a, png)
                    vuelta = cv2.imread(png)
                    if (leida is None or not np.array_equal(leida, a)
                            or fast_io.image_size(bmp) != (2000, 1400)):
                        raise RuntimeError("la lectura del BMP no coincide con la imagen escrita")
                    if vuelta is None or not np.array_equal(vuelta, a):
                        raise RuntimeError("el PNG escrito no decodifica a la imagen original")
                    lineas.append(f"OK   fast_io (BMP y PNG de ida y vuelta, {os.path.getsize(png)} bytes)")
        except Exception as e:
            ok = False
            lineas.append(f"FALLA fast_io: {type(e).__name__}: {e}")

    # Las actualizaciones comparan versiones leyendo el recurso de versión del
    # ejecutable publicado: si el build no lo graba, ninguna PC se entera de
    # que hay una versión nueva.
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        grabada = actualizador.version_de_exe(sys.executable)
        if grabada == actualizador._tupla(actualizador.VERSION):
            lineas.append("OK   recurso de versión del ejecutable")
        else:
            ok = False
            lineas.append(f"FALLA recurso de versión: el ejecutable dice {grabada}, "
                          f"el programa {actualizador.VERSION}")

    lineas.append("RESULTADO: OK" if ok else "RESULTADO: FALLA")
    texto = "\n".join(lineas)
    print(texto)
    try:
        destino = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "selftest.log")
        with open(destino, "w", encoding="utf-8") as f:
            f.write(texto + "\n")
        print(f"(escrito en {destino})")
    except Exception:
        pass
    return 0 if ok else 1


if __name__ == "__main__" and "--selftest" in sys.argv:
    # Antes de los imports pesados a propósito: si numpy o PyQt6 no cargan,
    # este es el modo que tiene que seguir funcionando para poder reportarlo.
    sys.exit(run_selftest())

if __name__ == "__main__" and "--actualizar-desde" in sys.argv:
    # Actualizar sin abrir la ventana (ver actualizador.actualizar_desde).
    sys.exit(actualizador.actualizar_desde(
        sys.argv[sys.argv.index("--actualizar-desde") + 1]))


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QTextEdit, QFrame, QStyledItemDelegate,
    QDialog, QFileDialog, QGraphicsDropShadowEffect, QSpacerItem, QSizePolicy,
    QMessageBox, QColorDialog
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, pyqtSlot, QEvent, QSize, QRectF, QLineF,
    QByteArray, QVariantAnimation, QTimer, QPointF, QPoint, QRect, QEasingCurve,
    QTranslator, QLibraryInfo
)
from PyQt6.QtGui import (
    QFont, QColor, QPixmap, QImage, QKeySequence, QShortcut, QPainter, QBrush, QIcon,
    QPen, QPolygonF, QPainterPath, QRadialGradient, QFontMetricsF
)
from PyQt6.QtSvg import QSvgRenderer

# TWAIN eliminado. WIA se cargará dinámicamente usando win32com.client

def order_points(pts):
    import numpy as np
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def _detect_document(small_img, debug_dir=None):
    """
    Busca el contorno del documento probando varias estrategias en orden y
    devolviendo la primera que da algo plausible.

    Motivo de tener mas de una: Otsu parte el histograma en dos clases. Con el
    vidrio limpio (papel claro sobre tapa clara) el corte cae justo entre esos
    dos tonos parecidos y funciona. Con el vidrio sucio la mugre agrega un modo
    oscuro, Otsu corre el umbral hacia abajo, papel y fondo quedan del mismo
    lado y sale un unico blob del tamano de toda la imagen que el filtro de
    area descarta. De ahi el "No se detecto un documento claro" intermitente.
    """
    import cv2
    import numpy as np

    gray = cv2.cvtColor(small_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blurred = cv2.GaussianBlur(gray, (11, 11), 0)
    h, w = blurred.shape
    total_area = float(h * w)

    # Cada mascara se arma recien cuando la cascada llega a esa estrategia.
    # Casi siempre resuelve la primera, y Canny y el desvio del fondo costaban
    # la mitad del tiempo de esta funcion sin que nadie los mirara.

    # A) Otsu, las dos polaridades (el papel puede quedar en cualquiera de las
    #    dos clases segun de que lado caiga el umbral).
    def otsu():
        return cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    def otsu_inv():
        return cv2.bitwise_not(otsu())

    # B) Bordes: el canto del papel deja una sombra aunque el contraste de
    #    brillo entre papel y tapa sea casi nulo. No depende del histograma
    #    global, asi que la suciedad no lo corre.
    def canny():
        edges = cv2.Canny(blurred, 30, 90)
        return cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)

    # C) Desvio respecto del fondo de la cama, estimado con la mediana del
    #    marco exterior (ahi nunca hay documento).
    def fondo():
        border = np.concatenate([
            blurred[:10, :].ravel(), blurred[-10:, :].ravel(),
            blurred[:, :10].ravel(), blurred[:, -10:].ravel(),
        ])
        bed = int(np.median(border))
        diff = cv2.absdiff(blurred, np.full_like(blurred, bed))
        return cv2.threshold(diff, 12, 255, cv2.THRESH_BINARY)[1]

    strategies = [("otsu", otsu), ("otsu_inv", otsu_inv), ("canny", canny), ("fondo", fondo)]

    kernel = np.ones((5, 5), np.uint8)

    # Se guarda aparte el mejor candidato "flojo" (el que pasa el filtro de
    # area pero no el de rectangularidad). Solo se usa si ninguna estrategia
    # da un candidato bueno. Asi esta funcion nunca rechaza algo que el
    # algoritmo anterior habria aceptado: en el peor caso empata.
    flojo = None

    for name, armar_mascara in strategies:
        m = cv2.morphologyEx(armar_mascara(), cv2.MORPH_CLOSE, kernel, iterations=2)
        # Borde negro para despegar el papel que toque el limite de la imagen.
        # Se agrega por fuera en vez de pintarlo encima: pintado se comia 5 px
        # de la version reducida (unos 25 px del crudo) de cualquier documento
        # apoyado contra el borde. El offset devuelve los contornos a las
        # coordenadas sin borde.
        m = cv2.copyMakeBorder(m, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0)

        if debug_dir:
            cv2.imwrite(os.path.join(debug_dir, f"debug_mask_{name}.jpg"), m)

        contours, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE,
                                       offset=(-2, -2))

        estricto = None
        for c in contours:
            area = cv2.contourArea(c)
            if not (0.01 * total_area < area < 0.97 * total_area):
                continue

            if flojo is None or area > flojo[1]:
                flojo = (c, area, name + "/sin-filtrar")

            # El rectangulo minimo tiene que explicar bien el contorno: una
            # ficha lo llena, una veta de mugre o un blob irregular no.
            (_, (rw, rh), _) = cv2.minAreaRect(c)
            rect_area = rw * rh
            if rect_area <= 0 or (area / rect_area) < 0.75:
                continue
            if estricto is None or area > estricto[1]:
                estricto = (c, area)

        if estricto is not None:
            return estricto[0], name

    if flojo is not None:
        return flojo[0], flojo[2]

    return None, None


def _frame_margins(img):
    """
    Ancho del marco del escaner en cada borde del crudo: (arr, abj, izq, der).

    La captura de la cama completa trae en los bordes el labio del marco, una
    franja clara y pareja de punta a punta. Hay que sacarla: si queda, Otsu la
    pone del lado del papel y el documento que la toca se funde con ella.

    Antes se recortaba un porcentaje fijo, 64 px por lado a 300 dpi, cuando el
    marco real de la cama oficio mide unos 30 px. Una ficha de 20 cm en una
    cama de 21.6 cm tenia que caer en una ventana de 5 mm para no perder un
    borde.

    Una fila o columna es marco si es clara en practicamente todo su largo: un
    documento nunca la cubre entera, siempre asoma cama oscura en algun lado.
    El porcentaje viejo queda como tope, asi que nunca se recorta mas que antes.

    Solo se mira la franja de cada borde que llega hasta ese tope: lo que haya
    mas adentro no puede cambiar el resultado, y pasar a gris el crudo entero
    para leer cuatro franjas costaba 30 ms.
    """
    import cv2

    h, w = img.shape[:2]
    tope_v = int(round(h * 0.0233))
    tope_h = int(round(w * 0.0250))
    colchon = 3  # para la transicion entre el marco y la cama

    def racha(franja, eje, desde_el_final=False):
        # Cuantas filas (eje=1) o columnas (eje=0) seguidas son marco, contando
        # desde el borde de la imagen.
        if franja.size == 0:
            return 0
        claro = cv2.cvtColor(franja, cv2.COLOR_BGR2GRAY) > 100
        flags = claro.mean(axis=eje) > 0.98
        if desde_el_final:
            flags = flags[::-1]
        n = 0
        while n < len(flags) and flags[n]:
            n += 1
        return n

    def margen(n, tope):
        return min(n + colchon, tope) if n else 0

    return (margen(racha(img[:tope_v], 1), tope_v),
            margen(racha(img[h - tope_v:], 1, True), tope_v),
            margen(racha(img[:, :tope_h], 0), tope_h),
            margen(racha(img[:, w - tope_h:], 0, True), tope_h))


def _refine_rect(img, rect, alcance):
    """
    Ajusta el rectangulo del documento contra el crudo a resolucion completa.

    El contorno sale de una copia reducida a 800 px de alto, desenfocada y
    binarizada: cada pixel de ahi son unos 5 del crudo, asi que llega
    escalonado, con las esquinas redondeadas y corrido varios pixeles. El
    rectangulo que se le calcula encima hereda todo eso: en un crudo real se
    comia 5 px de papel arriba y abajo, hasta 11 a la derecha, y a la izquierda
    dejaba una cuna de cama.

    Aca ese rectangulo es solo el punto de partida. Sobre cada lado se toman
    perfiles perpendiculares en el crudo, en cada uno se ubica el paso de cama
    a papel con precision de subpixel y se ajusta una recta robusta: muescas,
    sellos y puntas rotas quedan afuera como atipicos. El angulo sale de esas
    rectas, pesando mas las que se midieron mejor (lado largo y prolijo).

    El resultado sigue siendo un rectangulo, el minimo que encierra los cuatro
    lados medidos. Una ficha cortada fuera de escuadra deja ver un poco de
    cama en vez de salir deformada o con un borde comido.

    rect: esquinas (tl, tr, br, bl) en coordenadas del crudo.
    alcance: cuantos px buscar a cada lado del borde aproximado.

    Devuelve (rect, lados_medidos). Un lado sin transicion clara (documento
    contra el marco, tapa del mismo tono que el papel) se deja como estaba, y
    con lados_medidos en 0 el rectangulo vuelve sin cambios.
    """
    import cv2
    import numpy as np

    alto, ancho = img.shape[:2]
    gris_entero = []  # el crudo completo en gris suavizado, si llega a hacer falta

    def gris_suavizado(mx, my):
        # Gris suavizado de la caja que tocan los perfiles de un lado, y el
        # origen de esa caja. Los perfiles leen unos 70.000 puntos pegados a
        # los lados; pasar a gris y suavizar los 10 megapixeles del crudo para
        # eso era casi todo el costo de esta funcion. El suavizado de 5x5 mira
        # 2 px a cada lado: con ese margen de mas, cada pixel que se lee vale
        # exactamente lo mismo que si se hubiera procesado el crudo entero.
        xa, xb = (int(np.clip(v, 0, ancho - 1)) for v in (np.floor(mx.min()), np.ceil(mx.max())))
        ya, yb = (int(np.clip(v, 0, alto - 1)) for v in (np.floor(my.min()), np.ceil(my.max())))
        x0, x1 = max(xa - 2, 0), min(xb + 3, ancho)
        y0, y1 = max(ya - 2, 0), min(yb + 3, alto)
        if 4 * (x1 - x0) * (y1 - y0) > ancho * alto:
            # Documento muy girado: las cajas de los cuatro lados juntas ya
            # ocupan mas que el crudo, conviene procesarlo entero una vez.
            if not gris_entero:
                gris_entero.append(cv2.GaussianBlur(
                    cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0))
            return gris_entero[0], 0, 0
        caja = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(caja, (5, 5), 0), x0, y0

    rect = np.asarray(rect, dtype=np.float64)
    sin_cambios = (rect.astype(np.float32), 0)
    centro = rect.mean(axis=0)
    offs = np.arange(-alcance, alcance + 1, dtype=np.float64)
    tol = 2.0      # px que un punto puede apartarse de la recta de su lado
    colchon = 2.0  # px de cama que se dejan alrededor, para no morder el canto

    def ajustar(t, o):
        # Arranque con medianas (aguanta atipicos) y despues minimos cuadrados
        # solo sobre los puntos que quedaron cerca.
        m = len(t) // 2
        b = float(np.median((o[m:2 * m] - o[:m]) / (t[m:2 * m] - t[:m])))
        a = float(np.median(o - b * t))
        ok = np.abs(o - (a + b * t)) <= tol
        for _ in range(3):
            if ok.sum() < 2:
                break
            b, a = np.polyfit(t[ok], o[ok], 1)
            ok = np.abs(o - (a + b * t)) <= tol
        return a, b, ok

    rectas = []  # por lado: (punto, direccion)
    giros = []   # por lado medido: (pendiente respecto del lado aproximado, peso)
    ejes = None
    for i in range(4):
        p0, p1 = rect[i], rect[(i + 1) % 4]
        largo = float(np.linalg.norm(p1 - p0))
        if largo < 1:
            return sin_cambios
        d = (p1 - p0) / largo
        n = np.array([-d[1], d[0]])
        if np.dot(centro - p0, n) < 0:
            n = -n  # normal hacia adentro del documento
        if ejes is None:
            ejes = (d, n)
        recta = (p0, d)

        # Las puntas no se miran: ahi estan las esquinas redondeadas o rotas.
        margen = max(0.05 * largo, 2 * alcance)
        ts = np.arange(margen, largo - margen, 6.0)
        if len(ts) >= 20:
            base = p0[None, :] + ts[:, None] * d[None, :]
            mx = (base[:, 0:1] + offs[None, :] * n[0]).astype(np.float32)
            my = (base[:, 1:2] + offs[None, :] * n[1]).astype(np.float32)
            # Una fila por perfil, de afuera (columna 0) hacia adentro.
            gray, x0, y0 = gris_suavizado(mx, my)
            tira = cv2.remap(gray, mx - np.float32(x0), my - np.float32(y0),
                             cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE).astype(np.float64)

            q = max(alcance // 2, 1)
            afuera = float(np.median(tira[:, :q]))
            adentro = float(np.median(tira[:, -q:]))
            if abs(adentro - afuera) >= 25:
                # Primer cruce del nivel medio viniendo de afuera: el canto
                # del papel y no una linea impresa mas adentro.
                medio = (afuera + adentro) / 2.0
                sobre = (tira > medio) if adentro > afuera else (tira < medio)
                idx = sobre.argmax(axis=1)
                r = np.nonzero(sobre.any(axis=1) & (idx > 0))[0]
                if len(r) >= 20:
                    v0, v1 = tira[r, idx[r] - 1], tira[r, idx[r]]
                    pos = offs[idx[r] - 1] + (medio - v0) / (v1 - v0)
                    a, b, ok = ajustar(ts[r], pos)
                    if ok.sum() >= 0.6 * len(ts):
                        t_ok = ts[r][ok]
                        resid = pos[ok] - (a + b * t_ok)
                        # Inversa de la varianza de la pendiente ajustada.
                        peso = ((t_ok - t_ok.mean()) ** 2).sum() / max(resid.var(), 0.05)
                        giros.append((b, peso))
                        dd = d + n * b
                        recta = (p0 + n * a, dd / np.linalg.norm(dd))
        rectas.append(recta)

    if not giros:
        return sin_cambios

    # Esquinas: cruce de cada lado con el anterior.
    esquinas = np.zeros((4, 2))
    for i in range(4):
        (a1, d1), (a2, d2) = rectas[i - 1], rectas[i]
        try:
            k = np.linalg.solve(np.array([d1, -d2]).T, a2 - a1)
        except np.linalg.LinAlgError:
            return sin_cambios
        esquinas[i] = a1 + k[0] * d1
    if np.linalg.norm(esquinas - rect, axis=1).max() > 2 * alcance:
        return sin_cambios

    pendientes, pesos = zip(*giros)
    giro = np.arctan(np.average(pendientes, weights=pesos))
    d, n = ejes
    u = d * np.cos(giro) + n * np.sin(giro)
    v = n * np.cos(giro) - d * np.sin(giro)
    pu = (esquinas - centro) @ u
    pv = (esquinas - centro) @ v
    u0, u1 = pu.min() - colchon, pu.max() + colchon
    v0, v1 = pv.min() - colchon, pv.max() + colchon
    nuevo = centro + np.array([u0 * u + v0 * v, u1 * u + v0 * v,
                               u1 * u + v1 * v, u0 * u + v1 * v])
    return nuevo.astype(np.float32), len(giros)


def process_and_crop(input_path, output_path, log_signal=None, debug_mode=False):
    """
    Procesa la imagen escaneada. Devuelve (ruta_final, detectado); "detectado"
    en False significa que se guardo la cama completa como fallback.
    """
    ruta, detectado, _ = process_and_crop_image(input_path, output_path, log_signal, debug_mode)
    return ruta, detectado


def process_and_crop_image(input_path, output_path, log_signal=None, debug_mode=False):
    """
    Procesa la imagen escaneada mediante una transformacion de perspectiva.
    Optimizado: Reduce la resolucion para hallar contornos rapido y aplica el
    recorte en alta res. Recorta el marco plastico del escaner, medido en cada
    crudo.

    Devuelve (ruta_final, detectado, imagen). "detectado" en False significa
    que se guardo la cama completa como fallback. "imagen" son los pixeles que
    quedaron en el archivo (BGR), para poder mostrarlos sin volver a leerlo y
    decodificarlo; es None cuando no se pudo procesar nada.
    """
    output_path_png = output_path.replace('.jpg', '.png')
    try:
        import cv2
        import numpy as np
        import fast_io
        img = fast_io.read_image(input_path)
        if img is None:
            return input_path, False, None

        # 1. Sacar el marco fisico del escaner, medido en este crudo en vez de
        #    un porcentaje fijo (ver _frame_margins).
        h_orig, w_orig = img.shape[:2]
        top, bottom, left, right = _frame_margins(img)
        img = img[top:h_orig - bottom, left:w_orig - right]
        if debug_mode and log_signal:
            log_signal.emit(
                f"Marco recortado: izq {left}, der {right}, arr {top}, abj {bottom} px."
            )

        # 2. Bajar la resolucion temporalmente para procesar rapido. orig es el
        #    mismo recorte, sin copiar: de aca en adelante solo se lee, y la
        #    copia eran 30 MB por escaneo.
        ratio = img.shape[0] / 800.0
        orig = img

        if ratio > 1:
            small_img = cv2.resize(img, (int(img.shape[1] / ratio), 800))
        else:
            small_img = img.copy()
            ratio = 1.0

        debug_dir = os.path.dirname(output_path) if debug_mode else None
        c, strategy = _detect_document(small_img, debug_dir)

        if c is not None:
            # Ajustar contorno a la escala original. Cada eje con su factor (el
            # ancho reducido se trunca a entero, asi que no es exactamente
            # ratio) y por el centro del pixel: escalando el indice a secas,
            # los bordes derecho e inferior quedaban unos 5 px hacia adentro.
            escala = (orig.shape[1] / small_img.shape[1],
                      orig.shape[0] / small_img.shape[0])
            c = np.round((c + 0.5) * escala - 0.5).astype(np.int32)

            # Si el documento llega al borde de lo escaneado, lo que siga por
            # debajo del marco se perdio y no hay procesamiento que lo
            # recupere: hay que avisar para que lo corran.
            bx, by, bw, bh = cv2.boundingRect(c)
            tol = int(round(3 * ratio))
            lados = [lado for lado, toca in (
                ("izquierdo", bx <= tol),
                ("derecho", bx + bw >= orig.shape[1] - tol),
                ("superior", by <= tol),
                ("inferior", by + bh >= orig.shape[0] - tol),
            ) if toca]
            if lados and log_signal:
                log_signal.emit(
                    f"AVISO: el documento toca el borde {' y '.join(lados)} de la cama. "
                    f"Si ahí se cortó, correlo unos milímetros hacia adentro."
                )

            # El contorno da un rectangulo aproximado; los lados se miden de
            # nuevo sobre el crudo (ver _refine_rect).
            box = cv2.boxPoints(cv2.minAreaRect(c))
            rect = order_points(np.array(box, dtype=np.float32).reshape(4, 2))
            rect, lados_medidos = _refine_rect(orig, rect, int(round(6 * ratio)))
            (tl, tr, br, bl) = rect

            if debug_mode:
                # Rojo fino: el contorno aproximado. Verde: el recorte final.
                debug_img = orig.copy()
                cv2.drawContours(debug_img, [c], -1, (0, 0, 255), 2)
                cv2.polylines(debug_img, [np.round(rect).astype(np.int32)], True,
                              (0, 255, 0), 4)
                cv2.imwrite(os.path.join(debug_dir, "debug_4_contour.jpg"), debug_img)
                if log_signal:
                    log_signal.emit(f"Lados medidos sobre el crudo: {lados_medidos} de 4.")

            ancho = float(np.linalg.norm(tr - tl))
            alto = float(np.linalg.norm(bl - tl))
            maxWidth = int(round(ancho)) + 1
            maxHeight = int(round(alto)) + 1

            # Escala 1:1 exacta: cada esquina va a su distancia real, sin
            # estirar para que coincida con el ultimo pixel.
            dst = np.array([
                [0, 0],
                [ancho, 0],
                [ancho, alto],
                [0, alto]], dtype="float32")

            # Cubica: el recorte ya no cae en pixeles enteros y la bilineal
            # ablanda el trazo fino cuando interpola a medio pixel.
            M = cv2.getPerspectiveTransform(rect, dst)
            warped = cv2.warpPerspective(orig, M, (maxWidth, maxHeight),
                                         flags=cv2.INTER_CUBIC)

            if warped.size > 0:
                fast_io.write_png(warped, output_path_png)
                if log_signal:
                    log_signal.emit(
                        f"Documento detectado ({strategy}), enderezado y guardado "
                        f"sin perdida: {maxWidth}x{maxHeight} px."
                    )
                return output_path_png, True, warped

        # Fallback: ninguna estrategia encontro el documento. Se guarda la cama
        # entera, asi que el documento queda ocupando solo una fraccion del
        # archivo: parece "de menor resolucion" aunque el dpi haya sido el
        # correcto. Causa tipica: vidrio sucio.
        if log_signal:
            log_signal.emit(
                f"AVISO: no se detecto el documento con ninguna estrategia. Se guarda "
                f"la cama completa ({img.shape[1]}x{img.shape[0]} px), el documento va "
                f"a quedar mas chico dentro del archivo. Revisa que el vidrio este limpio."
            )
        fast_io.write_png(img, output_path_png)
        return output_path_png, False, img
    except Exception as e:
        if log_signal:
            log_signal.emit(f"Error en procesamiento: {e}")
        return input_path, False, None


# --- WIA: control directo de la captura -------------------------------------
# Antes la resolucion se fijaba tipeando "300" a ciegas con SendKeys sobre el
# dialogo nativo, con sleeps fijos y solo en el primer escaneo. Si el dialogo
# tardaba mas de 0.5 s en aparecer, las teclas caian en cualquier lado y el
# escaner se quedaba con su default (150 dpi o menos). Esa era la causa real de
# los escaneos intermitentes en baja resolucion.

WIA_FORMAT_BMP = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"

# Propiedades del item de captura
WIA_IPA_DATATYPE        = 4103   # 0=BN, 2=grises, 3=color RGB
WIA_IPS_CUR_INTENT      = 6146
WIA_IPS_XRES            = 6147
WIA_IPS_YRES            = 6148
WIA_IPS_XPOS            = 6149
WIA_IPS_YPOS            = 6150
WIA_IPS_XEXTENT         = 6151
WIA_IPS_YEXTENT         = 6152

# Propiedades del dispositivo (tamano de la cama, en milesimas de pulgada)
WIA_DPS_HORIZONTAL_BED_SIZE = 3074
WIA_DPS_VERTICAL_BED_SIZE   = 3075

WIA_INTENT_COLOR            = 1
WIA_INTENT_MAXIMIZE_QUALITY = 131072
WIA_INTENT_MINIMIZE_SIZE    = 65536

SCAN_DPI = 300  # valor por defecto; se cambia con la barra de calidad
# Resoluciones que ofrece la barra. Son las que casi cualquier driver WIA
# acepta; si el escaner rechaza una, la captura directa lo informa en el log.
DPI_OPCIONES = (100, 150, 200, 300, 400, 600)


def _wia_prop(collection, prop_id):
    for p in collection:
        try:
            if p.PropertyID == prop_id:
                return p
        except Exception:
            continue
    return None


def _wia_get(collection, prop_id, default=None):
    p = _wia_prop(collection, prop_id)
    if p is None:
        return default
    try:
        return p.Value
    except Exception:
        return default


def _wia_set(collection, prop_id, value):
    """Escribe una propiedad WIA y devuelve el valor que realmente quedo."""
    p = _wia_prop(collection, prop_id)
    if p is None:
        return None
    try:
        p.Value = value
    except Exception:
        pass
    try:
        return p.Value
    except Exception:
        return None


def acquire_wia_direct(dev_info, raw_path, dpi=SCAN_DPI, log_signal=None):
    """
    Escanea fijando la resolucion por propiedades, sin dialogo ni SendKeys.
    Devuelve (ancho, alto) en pixeles. Lanza excepcion si el driver no acepta
    la resolucion pedida, para que el llamador pueda caer al camino viejo.
    """
    device = dev_info.Connect()
    if device.Items.Count < 1:
        raise RuntimeError("el escaner no expone ningun item de captura")

    item = device.Items(1)
    props = item.Properties

    # 1) Intencion primero: varios drivers resetean la resolucion al cambiarla.
    _wia_set(props, WIA_IPS_CUR_INTENT, WIA_INTENT_COLOR | WIA_INTENT_MAXIMIZE_QUALITY)
    _wia_set(props, WIA_IPA_DATATYPE, 3)

    # 2) Resolucion, verificando que el driver la haya aceptado de verdad
    real_x = _wia_set(props, WIA_IPS_XRES, dpi)
    real_y = _wia_set(props, WIA_IPS_YRES, dpi)
    if real_x != dpi or real_y != dpi:
        raise RuntimeError(f"el driver no acepto {dpi} dpi (quedo en {real_x}x{real_y})")

    # 3) Area de escaneo. Cambiar la resolucion no siempre reescala el extent:
    #    si queda el extent viejo (en pixeles) se escanea solo un pedazo de la
    #    cama. Por eso se recalcula explicitamente desde el tamano fisico.
    bed_x = _wia_get(device.Properties, WIA_DPS_HORIZONTAL_BED_SIZE)
    bed_y = _wia_get(device.Properties, WIA_DPS_VERTICAL_BED_SIZE)
    if bed_x and bed_y:
        _wia_set(props, WIA_IPS_XPOS, 0)
        _wia_set(props, WIA_IPS_YPOS, 0)
        _wia_set(props, WIA_IPS_XEXTENT, int(bed_x * dpi / 1000))
        _wia_set(props, WIA_IPS_YEXTENT, int(bed_y * dpi / 1000))

    image = item.Transfer(WIA_FORMAT_BMP)
    if os.path.exists(raw_path):
        os.remove(raw_path)
    image.SaveFile(raw_path)

    return int(image.Width), int(image.Height)


def _pick_device_info(dev_manager, scanner_name):
    """Devuelve el DeviceInfo elegido en el combo, o el primer escaner."""
    fallback = None
    for i in range(1, dev_manager.DeviceInfos.Count + 1):
        dev_info = dev_manager.DeviceInfos(i)
        try:
            if dev_info.Type != 1:  # 1 = escaner
                continue
        except Exception:
            continue
        if fallback is None:
            fallback = dev_info
        if scanner_name and scanner_name != "Auto-Detectar":
            for p in dev_info.Properties:
                try:
                    if p.Name == "Name" and p.Value == scanner_name:
                        return dev_info
                except Exception:
                    continue
    return fallback


def _warn_if_low_res(raw_path, expected_dpi, log_signal):
    """
    Compara el tamano real del crudo contra lo esperado y avisa. Sin esto, una
    caida de dpi pasa desapercibida hasta que alguien mira el archivo.
    """
    try:
        # Solo el encabezado: decodificar los 32 MB del crudo para saber su
        # tamano duplicaba el tiempo de lectura de cada escaneo.
        import fast_io
        size = fast_io.image_size(raw_path)
        if size is None:
            return
        w, h = size
        long_side = max(w, h)
        # Una cama de tamano carta/oficio da al menos 10 pulgadas de lado largo
        est_dpi = long_side / 10.0
        if long_side < expected_dpi * 7:
            log_signal.emit(
                f"AVISO: el crudo salio {w}x{h} px (~{est_dpi:.0f} dpi estimados), "
                f"muy por debajo de los {expected_dpi} dpi esperados."
            )
        else:
            log_signal.emit(f"Crudo recibido: {w}x{h} px.")
    except Exception:
        pass


# --- Borrado del crudo ------------------------------------------------------
# El crudo se escribe, se lee y se borra en un par de segundos, casi siempre en
# una carpeta de red. En algunas PCs Windows rechaza ese borrado con "Acceso
# denegado" aunque el permiso esté: pasa cuando otro programa (antivirus,
# indexador, el Explorador con la carpeta abierta) toma el archivo apenas
# aparece. Antes eso se reportaba como error del escaneo, con el PNG ya
# guardado, y el crudo quedaba en la carpeta.

# Crudos que no se pudieron borrar al terminar su escaneo. Se vuelve a probar
# al empezar el siguiente y al cerrar el programa.
_crudos_pendientes = []


def _borrar_crudo(path, intentos=6, espera=0.2):
    """
    Borra el crudo, insistiendo hasta un segundo si Windows no deja. Devuelve
    None si el archivo ya no está, o el error del último intento.
    """
    error = None
    for i in range(intentos):
        if i:
            time.sleep(espera)
        try:
            os.remove(path)
            return None
        except FileNotFoundError:
            return None
        except OSError as e:
            error = e
            if i == 0:
                # Un archivo de solo lectura da el mismo "Acceso denegado".
                try:
                    os.chmod(path, stat.S_IWRITE)
                except OSError:
                    pass
    return error


def _limpiar_crudos_pendientes(log_signal=None):
    """Segundo y último intento para los crudos que quedaron sin borrar."""
    pendientes = _crudos_pendientes[:]
    del _crudos_pendientes[:]
    for path in pendientes:
        error = _borrar_crudo(path, intentos=1)
        if error is not None and log_signal:
            log_signal.emit(
                f"AVISO: no se pudo borrar {os.path.basename(path)} "
                f"({error.strerror or error}). Hay que borrarlo a mano."
            )


def to_qimage(img):
    """
    La imagen procesada (ndarray BGR de 8 bits) como QImage lista para mostrar,
    o None si no hay imagen o no tiene ese formato.

    Se puede llamar desde el hilo de escaneo: QImage no depende del hilo de la
    ventana. La conversion copia los pixeles, asi que el resultado no queda
    atado al ndarray.
    """
    if img is None or img.ndim != 3 or img.shape[2] != 3 or img.dtype.name != "uint8":
        return None
    import numpy as np
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    vista = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888)
    return vista.convertToFormat(QImage.Format.Format_RGB32)


class ScannerThread(QThread):
    log_signal = pyqtSignal(str)
    # ruta final, documento detectado, imagen ya lista para mostrar (QImage o None)
    image_signal = pyqtSignal(str, bool, object)
    finished_signal = pyqtSignal()

    def __init__(self, scanner_name, output_path, debug_mode, is_first_scan=False,
                 manual_mode=False, dpi=SCAN_DPI):
        super().__init__()
        self.scanner_name = scanner_name
        self.output_path = output_path
        self.debug_mode = debug_mode
        self.is_first_scan = is_first_scan
        self.dpi = dpi
        self.manual_mode = manual_mode

    def run(self):
        self.log_signal.emit(f"Iniciando escaneo... Guardará en {os.path.basename(self.output_path)}")
        base, ext = os.path.splitext(self.output_path)
        raw_path = f"{base}_raw.bmp"
        _limpiar_crudos_pendientes(self.log_signal)

        try:
            import win32com.client
            import pythoncom

            # WIA utiliza COM, inicializar en el hilo actual
            pythoncom.CoInitialize()

            dev_manager = win32com.client.Dispatch("WIA.DeviceManager")
            if dev_manager.DeviceInfos.Count == 0:
                self.log_signal.emit("Error: No se detectó ningún escáner conectado. Conecta el USB y espera a que Windows lo reconozca.")
                self.finished_signal.emit()
                pythoncom.CoUninitialize()
                return

            acquired = False

            # --- Camino principal: captura directa, resolución determinística ---
            if not self.manual_mode:
                dev_info = _pick_device_info(dev_manager, self.scanner_name)
                if dev_info is None:
                    self.log_signal.emit("No se encontró un escáner utilizable.")
                else:
                    try:
                        w, h = acquire_wia_direct(dev_info, raw_path, self.dpi, self.log_signal)
                        self.log_signal.emit(f"Captura directa WIA a {self.dpi} dpi: {w}x{h} px.")
                        acquired = True
                    except Exception as e:
                        self.log_signal.emit(
                            f"Captura directa no disponible ({e}). Cayendo al diálogo nativo."
                        )

            # --- Fallback: diálogo nativo (y modo manual) ---
            if not acquired:
                import threading
                dpi = self.dpi

                def auto_clicker(first_scan):
                    import time
                    time.sleep(0.5)
                    try:
                        import win32com.client
                        shell = win32com.client.Dispatch("WScript.Shell")
                        shell.SendKeys("{TAB}")
                        time.sleep(0.1)
                        shell.SendKeys("{DOWN 3}")
                        time.sleep(0.1)

                        if first_scan:
                            # Entrar a propiedades avanzadas
                            shell.SendKeys("{TAB}")
                            time.sleep(0.1)
                            shell.SendKeys(" ")
                            time.sleep(0.8)  # Esperar ventana

                            # Cambiar DPI a 300 (4 tabs)
                            for _ in range(4):
                                shell.SendKeys("{TAB}")
                                time.sleep(0.1)
                            shell.SendKeys(str(dpi))
                            time.sleep(0.1)
                            shell.SendKeys("{ENTER}")
                            time.sleep(0.8)  # Esperar cierre de ventana

                            # Tab y Enter para lanzar escaneo
                            shell.SendKeys("{TAB}")
                            time.sleep(0.1)
                            shell.SendKeys("{ENTER}")
                        else:
                            shell.SendKeys("{ENTER}")

                    except Exception:
                        pass

                if not self.manual_mode:
                    threading.Thread(target=auto_clicker, args=(self.is_first_scan,), daemon=True).start()
                    self.log_signal.emit("Robot activado: Seleccionará 'Configuración personalizada'...")
                else:
                    self.log_signal.emit("Modo manual: Interactúa con la ventana del escáner libremente.")

                common_dialog = win32com.client.Dispatch("WIA.CommonDialog")
                self.log_signal.emit("Solicitando captura al motor nativo de Windows (WIA)...")
                # Bias = MAXIMIZE_QUALITY. Antes era 65536 (MINIMIZE_SIZE), que le
                # pedía al driver priorizar archivo chico, o sea baja resolución.
                image = common_dialog.ShowAcquireImage(
                    1, WIA_INTENT_COLOR, WIA_INTENT_MAXIMIZE_QUALITY,
                    WIA_FORMAT_BMP, False, True, False
                )

                if image:
                    if os.path.exists(raw_path):
                        os.remove(raw_path)
                    image.SaveFile(raw_path)
                    acquired = True
                else:
                    self.log_signal.emit("Escaneo cancelado.")

            if acquired:
                _warn_if_low_res(raw_path, self.dpi, self.log_signal)

                self.log_signal.emit("Procesando imagen (Enderezado y recorte automático)...")
                final_path, detectado, imagen = process_and_crop_image(
                    raw_path, self.output_path, self.log_signal, self.debug_mode
                )
                # La imagen se manda ya convertida, desde este hilo. Si la
                # ventana tuviera que releer y decodificar el PNG recién
                # guardado, se congelaría unos 75 ms por escaneo (200 con la
                # cama completa).
                if final_path:
                    self.image_signal.emit(final_path, detectado, to_qimage(imagen))

                if os.path.exists(raw_path) and raw_path != final_path:
                    if detectado:
                        error = _borrar_crudo(raw_path)
                        if error is not None:
                            # El escaneo salió bien: no es un error ni un aviso.
                            _crudos_pendientes.append(raw_path)
                            self.log_signal.emit(
                                f"Todavía no se pudo borrar {os.path.basename(raw_path)} "
                                f"({error.strerror or error}): se vuelve a intentar "
                                f"en el próximo escaneo."
                            )
                    else:
                        # No se borra: sin el crudo del escaneo que fallo no hay
                        # forma de averiguar por que fallo la deteccion.
                        self.log_signal.emit(
                            f"Se conservó el crudo del escaneo fallido en "
                            f"{os.path.basename(raw_path)} para diagnóstico."
                        )

            pythoncom.CoUninitialize()

        except Exception as e:
            self.log_signal.emit(f"Error durante el escaneo WIA: {str(e)}")

        finally:
            self.finished_signal.emit()




# --- Configuracion persistente ----------------------------------------------
# El destino elegido en el diálogo se guardaba solo en memoria: al reiniciar,
# la app volvía al H:\see\... hardcodeado y había que reconfigurarla siempre.

DEFAULT_OUTPUT_DIR = r"H:\see\imagenes_fallecidos\incoming"
DEFAULT_PREFIX = "doc_"


def _config_path():
    r"""
    %APPDATA%\LaBestia\config.json en Windows, ~ como fallback.
    No se guarda junto al .exe a propósito: empaquetado con PyInstaller puede
    quedar en Program Files, donde el usuario no tiene permiso de escritura.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    carpeta = os.path.join(base, "LaBestia")
    try:
        os.makedirs(carpeta, exist_ok=True)
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".la_bestia.json")
    return os.path.join(carpeta, "config.json")


def _old_config_paths():
    """Dónde guardaba la configuración la app cuando se llamaba Antigravity Scanner."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return [os.path.join(base, "AntigravityScanner", "config.json"),
            os.path.join(os.path.expanduser("~"), ".antigravity_scanner.json")]


def load_config():
    # Primero la ubicación actual; si todavía no existe, la del nombre viejo.
    # Sin esto, un equipo ya configurado volvería a los valores por defecto al
    # actualizar, y empezaría a guardar los escaneos en otra carpeta. Lo
    # primero que se guarde después ya va a la ubicación nueva.
    for ruta in [_config_path()] + _old_config_paths():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg
        except Exception:
            continue
    return {}


def save_config(**cambios):
    """
    Guarda solo las claves que se pasan y conserva el resto. Importa cuando el
    destino configurado no esta disponible: cambiar la calidad en ese momento
    no tiene que pisar la carpeta guardada con la temporal.

    Devuelve (ok, detalle) para poder informarlo en el log.
    """
    try:
        cfg = load_config()
        cfg.update(cambios)
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True, _config_path()
    except Exception as e:
        return False, str(e)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_dir="", current_prefix=""):
        super().__init__(parent)
        self.setWindowTitle("Cambiar destino")
        self.setFixedSize(480, 250)
        self.setStyleSheet(parent.styleSheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(4)
        titulo = QLabel("Destino de los escaneos")
        titulo.setObjectName("acercaTitulo")
        layout.addWidget(titulo)
        layout.addSpacing(14)

        # Carpeta
        lbl_dir = QLabel("Carpeta")
        lbl_dir.setObjectName("mutedLabel")
        layout.addWidget(lbl_dir)
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(8)
        self.txt_dir = QLineEdit(os.path.normpath(current_dir) if current_dir else "")
        btn_browse = QPushButton(" Elegir…")
        btn_browse.setIcon(icon("carpeta", C["texto2"]))
        btn_browse.setIconSize(QSize(16, 16))
        btn_browse.setObjectName("secondaryButton")
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self.browse_dir)
        dir_layout.addWidget(self.txt_dir, stretch=1)
        dir_layout.addWidget(btn_browse)
        layout.addLayout(dir_layout)
        layout.addSpacing(10)

        # Prefijo
        lbl_prefix = QLabel("Prefijo del nombre de archivo")
        lbl_prefix.setObjectName("mutedLabel")
        layout.addWidget(lbl_prefix)
        self.txt_prefix = QLineEdit(current_prefix)
        layout.addWidget(self.txt_prefix)

        layout.addStretch()

        # Botones, con el mismo par que "Acerca de": secundario y azul.
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("secondaryButton")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(" Guardar")
        btn_ok.setIcon(icon("tilde", C["sobre_acento"]))
        btn_ok.setIconSize(QSize(16, 16))
        btn_ok.setObjectName("updateButton")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def browse_dir(self):
        # Arranca en la carpeta que ya está escrita, no en la de trabajo.
        d = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", self.txt_dir.text())
        if d:
            self.txt_dir.setText(os.path.normpath(d))


class AcercaDialog(QDialog):
    """
    La versión del programa y las actualizaciones. Solo muestra: el estado y
    las acciones son de la ventana principal, que lo refresca cuando cambian.
    """

    def __init__(self, ventana):
        super().__init__(ventana)
        self.ventana = ventana
        self.setWindowTitle("Acerca de La bestia")
        self.setFixedSize(460, 440)
        self.setStyleSheet(ventana.styleSheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(4)
        titulo = QLabel("La bestia")
        titulo.setObjectName("acercaTitulo")
        version = QLabel(f"Versión {actualizador.VERSION}")
        version.setObjectName("mutedLabel")
        layout.addWidget(titulo)
        layout.addWidget(version)
        layout.addSpacing(14)

        # El estado de las actualizaciones, con una ruedita mientras hay algo
        # en curso. Alto fijo para que los botones no salten cuando el texto
        # pasa de una línea a dos.
        self.spinner = Spinner(16)
        self.lbl_estado = QLabel()
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        estado = QHBoxLayout()
        estado.setSpacing(8)
        estado.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignTop)
        estado.addWidget(self.lbl_estado, stretch=1)
        caja_estado = QWidget()
        caja_estado.setFixedHeight(56)
        caja_estado.setLayout(estado)
        estado.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(caja_estado)

        self.btn_buscar = QPushButton(" Buscar actualizaciones")
        self.btn_buscar.setIcon(icon("refrescar", C["texto2"]))
        self.btn_buscar.setIconSize(QSize(16, 16))
        self.btn_buscar.setObjectName("secondaryButton")
        self.btn_buscar.clicked.connect(ventana.check_updates)
        self.btn_actualizar = QPushButton(" Actualizar ahora")
        self.btn_actualizar.setIcon(icon("descargar", C["sobre_acento"]))
        self.btn_actualizar.setIconSize(QSize(16, 16))
        self.btn_actualizar.setObjectName("updateButton")
        self.btn_actualizar.clicked.connect(ventana.start_update)
        botones = QHBoxLayout()
        botones.addWidget(self.btn_buscar)
        botones.addStretch()
        botones.addWidget(self.btn_actualizar)
        layout.addLayout(botones)

        layout.addSpacing(16)
        lbl_novedades = QLabel("Novedades")
        lbl_novedades.setObjectName("mutedLabel")
        layout.addWidget(lbl_novedades)
        layout.addSpacing(4)
        self.novedades = QTextEdit()
        self.novedades.setObjectName("novedades")
        self.novedades.setReadOnly(True)
        self.novedades.setHtml(self.html_novedades())
        layout.addWidget(self.novedades, stretch=1)
        self.refrescar()

    @staticmethod
    def html_novedades():
        """Las novedades de cada versión, la más nueva primero."""
        partes = []
        for version, cambios in actualizador.NOVEDADES:
            actual = " (esta)" if version == actualizador.VERSION else ""
            items = "".join(f"<li>{html.escape(c)}</li>" for c in cambios)
            partes.append(
                f"<p style='margin: 6px 0 2px 0; color: {C['titulo']}; font-weight: bold;'>"
                f"{version}{actual}</p>"
                f"<ul style='margin: 0 0 6px -18px;'>{items}</ul>"
            )
        return "".join(partes)

    def refrescar(self):
        texto, ocupado, se_puede = self.ventana.estado_actualizacion()
        self.lbl_estado.setText(texto)
        self.btn_buscar.setEnabled(not ocupado)
        self.btn_actualizar.setVisible(se_puede)
        if ocupado:
            self.spinner.start()
        else:
            self.spinner.stop()

# Iconos de linea (trazos de Tabler Icons, licencia MIT), en una grilla de
# 24x24. Reemplazan a los emoji, que cada version de Windows dibuja distinto y
# a color. Se guardan como texto y se pintan con el color que haga falta.
ICONOS = {
    "carpeta": '<path d="M5 4h4l3 3h7a2 2 0 0 1 2 2v8a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-11a2 2 0 0 1 2 -2"/>',
    "archivo": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
               '<path d="M5 13v-8a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2h-5.5m-9.5 -2h7m-3 -3l3 3l-3 3"/>',
    "bicho": '<path d="M9 9v-1a3 3 0 0 1 6 0v1"/>'
             '<path d="M8 9h8a6 6 0 0 1 1 3v3a5 5 0 0 1 -10 0v-3a6 6 0 0 1 1 -3"/>'
             '<path d="M3 13l4 0"/><path d="M17 13l4 0"/><path d="M12 20l0 -6"/>'
             '<path d="M4 19l3.35 -2"/><path d="M20 19l-3.35 -2"/>'
             '<path d="M4 7l3.75 2.4"/><path d="M20 7l-3.75 2.4"/>',
    "ajustes": '<path d="M14 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M4 6l8 0"/><path d="M16 6l4 0"/>'
               '<path d="M8 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M4 12l2 0"/><path d="M10 12l10 0"/>'
               '<path d="M17 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M4 18l11 0"/><path d="M19 18l1 0"/>',
    "flecha_derecha": '<path d="M9 6l6 6l-6 6"/>',
    "flecha_abajo": '<path d="M6 9l6 6l6 -6"/>',
    "tilde": '<path d="M5 12l5 5l10 -10"/>',
    "alerta": '<path d="M12 9v4"/>'
              '<path d="M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0z"/>'
              '<path d="M12 16h.01"/>',
    "info": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0"/>'
            '<path d="M12 9h.01"/><path d="M11 12h1v4h1"/>',
    "refrescar": '<path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4"/>'
                 '<path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4"/>',
    "descargar": '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2"/>'
                 '<path d="M7 11l5 5l5 -5"/><path d="M12 4l0 12"/>',
    # Solo el contorno: las manchas de pintura las agrega pixmap_paleta.
    "paleta": '<path d="M12 21a9 9 0 0 1 0 -18c4.97 0 9 3.582 9 8c0 1.06 -.474 2.078 -1.318 2.828'
              'c-.844 .75 -1.989 1.172 -3.182 1.172h-2.5a2 2 0 0 0 -1 3.75a1.3 1.3 0 0 1 -1 2.25"/>',
    "lapiz": '<path d="M4 20h4l10.5 -10.5a2.828 2.828 0 1 0 -4 -4l-10.5 10.5v4"/><path d="M13.5 6.5l4 4"/>',
    "tacho": '<path d="M4 7l16 0"/><path d="M10 11l0 6"/><path d="M14 11l0 6"/>'
             '<path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12"/>'
             '<path d="M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3"/>',
    "mas": '<path d="M12 5l0 14"/><path d="M5 12l14 0"/>',
}


def icon_pixmap(nombre, color, size=16):
    """El icono como QPixmap de `size` px logicos, nitido a cualquier escala de pantalla."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{ICONOS[nombre]}</svg>'
    )
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    lado = max(1, round(size * dpr))
    pixmap = QPixmap(lado, lado)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def icon(nombre, color, size=16):
    return QIcon(icon_pixmap(nombre, color, size))


def pixmap_paleta(c, size=18):
    """La paleta de pintor del botón de temas, con manchas de los colores del tema `c`."""
    pixmap = icon_pixmap("paleta", c["texto2"], size)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    k = size / 24
    for (x, y), color in zip(((8, 10.5), (12.5, 7), (17, 10.5)), (c["escanear"], c["acento"], c["texto"])):
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(x * k, y * k), 2.1 * k, 2.1 * k)
    p.end()
    return pixmap


class QualitySlider(QWidget):
    """
    Barra de calidad: una pista con forma de pastilla y marcas de regla, y un
    tirador claro que se mueve entre los valores permitidos.

    Los valores no son continuos (un driver de escaner acepta solo ciertas
    resoluciones), asi que el tirador salta al permitido mas cercano. Las
    marcas altas son esos valores; las bajas solo dan la escala.
    """
    valueChanged = pyqtSignal(int)

    def __init__(self, valores, valor, paso_marcas=25, parent=None):
        super().__init__(parent)
        self._valores = sorted(valores)
        self._valor = valor if valor in self._valores else self._valores[0]
        self._paso_marcas = paso_marcas
        self._foco_teclado = False
        self.setFixedHeight(22)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(230, 22)

    def value(self):
        return self._valor

    def setValue(self, valor):
        if valor in self._valores and valor != self._valor:
            self._valor = valor
            self.update()
            self.valueChanged.emit(valor)

    # El tirador no llega al borde de la pista: queda este margen a cada lado.
    _MARGEN = 12

    def _x_de(self, valor):
        lo, hi = self._valores[0], self._valores[-1]
        ancho = self.width() - 2 * self._MARGEN
        return self._MARGEN + ancho * (valor - lo) / (hi - lo)

    def _valor_en(self, x):
        return min(self._valores, key=lambda v: abs(self._x_de(v) - x))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        pista = QRectF(0.5, 0.5, self.width() - 1, h - 1)
        p.setPen(QPen(QColor(C["acento"] if self._foco_teclado else C["apagado_borde"]), 1))
        p.setBrush(QColor(C["apagado"]))
        p.drawRoundedRect(pista, h / 2, h / 2)

        # Marcas de regla. Lo ya "recorrido" (a la izquierda del tirador) va
        # mas claro, para que la posicion se lea de un vistazo.
        lo, hi = self._valores[0], self._valores[-1]
        x_tirador = self._x_de(self._valor)
        v = lo
        while v <= hi:
            x = round(self._x_de(v)) + 0.5  # al centro del píxel: línea nítida
            permitido = v in self._valores
            alto = 10 if permitido else 5
            if x <= x_tirador:
                color = C["tenue"] if permitido else C["apagado_texto"]
            else:
                color = C["apagado_texto"] if permitido else C["marca_baja"]
            p.setPen(QPen(QColor(color), 1))
            p.drawLine(QLineF(x, (h - alto) / 2, x, (h + alto) / 2))
            v += self._paso_marcas

        # Tirador: una pastilla clara con una sombra corta debajo.
        ancho_t, alto_t = 12, h - 6
        tirador = QRectF(x_tirador - ancho_t / 2, (h - alto_t) / 2, ancho_t, alto_t)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(tirador.translated(0, 1.5), 5, 5)
        p.setBrush(QColor(C["tirador_hover"] if self.underMouse() else C["tirador"]))
        p.drawRoundedRect(tirador, 5, 5)

    # El tirador sigue al cursor sin animacion: es un ajuste directo, y
    # cualquier demora entre la mano y la pantalla se siente como lag.
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._foco_teclado = False
            self.setValue(self._valor_en(event.position().x()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._valor_en(event.position().x()))

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def keyPressEvent(self, event):
        i = self._valores.index(self._valor)
        tecla = event.key()
        if tecla in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            i = max(i - 1, 0)
        elif tecla in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            i = min(i + 1, len(self._valores) - 1)
        elif tecla == Qt.Key.Key_Home:
            i = 0
        elif tecla == Qt.Key.Key_End:
            i = len(self._valores) - 1
        else:
            super().keyPressEvent(event)
            return
        self.setValue(self._valores[i])

    def focusInEvent(self, event):
        # El aro de foco solo cuando se llega con el teclado.
        self._foco_teclado = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        self.update()

    def focusOutEvent(self, event):
        self._foco_teclado = False
        self.update()


class BusyBar(QWidget):
    """
    Barra de espera sin porcentaje: un segmento que cruza de izquierda a
    derecha a velocidad constante mientras dura el escaneo. No hay forma de
    saber cuanto falta (el escaner no lo informa), solo que sigue trabajando.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 4)
        self._fase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1200)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._avanzar)
        self.hide()

    def _avanzar(self, fase):
        self._fase = fase
        self.update()

    def start(self):
        self.show()
        # Si Windows tiene las animaciones desactivadas, queda la barra quieta.
        if QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo):
            self._anim.start()

    def stop(self):
        self._anim.stop()
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        w, h = self.width(), self.height()
        p.setBrush(QColor(C["linea_hundido"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        p.setBrush(QColor(C["escanear"]))
        if self._anim.state() == QVariantAnimation.State.Running:
            largo = 0.35 * w
            x = -largo + self._fase * (w + largo)
            p.setClipRect(QRectF(0, 0, w, h))
            p.drawRoundedRect(QRectF(x, 0, largo, h), h / 2, h / 2)
        else:
            p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)


def _texto_con_borde(p, x, y, texto, fuente, relleno, borde=None, ancho_borde=0.0):
    """Texto centrado en (x, y), con un contorno para que se lea sobre cualquier fondo."""
    m = QFontMetricsF(fuente)
    camino = QPainterPath()
    camino.addText(x - m.horizontalAdvance(texto) / 2, y + (m.ascent() - m.descent()) / 2,
                   fuente, texto)
    if borde is not None and ancho_borde > 0:
        p.strokePath(camino, QPen(QColor(borde), ancho_borde, Qt.PenStyle.SolidLine,
                                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.fillPath(camino, QColor(relleno))


def _marquesina(p, w, h, corrimiento, color_encendida, apagada, paso=30, radio=5, margen=8):
    """
    Lamparitas alrededor de un rectángulo de w x h, encendidas de a una cada
    tres y corriéndose con `corrimiento`. `color_encendida` recibe el número
    de lamparita y devuelve su color.
    """
    for i in range(int(2 * (w + h) // paso)):
        d = i * paso
        if d < w:
            x, y = d, margen
        elif d < w + h:
            x, y = w - margen, d - w
        elif d < 2 * w + h:
            x, y = w - (d - w - h), h - margen
        else:
            x, y = margen, h - (d - 2 * w - h)
        p.setBrush(color_encendida(i) if (i + corrimiento) % 3 == 0 else apagada)
        p.drawEllipse(QRectF(x - radio, y - radio, 2 * radio, 2 * radio))


def _poligono_estrella(x, y, radio, puntas, interior):
    """Estrella de `puntas` puntas con la primera hacia arriba; `interior` es la proporción del radio de adentro."""
    puntos = []
    for i in range(puntas * 2):
        r = radio if i % 2 == 0 else radio * interior
        an = -math.pi / 2 + i * math.pi / puntas
        puntos.append(QPointF(x + math.cos(an) * r, y + math.sin(an) * r))
    return QPolygonF(puntos)


class Festejo(QWidget):
    """
    Festejo del canje del contador, dibujado con QPainter sobre una capa
    transparente que cubre la ventana y no toma clics. Cambia según el
    escalón canjeado: un fueguito que quema el número (antes de 10), confeti
    (10), confeti grande y desparramado (25), fuegos artificiales (50), un
    diamante con rayos y marquesina de casino (100), lluvia de billetes (250)
    y un jackpot de monedas que se apilan al pie (500).
    Hay además dos que no salen de un canje: la medalla del récord del día
    ("record") y el cofre sorpresa ("cofre"), que al abrirse larga su premio.
    Se destruye sola al terminar. Las bibliotecas de confeti para la web
    necesitarían un navegador embebido (QtWebEngine, más de 100 MB): así no
    agrega nada al ejecutable.
    """

    COLORES = ["#D84315", "#F0C36B", "#6FCF73", "#569CD6", "#C586C0", "#FFFFFF"]
    DORADOS = ["#FFC83D", "#FFE08A", "#FFFFFF", "#F0C36B"]
    HIELO = ["#9FF0FF", "#FFFFFF", "#CFF7FF", "#5CC9E0"]
    MEDALLA = ["#FFC83D", "#FFE08A", "#FFFFFF", "#1565C0", "#C62828"]
    # Colores de los fuegos artificiales: cada explosión usa una paleta.
    PALETAS_FUEGOS = [
        ["#FFC83D", "#FFE08A"], ["#FFFFFF", "#CFF7FF"], ["#FF6B4A", "#FFC83D"],
        ["#6FCF73", "#E9FFD9"], ["#569CD6", "#BFE3FF"], ["#C586C0", "#FFD6F6"],
    ]
    DURACIONES = {0: 2.0, 10: 3.0, 25: 4.2, 50: 5.6, 100: 5.0, 250: 5.2, 500: 6.6,
                  "record": 6.2, "cofre": 3.4}
    _billetes = None    # (frente, dorso), dibujados una sola vez
    QUEMADO = 0.75     # segundo del fueguito en que el número ya no se ve
    # Llama plana en tres capas, de afuera hacia adentro (viewBox de 64x80,
    # con la base abajo). Cada capa titila por su cuenta.
    LLAMA_SVG = [
        ("#F4511E", "M32 2C38 18 54 26 54 48C54 66 44 78 32 78C20 78 10 66 10 50"
                    "C10 38 16 30 22 24C22 34 26 38 30 40C28 26 30 12 32 2Z"),
        ("#FF9800", "M33 26C37 36 46 42 46 55C46 67 40 74 32 74C24 74 18 67 18 57"
                    "C18 50 22 45 26 42C26 49 28 52 31 53C30 44 31 34 33 26Z"),
        ("#FFE082", "M32 46C35 53 40 57 40 63C40 69 36 73 32 73C28 73 24 69 24 64"
                    "C24 59 28 55 32 46Z"),
    ]
    # (corrimiento en anchos del contador, tamaño, demora, fase): las de los
    # costados primero, así la del centro queda adelante.
    LLAMAS = [(-0.32, 0.68, 0.07, 1.7), (0.32, 0.72, 0.13, 3.1), (0.0, 1.0, 0.0, 0.0)]
    CUADRO_MS = 16     # unos 60 cuadros por segundo
    GRAVEDAD = 1400    # píxeles por segundo al cuadrado, para el confeti

    def __init__(self, parent, origen, nivel, zona=None, al_quemar=None, datos=None):
        """
        `zona` es el rectángulo del contador y `al_quemar` lo que se llama
        cuando el fuego tapa el número: solo para el fueguito (nivel 0).
        `datos` lleva lo que muestran la medalla (fichas, semana, record) y
        el cofre (premio, al_abrir).
        """
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.setGeometry(parent.rect())
        self._rnd = random.Random()
        self._origen = (float(origen.x()), float(origen.y()))
        self._nivel = nivel
        self._duracion = self.DURACIONES[nivel]
        self._particulas = []
        self._nuevas = []       # lo que aparece durante un cuadro (chispas, tandas)
        self._agenda = []       # (segundo, función): lo que se larga más tarde
        self._t = 0.0
        self._zona = QRectF(zona) if zona is not None else None
        self._al_quemar = al_quemar
        self._datos = datos or {}
        self._pila = []         # alto de las monedas apiladas, cada 6 px de ancho
        self._capas_llama = []
        if nivel == 0:
            for color, camino in self.LLAMA_SVG:
                svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 80">'
                       f'<path fill="{color}" d="{camino}"/></svg>')
                self._capas_llama.append(QSvgRenderer(QByteArray(svg.encode("utf-8"))))
        {0: self._armar_0, 10: self._armar_10, 25: self._armar_25,
         50: self._armar_50, 100: self._armar_100, 250: self._armar_250,
         500: self._armar_500, "record": self._armar_record,
         "cofre": self._armar_cofre}[nivel]()
        self._agenda.sort(key=lambda e: e[0])
        self._particulas, self._nuevas = self._nuevas, []

        self._inicio = time.perf_counter()
        self._ultimo = self._inicio
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._avanzar)
        self._timer.start(self.CUADRO_MS)
        parent.installEventFilter(self)
        self.raise_()
        self.show()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    # --- Armado de cada festejo ---

    def _confeti(self, x, y, cantidad, angulo, abanico, vmin, vmax,
                 tamano=(1.0, 1.0), colores=None, vida=(2.2, 3.0)):
        """Tanda de papelitos que sale de (x, y) hacia angulo ± abanico (grados)."""
        rnd = self._rnd
        colores = colores or self.COLORES
        for _ in range(cantidad):
            a = math.radians(angulo + rnd.uniform(-abanico, abanico))
            v = rnd.uniform(vmin, vmax)
            esc = rnd.uniform(*tamano)
            self._nuevas.append({
                "tipo": "papel", "x": x, "y": y,
                "vx": math.cos(a) * v, "vy": math.sin(a) * v,
                "giro": rnd.uniform(0, 360), "vgiro": rnd.uniform(-540, 540),
                "fase": rnd.uniform(0, math.tau),        # para el bamboleo
                "ancho": rnd.uniform(6, 10) * esc, "alto": rnd.uniform(3, 6) * esc,
                "redondo": rnd.random() < 0.3,
                "color": QColor(rnd.choice(colores)),
                "edad": 0.0, "vida": rnd.uniform(*vida),
            })

    def _armar_0(self):
        # Las llamas (dibujadas según el tiempo en _pintar_llamas) van
        # carbonizando el número; cuando ya no se ve, abajo queda el cero, y
        # al apagarse sube un poco de humo.
        for _ in range(8):
            self._agenda.append((self._rnd.uniform(0.95, 1.4), self._humo))
        if self._al_quemar is not None:
            self._agenda.append((self.QUEMADO, self._al_quemar))

    def _humo(self):
        rnd, z = self._rnd, self._zona
        self._nuevas.append({
            "tipo": "humo",
            "x": z.center().x() + rnd.uniform(-0.3, 0.3) * z.width(), "y": z.top(),
            "vx": rnd.uniform(-14, 6), "vy": rnd.uniform(-45, -25), "empuje": 15,
            "radio": rnd.uniform(4, 7) * z.height() / 20,
            "edad": 0.0, "vida": rnd.uniform(0.9, 1.4),
        })

    def _armar_10(self):
        # Abanico hacia arriba: el contador está al pie de la ventana.
        self._confeti(*self._origen, 140, -90, 50, 380, 900)

    def _armar_25(self):
        rnd, w, h = self._rnd, self.width(), self.height()
        self._confeti(*self._origen, 110, -90, 45, 400, 950, tamano=(1.2, 1.8))
        # Ráfagas desde lugares, momentos y direcciones al azar, cada una con
        # su cantidad y su fuerza: que no se lea como dos cañones prolijos.
        for _ in range(10):
            cuando = rnd.uniform(0.0, 1.4)
            args = (rnd.uniform(0.03, 0.97) * w, rnd.uniform(0.6, 1.0) * h + 10,
                    rnd.randint(50, 130), -90 + rnd.uniform(-40, 40),
                    rnd.uniform(12, 50), rnd.uniform(350, 600), rnd.uniform(800, 1200))
            self._agenda.append((cuando, lambda a=args: self._confeti(
                *a, tamano=(1.1, 2.1), vida=(2.0, 3.2))))
        # Y algo que llueve desde arriba, de a uno y a lo ancho.
        for _ in range(90):
            cuando = rnd.uniform(0.3, 1.8)
            x = rnd.uniform(0.0, 1.0) * w
            self._agenda.append((cuando, lambda x=x: self._confeti(
                x, -10, 1, 90, 60, 20, 200, tamano=(1.1, 2.0), vida=(2.0, 2.6))))

    def _armar_50(self):
        rnd = self._rnd
        self._confeti(*self._origen, 80, -90, 45, 350, 850, colores=self.DORADOS)
        # Cohetes salteados durante casi tres segundos y un final de varios
        # juntos.
        tiempos = [rnd.uniform(0.0, 3.0) for _ in range(24)]
        tiempos += [3.3 + rnd.uniform(0, 0.3) for _ in range(9)]
        for cuando in tiempos:
            self._agenda.append((cuando, self._lanzar_cohete))

    def _lanzar_cohete(self):
        rnd, w, h = self._rnd, self.width(), self.height()
        altura = rnd.uniform(0.45, 0.85) * h      # cuánto sube desde el piso
        g = 600
        self._nuevas.append({
            "tipo": "cohete", "x": rnd.uniform(0.1, 0.9) * w, "y": float(h),
            "vx": rnd.uniform(-40, 40), "vy": -math.sqrt(2 * g * altura), "g": g,
            "edad": 0.0, "vida": 4.0,
        })

    def _explotar(self, x, y):
        rnd = self._rnd
        paleta = rnd.choice(self.PALETAS_FUEGOS)
        anillo = rnd.random() < 0.3
        n = rnd.randint(100, 160)
        vmax = rnd.uniform(230, 380)
        # Fogonazo en el centro, apenas un instante.
        self._nuevas.append({"tipo": "fogonazo", "x": x, "y": y, "r": vmax * 0.45,
                             "vx": 0.0, "vy": 0.0, "edad": 0.0, "vida": 0.18})
        for i in range(n):
            a = i / n * math.tau + rnd.uniform(-0.05, 0.05)
            # La raíz reparte las chispas parejo dentro del círculo; el anillo
            # las deja todas en el borde.
            v = vmax * (rnd.uniform(0.92, 1.0) if anillo else math.sqrt(rnd.random()))
            self._nuevas.append({
                "tipo": "chispa", "x": x, "y": y,
                "vx": math.cos(a) * v, "vy": math.sin(a) * v,
                "color": QColor(rnd.choice(paleta)),
                "edad": 0.0, "vida": rnd.uniform(1.1, 1.9),
                "titila": rnd.random() < 0.5,
            })

    def _armar_100(self):
        # El diamante, los rayos y la marquesina se dibujan según el tiempo
        # en paintEvent; acá van solo las partículas.
        cx, cy = self._centro_diamante()
        self._agenda.append((1.05, lambda: self._confeti(
            cx, cy, 170, -90, 180, 250, 750, tamano=(1.0, 1.5), colores=self.HIELO)))
        self._agenda.append((1.6, lambda: self._confeti(
            *self._origen, 90, -90, 45, 400, 900, colores=self.HIELO)))

    def _centro_diamante(self):
        return self.width() / 2, self.height() / 2 - 10

    def _billete(self, x, y, vx, vy, fajo=False):
        rnd = self._rnd
        self._nuevas.append({
            "tipo": "billete", "x": x, "y": y, "vx": vx, "vy": vy, "fajo": fajo,
            "fase": rnd.uniform(0, math.tau), "vfase": rnd.uniform(2, 4),     # hamaca
            "vuelta": rnd.uniform(0, math.tau), "vvuelta": rnd.uniform(3, 7),  # da vueltas
            "giro0": rnd.uniform(-0.6, 0.6), "esc": rnd.uniform(0.85, 1.1),
            "edad": 0.0, "vida": rnd.uniform(4.0, 6.0),
        })

    def _armar_250(self):
        # Un fajo que se desarma desde el contador y después billetes que
        # caen de arriba a lo ancho, con algunos fajos enteros que bajan más
        # rápido.
        rnd, w = self._rnd, self.width()
        ox, oy = self._origen
        for _ in range(45):
            self._billete(ox + rnd.uniform(-10, 10), oy,
                          rnd.uniform(-420, 300), rnd.uniform(-950, -500))
        for _ in range(110):
            x = rnd.uniform(0.0, 1.0) * w
            self._agenda.append((rnd.uniform(0.15, 3.2), lambda x=x: self._billete(
                x, -20, rnd.uniform(-20, 20), rnd.uniform(40, 120))))
        for _ in range(6):
            x = rnd.uniform(40, max(41, w - 40))
            self._agenda.append((rnd.uniform(0.3, 2.2), lambda x=x: self._billete(
                x, -30, rnd.uniform(-30, 30), rnd.uniform(60, 160), fajo=True)))

    @classmethod
    def _sprites_billete(cls):
        """Frente y dorso de un billete verde tipo dólar, inventado, a doble resolución."""
        if cls._billetes is not None:
            return cls._billetes

        def fuente(px, serif=False):
            f = QFont("Georgia" if serif else "Arial")
            f.setPixelSize(px)
            f.setBold(True)
            return f

        def texto(p, x, y, s, f, color):
            p.setFont(f)
            p.setPen(QColor(color))
            p.drawText(QRectF(x - 20, y - 8, 40, 16), Qt.AlignmentFlag.AlignCenter, s)
            p.setPen(Qt.PenStyle.NoPen)

        hechos = []
        for frente in (True, False):
            pix = QPixmap(240, 104)
            pix.fill(QColor("#DCE7CF" if frente else "#5E8F5A"))
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.scale(2, 2)
            tinta = "#2F5D3A" if frente else "#1F4426"
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(tinta), 3))
            p.drawRect(QRectF(2.5, 2.5, 115, 47))
            p.setPen(QPen(QColor(tinta), 1))
            p.drawRect(QRectF(7, 7, 106, 38))
            if frente:
                # Óvalo con un retrato cualquiera, dos sellos y el valor en
                # las cuatro esquinas.
                p.setPen(QPen(QColor(tinta), 1.5))
                p.setBrush(QColor("#C3D6B0"))
                p.drawEllipse(QRectF(46, 9, 28, 34))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#4E7A55"))
                p.drawEllipse(QRectF(54.5, 15.5, 11, 11))
                p.drawChord(QRectF(50, 30, 20, 14), 0, 180 * 16)
                p.setBrush(QColor("#4A4F48"))
                p.drawEllipse(QRectF(25, 19, 14, 14))
                p.setBrush(QColor("#3C7A4A"))
                p.drawEllipse(QRectF(81, 19, 14, 14))
                texto(p, 88, 26.5, "$", fuente(9), "#DCE7CF")
                for x, y in ((20, 14), (100, 14), (20, 39), (100, 39)):
                    texto(p, x, y, "100", fuente(10), tinta)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#86B381"))
                p.drawEllipse(QRectF(36, 11, 48, 30))
                texto(p, 60, 27, "100", fuente(20, serif=True), tinta)
                texto(p, 18, 14, "100", fuente(9), tinta)
                texto(p, 102, 39, "100", fuente(9), tinta)
            p.end()
            hechos.append(pix)
        cls._billetes = tuple(hechos)
        return cls._billetes

    def _moneda(self, x, y, vx, vy):
        rnd = self._rnd
        self._nuevas.append({
            "tipo": "moneda", "x": x, "y": y, "vx": vx, "vy": vy,
            "fase": rnd.uniform(0, math.tau), "vfase": rnd.uniform(8, 16),
            "r": rnd.uniform(7, 10), "quieta": False,
            # Viven hasta que el festejo las apaga (_apagar_monedas).
            "edad": 0.0, "vida": 99.0,
        })

    def _armar_500(self):
        # Un chorro de monedas que sale del contador, rebota y se va apilando
        # al pie; la ventana tiembla un poco al principio. JACKPOT, el número
        # y la marquesina se dibujan según el tiempo.
        rnd = self._rnd
        ox, oy = self._origen
        self._pila = [0.0] * (int(self.width() // 6) + 2)
        for i in range(170):
            self._agenda.append((i * 0.016, lambda: self._moneda(
                ox + rnd.uniform(-6, 6), oy - 8, rnd.uniform(-380, 200), rnd.uniform(-1000, -620))))
        self._agenda.append((6.0, self._apagar_monedas))

    def _apagar_monedas(self):
        for p in self._particulas:
            if p["tipo"] == "moneda":
                p["vida"] = p["edad"] + 0.5

    def _piso(self, x):
        """Altura del piso en x: el borde de abajo menos lo que ya se apiló."""
        if not self._pila:
            return self.height() - 2
        i = max(0, min(len(self._pila) - 1, int(x // 6)))
        return self.height() - 2 - self._pila[i]

    def _apilar(self, x, r):
        i = int(x // 6)
        tope = self.height() * 0.3
        for j in range(i - 3, i + 4):
            if 0 <= j < len(self._pila):
                self._pila[j] = min(tope, self._pila[j] + r * 0.5 * (1 - abs(j - i) / 4))

    def _armar_record(self):
        # La medalla, la cinta y el cartel se dibujan según el tiempo en
        # _pintar_medalla; acá solo el confeti cuando la medalla llega.
        w, h = self.width(), self.height()
        self._agenda.append((0.6, lambda: self._confeti(
            w / 2, h * 0.32, 90, -90, 180, 200, 600, colores=self.MEDALLA)))
        self._agenda.append((0.55, lambda: self._destello(w / 2, h * 0.36 - 10, 30)))

    def _armar_cofre(self):
        # El cofre (en _pintar_cofre) cae, tiembla y se abre a los 1,7 s.
        # El premio arranca cuando el cofre ya se está yendo.
        w, h = self.width(), self.height()
        self._agenda.append((1.75, lambda: self._destello(w / 2, h * 0.45, 40)))
        al_abrir = self._datos.get("al_abrir")
        if al_abrir is not None:
            self._agenda.append((3.0, al_abrir))

    def _destello(self, x, y, n):
        """Chispas doradas para todos lados, como un golpe de luz."""
        rnd = self._rnd
        for _ in range(n):
            a = rnd.uniform(0, math.tau)
            v = rnd.uniform(80, 280)
            self._nuevas.append({
                "tipo": "chispa", "x": x, "y": y, "vx": math.cos(a) * v, "vy": math.sin(a) * v,
                "color": QColor(rnd.choice(["#FFE08A", "#FFFFFF", "#FFC83D"])),
                "edad": 0.0, "vida": rnd.uniform(0.5, 0.9), "titila": False,
            })

    # --- Movimiento ---

    def _avanzar(self):
        ahora = time.perf_counter()
        dt = min(ahora - self._ultimo, 0.05)
        self._ultimo = ahora
        self._t = ahora - self._inicio
        while self._agenda and self._agenda[0][0] <= self._t:
            self._agenda.pop(0)[1]()
        if self._t >= self._duracion and not self._agenda:
            self._timer.stop()
            self.parent().removeEventFilter(self)
            self.deleteLater()
            return

        vivas = []
        freno_papel = 0.985 ** (dt * 60)    # rozamiento del aire
        freno_chispa = 0.955 ** (dt * 60)
        for p in self._particulas:
            p["edad"] += dt
            if p["edad"] >= p["vida"]:
                continue
            tipo = p["tipo"]
            if tipo == "papel":
                p["vx"] *= freno_papel
                p["vy"] = p["vy"] * freno_papel + self.GRAVEDAD * dt
                p["giro"] += p["vgiro"] * dt
                p["fase"] += 8 * dt
            elif tipo == "chispa":
                p["vx"] *= freno_chispa
                p["vy"] = p["vy"] * freno_chispa + 140 * dt
            elif tipo == "billete":
                # Mucho rozamiento: caen despacio, hamacándose de un lado al
                # otro. Los fajos pesan más y casi no se hamacan.
                f = (0.985 if p["fajo"] else 0.95) ** (dt * 60)
                p["vx"] *= f
                p["vy"] = p["vy"] * f + (900 if p["fajo"] else 300) * dt
                p["fase"] += p["vfase"] * dt
                p["vuelta"] += p["vvuelta"] * dt
                if not p["fajo"]:
                    p["x"] += math.sin(p["fase"]) * 50 * dt
            elif tipo == "moneda":
                # Se mueven por su cuenta: rebotan en los costados y en el
                # piso, y cuando ya casi no rebotan se quedan apiladas.
                if not p["quieta"]:
                    r = p["r"]
                    p["vy"] += self.GRAVEDAD * dt
                    p["x"] += p["vx"] * dt
                    p["y"] += p["vy"] * dt
                    p["fase"] += p["vfase"] * dt
                    if p["x"] < r:
                        p["x"], p["vx"] = r, abs(p["vx"]) * 0.6
                    elif p["x"] > self.width() - r:
                        p["x"], p["vx"] = self.width() - r, -abs(p["vx"]) * 0.6
                    piso = self._piso(p["x"]) - r * 0.4
                    if p["y"] >= piso and p["vy"] > 0:
                        p["y"] = piso
                        p["vy"] *= -0.4
                        p["vx"] *= 0.6
                        if abs(p["vy"]) < 110:
                            p["quieta"] = True
                            self._apilar(p["x"], r)
                vivas.append(p)
                continue
            elif tipo == "humo":
                p["vy"] -= p["empuje"] * dt   # sube cada vez un poco más rápido
            elif tipo == "cohete":
                p["vy"] += p["g"] * dt
                if p["vy"] >= 0:          # llegó arriba: explota
                    self._explotar(p["x"], p["y"])
                    continue
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            vivas.append(p)
        self._particulas = vivas + self._nuevas
        self._nuevas = []
        self.update()

    # --- Dibujo ---

    def _salida(self, desde, largo):
        """1 hasta 'desde' segundos, y de ahí baja a 0 en 'largo' segundos."""
        return max(0.0, min(1.0, 1 - (self._t - desde) / largo))

    @staticmethod
    def _rebote(t):
        """De 0 a 1 pasándose un poco y volviendo (como un resorte)."""
        t = max(0.0, min(1.0, t))
        c = 1.7
        return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setPen(Qt.PenStyle.NoPen)
        if self._nivel == 100:
            self._pintar_diamante(p)
        elif self._nivel == 500:
            self._oscurecer(p, 0.4)
            p.setOpacity(self._entrada_salida())
            _marquesina(p, self.width(), self.height(), int(self._t * 9),
                        lambda i: QColor("#FFE08A"), QColor("#5A4A20"))
            p.setOpacity(1.0)
        elif self._nivel == "record":
            self._oscurecer(p, 0.5)
        elif self._nivel == "cofre":
            self._oscurecer(p, 0.55)
        if self._nivel == 0:
            self._pintar_carbon(p)
            self._pintar_llamas(p)
        for c in self._particulas:
            # Cada partícula se desvanece en su último medio segundo.
            p.setOpacity(max(0.0, min(1.0, (c["vida"] - c["edad"]) * 2)))
            tipo = c["tipo"]
            if tipo == "papel":
                p.save()
                p.translate(c["x"], c["y"])
                p.rotate(c["giro"])
                # Achatar un eje simula que el papelito da vueltas en el aire.
                p.scale(1.0, abs(math.cos(c["fase"])) * 0.8 + 0.2)
                p.setBrush(c["color"])
                w, h = c["ancho"], c["alto"]
                if c["redondo"]:
                    p.drawEllipse(QRectF(-h, -h, 2 * h, 2 * h))
                else:
                    p.drawRect(QRectF(-w / 2, -h / 2, w, h))
                p.restore()
            elif tipo == "chispa":
                if c["titila"] and c["edad"] > c["vida"] * 0.5:
                    p.setOpacity(p.opacity() * (0.5 + 0.5 * math.sin(c["edad"] * 40)))
                # Una estela corta en la dirección del movimiento.
                p.setPen(QPen(c["color"], 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QLineF(c["x"] - c["vx"] * 0.05, c["y"] - c["vy"] * 0.05,
                                  c["x"], c["y"]))
                p.setPen(Qt.PenStyle.NoPen)
            elif tipo == "fogonazo":
                avance = c["edad"] / c["vida"]
                p.setOpacity(1 - avance)
                r = c["r"] * (0.5 + 0.5 * avance)
                # Resplandor: blanco en el centro, transparente en el borde.
                luz = QRadialGradient(QPointF(c["x"], c["y"]), r)
                luz.setColorAt(0.0, QColor(255, 246, 221, 150))
                luz.setColorAt(1.0, QColor(255, 246, 221, 0))
                p.setBrush(QBrush(luz))
                p.drawEllipse(QRectF(c["x"] - r, c["y"] - r, 2 * r, 2 * r))
            elif tipo == "humo":
                avance = c["edad"] / c["vida"]
                r = c["radio"] * (1 + 1.6 * avance)
                p.setOpacity(0.35 * (1 - avance) * min(1.0, c["edad"] / 0.2))
                p.setBrush(QColor("#6A6A6A"))
                p.drawEllipse(QRectF(c["x"] - r, c["y"] - r, 2 * r, 2 * r))
            elif tipo == "cohete":
                p.setPen(QPen(QColor(255, 230, 170, 200), 2, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))
                p.drawLine(QLineF(c["x"], c["y"], c["x"] - c["vx"] * 0.06,
                                  c["y"] - c["vy"] * 0.06))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#FFF3C4"))
                p.drawEllipse(QRectF(c["x"] - 2.5, c["y"] - 2.5, 5, 5))
            elif tipo == "billete":
                self._pintar_billete(p, c)
            elif tipo == "moneda":
                self._pintar_moneda(p, c)
        p.setOpacity(1.0)
        if self._nivel == 250:
            self._cartel(p, self._t, "250 escaneos", "#B9F5AE", "#173404", 4.6, 30,
                         self.height() * 0.4)
        elif self._nivel == 500:
            self._pintar_jackpot(p)
        elif self._nivel == "record":
            self._pintar_medalla(p)
        elif self._nivel == "cofre":
            self._pintar_cofre(p)

    def _entrada_salida(self):
        """De 0 a 1 en los primeros 0,3 s y de vuelta a 0 en el último medio segundo."""
        return min(1.0, self._t / 0.3) * max(0.0, min(1.0, (self._duracion - self._t) / 0.5))

    def _oscurecer(self, p, alfa):
        p.fillRect(self.rect(), QColor(0, 0, 0, int(255 * alfa * self._entrada_salida())))

    def _fuente(self, px, negrita=True):
        f = QFont(self.font())
        f.setPixelSize(px)
        f.setBold(negrita)
        return f

    def _cartel(self, p, t, texto, relleno, borde, hasta, tamano, y):
        """Un texto que entra con un rebote y se desvanece a los `hasta` segundos."""
        if t < 0.25:
            return
        alfa = min(1.0, (t - 0.25) / 0.25) * max(0.0, min(1.0, 1 - (t - hasta) / 0.5))
        esc = self._rebote((t - 0.25) / 0.5)
        if alfa <= 0 or esc <= 0.01:
            return
        p.save()
        p.setOpacity(alfa)
        p.translate(self.width() / 2, y)
        p.scale(esc, esc)
        _texto_con_borde(p, 0, 0, texto, self._fuente(tamano), relleno, borde, 6)
        p.restore()

    def _pintar_billete(self, p, c):
        frente, dorso = self._sprites_billete()
        w, h = 56 * c["esc"], 24 * c["esc"]
        p.save()
        p.translate(c["x"], c["y"])
        if c["fajo"]:
            # Tres billetes corridos y una faja de papel.
            p.rotate(math.degrees(c["giro0"] * 0.5 + math.sin(c["fase"]) * 0.12))
            for j in (2, 1, 0):
                p.drawPixmap(QRectF(-w / 2 + j * 1.5, -h / 2 + j * 2, w, h), frente,
                             QRectF(frente.rect()))
            p.setBrush(QColor("#EADFBF"))
            p.drawRect(QRectF(-6, -h / 2 - 1, 12, h + 6))
        else:
            # Achatar un eje simula que da vueltas; del otro lado se ve el dorso.
            vuelta = math.cos(c["vuelta"])
            p.rotate(math.degrees(c["giro0"] + math.sin(c["fase"]) * 0.5))
            p.scale(1.0, max(0.12, abs(vuelta)))
            cara = frente if vuelta > 0 else dorso
            p.drawPixmap(QRectF(-w / 2, -h / 2, w, h), cara, QRectF(cara.rect()))
        p.restore()

    def _pintar_moneda(self, p, c):
        r = c["r"]
        de_canto = abs(math.cos(c["fase"]))
        p.save()
        p.translate(c["x"], c["y"])
        if c["quieta"]:
            p.scale(1.0, 0.5)       # acostada en la pila
        else:
            p.scale(max(0.1, de_canto), 1.0)
        p.setBrush(QColor("#B8860B"))
        p.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
        p.setBrush(QColor("#FFC83D"))
        p.drawEllipse(QRectF(-r * 0.78, -r * 0.78, 1.56 * r, 1.56 * r))
        if not c["quieta"] and de_canto > 0.5:
            p.setPen(QColor("#8A6200"))
            p.setFont(self._fuente(round(r * 1.1)))
            p.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, "$")
            p.setPen(Qt.PenStyle.NoPen)
        p.restore()

    def _pintar_jackpot(self, p):
        """JACKPOT con las letras saltando en ola y, centrado abajo, el número."""
        t, w, h = self._t, self.width(), self.height()
        if t < 0.25:
            return
        p.save()
        p.setOpacity(min(1.0, (t - 0.25) / 0.25) * max(0.0, min(1.0, (5.9 - t) / 0.5)))
        fuente = self._fuente(50)
        m = QFontMetricsF(fuente)
        palabra = "JACKPOT"
        anchos = [m.horizontalAdvance(letra) for letra in palabra]
        x = w / 2 - (sum(anchos) + 5 * (len(palabra) - 1)) / 2
        for i, letra in enumerate(palabra):
            esc = self._rebote((t - 0.25 - i * 0.07) / 0.4)
            if esc > 0.01:
                salto = -abs(math.sin(t * 6 + i * 0.7)) * 8
                p.save()
                p.translate(x + anchos[i] / 2, h / 2 - 34 + salto)
                p.scale(esc, esc)
                color = "#FFE08A" if (int(t * 8) + i) % 2 else "#FFFFFF"
                _texto_con_borde(p, 0, 0, letra, fuente, color, "#3A2A00", 8)
                p.restore()
            x += anchos[i] + 5
        p.restore()
        self._cartel(p, t - 0.35, "500 escaneos", "#FFE08A", "#3A2A00", 5.3, 30, h / 2 + 18)

    def _pintar_medalla(self, p):
        """
        La medalla del récord: cae colgada de una cinta, rebota como un
        resorte, se hamaca y abajo muestra el cartel con la semana. Al final
        vuelve a subir.
        """
        t, w, h = self._t, self.width(), self.height()
        fichas = self._datos.get("fichas", 0)
        dias = self._datos.get("semana", [])
        record = self._datos.get("record", 0)
        ax, ay, largo = w / 2, -10.0, h * 0.36
        if t < 0.55:
            l = largo * (t / 0.55) ** 2
        else:
            k = t - 0.55
            l = largo * (1 + 0.1 * math.exp(-5 * k) * math.sin(k * 18))
        if t > 5.6:
            l -= (largo + 200) * ((t - 5.6) / 0.6) ** 2
        ang = 0.0 if t < 0.55 else 0.2 * math.exp(-1.5 * (t - 0.55)) * math.sin((t - 0.55) * 5.5)
        vis = max(0.0, min(1.0, (6.1 - t) / 0.5))
        mx, my = ax + math.sin(ang) * l, ay + math.cos(ang) * l

        # Rayos girando detrás.
        if t > 0.55:
            p.save()
            p.setOpacity(0.16 * min(1.0, (t - 0.55) / 0.4) * vis)
            p.translate(mx, my)
            p.rotate(math.degrees(t * 0.6))
            p.setBrush(QColor("#FFE08A"))
            for _ in range(12):
                p.rotate(30)
                p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(420, -24), QPointF(420, 24)]))
            p.restore()

        p.save()
        p.setOpacity(vis)
        p.translate(ax, ay)
        p.rotate(-math.degrees(ang))
        # La cinta: dos tiras que bajan en V hasta la medalla.
        lb = max(0.0, l - 34)
        p.setBrush(QColor("#1565C0"))
        p.drawPolygon(QPolygonF([QPointF(-36, 0), QPointF(-14, 0), QPointF(14, lb), QPointF(-8, lb)]))
        p.setBrush(QColor("#C62828"))
        p.drawPolygon(QPolygonF([QPointF(14, 0), QPointF(36, 0), QPointF(8, lb), QPointF(-14, lb)]))
        p.setPen(QPen(QColor("#FFFFFF"), 3))
        p.drawLine(QLineF(-25, 0, 3, lb))
        p.drawLine(QLineF(25, 0, -3, lb))
        p.setPen(Qt.PenStyle.NoPen)

        p.translate(0, l)
        p.save()
        if t < 0.55:
            p.scale(max(0.15, abs(math.cos(t * 16))), 1.0)    # gira mientras cae
        p.setBrush(QColor("#B8860B"))
        p.drawEllipse(QRectF(-38, -38, 76, 76))
        p.setBrush(QColor("#FFC83D"))
        p.drawEllipse(QRectF(-32, -32, 64, 64))
        p.setPen(QPen(QColor("#D9A520"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-25, -25, 50, 50))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFF3C4"))
        p.drawPolygon(_poligono_estrella(0, 0, 17, 5, 0.45))
        # Un brillo que le cruza cada tanto.
        brillo = ((t - 0.8) % 1.8) / 0.6
        if t > 0.8 and brillo <= 1:
            p.save()
            borde = QPainterPath()
            borde.addEllipse(QRectF(-38, -38, 76, 76))
            p.setClipPath(borde)
            x = -60 + brillo * 120
            p.setBrush(QColor(255, 255, 255, 140))
            p.drawPolygon(QPolygonF([QPointF(x, -45), QPointF(x + 14, -45),
                                     QPointF(x - 6, 45), QPointF(x - 20, 45)]))
            p.restore()
        p.restore()

        # El cartel con las fichas de hoy y la semana en barras; la línea
        # punteada es el récord que se acaba de pasar.
        if t > 0.55:
            p.setOpacity(vis * min(1.0, (t - 0.55) / 0.3))
            p.setPen(QPen(QColor("#FFC83D"), 1.5))
            p.setBrush(QColor("#2B1E00"))
            p.drawRoundedRect(QRectF(-100, 46, 200, 128), 10, 10)
            p.setPen(QColor("#FFE08A"))
            p.setFont(self._fuente(13, negrita=False))
            p.drawText(QRectF(-100, 50, 200, 20), Qt.AlignmentFlag.AlignCenter, "Récord del día")
            p.setPen(QColor("#FFFFFF"))
            p.setFont(self._fuente(18))
            p.drawText(QRectF(-100, 68, 200, 24), Qt.AlignmentFlag.AlignCenter, f"{fichas} fichas")
            if dias:
                maximo = max([record, 1] + [n for _, n, _, _ in dias])
                hueco = 8
                ancho = min(24.0, (172 - hueco * (len(dias) - 1)) / len(dias))
                total = ancho * len(dias) + hueco * (len(dias) - 1)
                p.setFont(self._fuente(11, negrita=False))
                for i, (etiqueta, n, es_hoy, futuro) in enumerate(dias):
                    x = -total / 2 + i * (ancho + hueco)
                    crece = self._rebote((t - 0.9 - i * 0.1) / 0.35)
                    alto = (max(3.0, n / maximo * 38) if n > 0 else 0) * crece
                    if alto > 0.1:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor("#FFC83D" if es_hoy else "#6B5A30"))
                        p.drawRoundedRect(QRectF(x, 148 - alto, ancho, alto), 3, 3)
                    p.setPen(QColor("#6B6250" if futuro else "#CFC3A0"))
                    p.drawText(QRectF(x - 6, 152, ancho + 12, 16), Qt.AlignmentFlag.AlignCenter, etiqueta)
                    if es_hoy and crece >= 1:
                        p.setPen(QColor("#FFE08A"))
                        p.drawText(QRectF(x - 10, 148 - alto - 18, ancho + 20, 16),
                                   Qt.AlignmentFlag.AlignCenter, str(n))
                if record > 0:
                    lapiz = QPen(QColor("#FFE08A"), 1)
                    lapiz.setDashPattern([3, 3])
                    p.setPen(lapiz)
                    y = 148 - record / maximo * 38
                    p.drawLine(QLineF(-total / 2 - 6, y, total / 2 + 6, y))
            p.setPen(Qt.PenStyle.NoPen)
        p.restore()

        # Destellos alrededor.
        if 0.7 < t < 5.8:
            p.setBrush(QColor("#FFFFFF"))
            for i in range(8):
                an = i * 0.785 + t * 0.4
                radio = 58 + (i * 13) % 24
                brillo = (math.sin(t * 6 + i * 1.9) + 1) / 2
                p.setOpacity(brillo * vis)
                p.drawPolygon(_poligono_estrella(mx + math.cos(an) * radio,
                                                 my + math.sin(an) * radio * 0.8,
                                                 3 + brillo * 5, 4, 0.3))
            p.setOpacity(1.0)

    def _pintar_cofre(self, p):
        """El cofre cae con un rebote, tiembla cada vez más, se abre con luz y dice qué tocó."""
        t, w, h = self._t, self.width(), self.height()
        cx, cy, ancho, alto, tapa = w / 2, h * 0.52, 120, 66, 28
        sale = max(0.0, min(1.0, (3.4 - t) / 0.4))
        entra = self._rebote(t / 0.45) * 1.4
        tiembla = math.sin(t * 45) * 0.08 * ((t - 0.6) / 1.1) if 0.6 < t < 1.7 else 0.0
        abierto = max(0.0, min(1.0, (t - 1.7) / 0.2))
        if abierto > 0:
            p.save()
            p.setOpacity(sale * 0.2 * abierto)
            p.translate(cx, cy - alto / 2)
            p.rotate(math.degrees(t * 0.8))
            p.setBrush(QColor("#FFE08A"))
            for _ in range(10):
                p.rotate(36)
                p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(500, -28), QPointF(500, 28)]))
            p.restore()
        if entra > 0.01:
            p.save()
            p.setOpacity(sale)
            p.translate(cx, cy)
            p.rotate(math.degrees(tiembla))
            p.scale(entra, entra)
            if abierto > 0:
                # La tapa abierta: se ve por dentro, y la luz que sale.
                p.setBrush(QColor("#4A2C12"))
                p.drawRoundedRect(QRectF(-ancho / 2, -alto / 2 - 48 * abierto, ancho, 48 * abierto), 6, 6)
                p.setBrush(QColor("#FFE08A"))
                p.drawRoundedRect(QRectF(-ancho / 2 + 8, -alto / 2 - 5, ancho - 16, 9), 4, 4)
            p.setBrush(QColor("#8B5A2B"))
            p.drawRoundedRect(QRectF(-ancho / 2, -alto / 2, ancho, alto), 6, 6)
            p.setBrush(QColor("#FFC83D"))
            p.drawRect(QRectF(-ancho / 2 + 14, -alto / 2, 10, alto))
            p.drawRect(QRectF(ancho / 2 - 24, -alto / 2, 10, alto))
            if abierto < 1:
                l = tapa * (1 - abierto)
                p.setBrush(QColor("#A0683A"))
                p.drawRoundedRect(QRectF(-ancho / 2 - 3, -alto / 2 - l, ancho + 6, l), 6, 6)
                p.setBrush(QColor("#FFC83D"))
                p.drawRect(QRectF(-ancho / 2 + 14, -alto / 2 - l, 10, l))
                p.drawRect(QRectF(ancho / 2 - 24, -alto / 2 - l, 10, l))
            p.setBrush(QColor("#FFE08A"))
            p.drawRoundedRect(QRectF(-9, -alto / 2 - 6, 18, 20), 3, 3)
            p.setBrush(QColor("#5A3A10"))
            p.drawRect(QRectF(-2, -alto / 2 + 1, 4, 7))
            p.restore()
        if t > 2.0:
            premio = self._datos.get("premio", "")
            self._cartel(p, t - 1.75, f"Te tocó: {premio}", "#FFFFFF", "#3A2A00", 1.1, 24,
                         cy - alto * 0.7 - 90)

    def _pintar_carbon(self, p):
        """El número carbonizándose: se oscurece, lo tapa, y al apagarse aparece el cero."""
        t = self._t
        if t < 0.15:
            return
        if t < 0.55:
            tapado = (t - 0.15) / 0.4
        elif t < 0.85:
            tapado = 1.0
        else:
            tapado = max(0.0, 1 - (t - 0.85) / 0.5)
        if tapado <= 0:
            return
        z = self._zona.adjusted(-1, -1, 1, 1)
        radio = z.height() / 2
        p.setOpacity(tapado)
        p.setBrush(QColor(30, 18, 12))
        p.setPen(QPen(QColor(255, 120, 40, 170), 1.5))    # borde todavía encendido
        p.drawRoundedRect(z, radio, radio)
        p.setPen(Qt.PenStyle.NoPen)
        p.setOpacity(1.0)

    def _pintar_llamas(self, p):
        """Llamas que crecen con un rebote, se balancean y titilan, y se achican al apagarse."""
        z = self._zona
        alto_base = z.height() * 2.4
        p.setOpacity(1.0)
        for corrimiento, tamano, demora, fase in self.LLAMAS:
            t = self._t - demora
            if t <= 0:
                continue
            if t < 1.0:
                crece = max(0.0, self._rebote(t / 0.3))
            else:
                crece = max(0.0, 1 - (t - 1.0) / 0.35)
            if crece <= 0:
                continue
            alto = alto_base * tamano * crece
            ancho = alto * 0.8
            # La base, un poco debajo del centro del contador.
            bx = z.center().x() + corrimiento * z.width()
            by = z.center().y() + z.height() * 0.3
            for i, capa in enumerate(self._capas_llama):
                f = fase + i * 1.3
                p.save()
                p.translate(bx, by)
                # Inclinar la punta de un lado al otro, como si la moviera el aire.
                p.shear(0.10 * math.sin(t * 8 + f), 0)
                p.scale(1 + 0.05 * math.sin(t * 23 + f),
                        1 + (0.07 + 0.03 * i) * math.sin(t * 17 + f))
                capa.render(p, QRectF(-ancho / 2, -alto, ancho, alto))
                p.restore()

    def _pintar_diamante(self, p):
        t, w, h = self._t, self.width(), self.height()
        salida = self._salida(4.0, 0.9)
        cx, cy = self._centro_diamante()

        # Se oscurece la ventana para que resalte.
        p.fillRect(self.rect(), QColor(0, 0, 0, int(150 * min(1.0, t / 0.4) * salida)))

        # Rayos de luz girando detrás.
        p.save()
        p.translate(cx, cy)
        p.rotate(t * 35)
        p.setOpacity(0.09 * min(1.0, t / 0.6) * salida)
        p.setBrush(QColor("#BFF6FF"))
        largo = math.hypot(w, h)
        for _ in range(12):
            p.rotate(30)
            p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(largo, -largo * 0.07),
                                     QPointF(largo, largo * 0.07)]))
        p.restore()

        # Marquesina: lamparitas alrededor de la ventana.
        p.setOpacity(salida * min(1.0, t / 0.3))
        _marquesina(p, w, h, int(t * 9), lambda i: QColor("#FFE08A"), QColor("#5A4A20"))

        # El diamante entra girando, se pasa de tamaño y vuelve; después
        # late apenas y cada tanto le cruza un destello.
        if t > 0.35:
            avance = (t - 0.35) / 0.7
            escala = 1.6 * max(0.0, self._rebote(avance)) * (1 + 0.04 * math.sin(t * 4))
            giro = -70 * (1 - min(1.0, avance))
            destello = ((t - 1.2) % 1.6) / 0.6 if t > 1.2 else -1
            p.setOpacity(salida)
            self._dibujar_gema(p, cx, cy, escala, giro, destello)

        # Estrellitas que titilan alrededor.
        if t > 0.9:
            for i in range(12):
                an = i * 2.39 + t * 0.3
                radio = 115 + (i * 37) % 45
                brillo = (math.sin(t * 6 + i * 1.7) + 1) / 2
                p.setOpacity(brillo * salida)
                self._dibujar_estrella(p, cx + math.cos(an) * radio * 1.6,
                                       cy + math.sin(an) * radio * 0.7, 4 + brillo * 8)

        if t > 1.2:
            p.setOpacity(min(1.0, (t - 1.2) / 0.4) * salida)
            p.setPen(QColor("#F2FCFF"))
            fuente = QFont(self.font())
            fuente.setPixelSize(24)
            fuente.setBold(True)
            p.setFont(fuente)
            p.drawText(QRectF(0, cy + 110, w, 40), Qt.AlignmentFlag.AlignCenter, "100 escaneos")
            p.setPen(Qt.PenStyle.NoPen)
        p.setOpacity(1.0)

    @staticmethod
    def _dibujar_estrella(p, x, y, r):
        puntos = []
        for i in range(8):
            radio = r if i % 2 == 0 else r * 0.28
            an = i * math.pi / 4
            puntos.append(QPointF(x + math.cos(an) * radio, y + math.sin(an) * radio))
        p.setBrush(QColor("#FFFFFF"))
        p.drawPolygon(QPolygonF(puntos))

    @staticmethod
    def _dibujar_gema(p, cx, cy, escala, giro, destello):
        """Diamante de frente: corona arriba, pabellón en punta abajo, en facetas."""
        def poligono(*xy):
            return QPolygonF([QPointF(xy[i], xy[i + 1]) for i in range(0, len(xy), 2)])

        p.save()
        p.translate(cx, cy)
        p.rotate(giro)
        p.scale(escala, escala)
        contorno = poligono(-46, -14, -26, -36, 26, -36, 46, -14, 0, 48)
        facetas = [
            ("#CFF7FF", poligono(-26, -36, -8, -14, -46, -14)),
            ("#E9FCFF", poligono(-26, -36, 26, -36, 8, -14, -8, -14)),
            ("#B5F1FC", poligono(26, -36, 46, -14, 8, -14)),
            ("#5CC9E0", poligono(-46, -14, -8, -14, 0, 48)),
            ("#9BE8F7", poligono(-8, -14, 8, -14, 0, 48)),
            ("#3FB0CC", poligono(8, -14, 46, -14, 0, 48)),
        ]
        for color, cara in facetas:
            p.setBrush(QColor(color))
            p.drawPolygon(cara)
        if 0 <= destello <= 1:
            p.save()
            camino = QPainterPath()
            camino.addPolygon(contorno)
            p.setClipPath(camino)
            sx = -80 + destello * 160
            p.setBrush(QColor(255, 255, 255, 190))
            p.drawPolygon(poligono(sx, -50, sx + 16, -50, sx - 14, 60, sx - 30, 60))
            p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 180), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(contorno)
        p.restore()


class ContadorEscaneos(QPushButton):
    """
    Cuántas imágenes se escanearon desde el último canje. Se puede canjear en
    cualquier momento y el festejo depende del escalón alcanzado: antes de
    META, apenas un fueguito que quema el número. Conviene aguantar sin
    canjear para llegar al siguiente. Un canje lo vuelve a cero.

    El color acompaña: apagado hasta 10 y de ahí, de a poco con cada escaneo,
    bronce, plata (25), oro (50) y diamante (100); más arriba, verde billete
    (250) y oro de jackpot (500). Desde el diamante, además brilla.

    Con el mouse encima no muestra un tooltip sino la semana (señal
    `senalado`, que la ventana usa para mostrar PanelSemana).
    """

    canjeado = pyqtSignal(int)      # el escalón canjeado; 0 antes de META
    senalado = pyqtSignal(bool)     # el mouse entró (True) o salió (False)
    META = 10
    ESCALONES = (10, 25, 50, 100, 250, 500)
    # (desde, hasta, (fondo, texto) al principio, (fondo, texto) al final).
    TRAMOS = [
        (10, 25, ("#CD7F32", "#2B1A08"), ("#C9CED6", "#2A2E35")),
        (25, 50, ("#C9CED6", "#2A2E35"), ("#FFC83D", "#3A2A00")),
        # El oro pasa por un champán claro antes del celeste: mezclados
        # directo, a mitad de camino dan verde.
        (50, 75, ("#FFC83D", "#3A2A00"), ("#F4EEDC", "#2E2A20")),
        (75, 100, ("#F4EEDC", "#2E2A20"), ("#9FF0FF", "#0B3A48")),
    ]

    def __init__(self, valor=0, parent=None):
        super().__init__(parent)
        self.setObjectName("contadorEscaneos")
        self.clicked.connect(self._canjear)
        self._brillo = QTimer(self)
        self._brillo.timeout.connect(self._pintar)
        self.set_valor(valor)

    @staticmethod
    def _mezcla(a, b, t):
        a, b = QColor(a), QColor(b)
        return QColor(round(a.red() + (b.red() - a.red()) * t),
                      round(a.green() + (b.green() - a.green()) * t),
                      round(a.blue() + (b.blue() - a.blue()) * t))

    def colores(self):
        """(fondo, texto) para el valor actual, o None si todavía está apagado."""
        v = self.valor
        if v < self.META:
            return None
        if v >= 100:
            # Brillo: va y viene entre el color del escalón y uno más claro.
            t = (math.sin(time.perf_counter() * 3) + 1) / 2
            if v >= 500:
                return self._mezcla("#FFB300", "#FFE08A", t), QColor("#3A2A00")
            if v >= 250:
                return self._mezcla("#4FBF5A", "#B9F5AE", t), QColor("#173404")
            return self._mezcla("#9FF0FF", "#F2FCFF", t), QColor("#0B3A48")
        for desde, hasta, (f0, t0), (f1, t1) in self.TRAMOS:
            if v < hasta:
                k = (v - desde) / (hasta - desde)
                return self._mezcla(f0, f1, k), self._mezcla(t0, t1, k)

    def escalon(self):
        """El escalón más alto alcanzado: 0 antes de META, None si está en cero."""
        if self.valor == 0:
            return None
        alcanzados = [e for e in self.ESCALONES if self.valor >= e]
        return alcanzados[-1] if alcanzados else 0

    def set_valor(self, valor):
        self.valor = max(0, int(valor))
        self.setText(str(self.valor))
        listo = self.valor > 0
        self.setEnabled(listo)
        self.setCursor(Qt.CursorShape.PointingHandCursor if listo
                       else Qt.CursorShape.ArrowCursor)
        self._animar()

    def _animar(self):
        if self.valor >= 100:
            self._brillo.start(80)
        else:
            self._brillo.stop()
        self._pintar()

    def _pintar(self):
        colores = self.colores()
        if colores is None:
            self.setStyleSheet("")     # el gris apagado de la hoja general
            return
        fondo, texto = colores
        self.setStyleSheet(
            f"#contadorEscaneos {{ background-color: {fondo.name()}; color: {texto.name()};"
            f" border: 1px solid {fondo.lighter(115).name()}; font-weight: bold; }}"
            f"#contadorEscaneos:hover {{ background-color: {fondo.lighter(110).name()}; }}"
            f"#contadorEscaneos:pressed {{ background-color: {fondo.darker(115).name()}; }}"
        )

    def sumar(self, cantidad=1):
        self.set_valor(self.valor + cantidad)

    def _canjear(self):
        escalon = self.escalon()
        if escalon is not None:
            self.canjeado.emit(escalon)

    def enterEvent(self, event):
        self.senalado.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.senalado.emit(False)
        super().leaveEvent(event)


DIAS_SEMANA = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def _hoy():
    return datetime.date.today().isoformat()


def _semana(por_dia, hoy=None):
    """
    Los días de la semana de `hoy` como (etiqueta, fichas, es hoy, todavía no
    llegó). De lunes a viernes siempre; sábado y domingo solo si hubo
    escaneos o si es hoy.
    """
    hoy = hoy or datetime.date.today()
    lunes = hoy - datetime.timedelta(days=hoy.weekday())
    dias = []
    for i, etiqueta in enumerate(DIAS_SEMANA):
        dia = lunes + datetime.timedelta(days=i)
        n = por_dia.get(dia.isoformat(), 0)
        if i >= 5 and n == 0 and dia != hoy:
            continue
        dias.append((etiqueta, n, dia == hoy, dia > hoy))
    return dias


def _record_previo(por_dia, hoy):
    """(fichas, fecha) del mejor día de siempre sin contar `hoy`; (0, None) si no hay otro día."""
    otros = [(n, dia) for dia, n in por_dia.items() if dia != hoy]
    return max(otros) if otros else (0, None)


class PanelSemana(QWidget):
    """
    Los escaneos de cada día de la semana en barras, con el récord de siempre
    como una línea punteada. Aparece arriba del contador mientras el mouse
    está encima y no toma clics.
    """

    ANCHO, ALTO = 250, 146
    BASE = 98       # dónde apoyan las barras
    MAXIMO = 52     # alto de la barra más alta

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(self.ANCHO, self.ALTO)
        self._dias, self._record, self._fecha, self._pie = [], 0, None, ""
        self.hide()

    def mostrar(self, dias, record, fecha_record, pie, esquina):
        """`esquina` es el punto (en el padre) donde va la esquina de abajo a la derecha."""
        self._dias, self._record, self._fecha, self._pie = dias, record, fecha_record, pie
        self.setFixedSize(self.ANCHO, self.ALTO if pie else self.ALTO - 22)
        self.move(max(4, esquina.x() - self.width()), esquina.y() - self.height())
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(C["borde"]), 1))
        p.setBrush(QColor(C["flotante"]))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)

        fuente = QFont(self.font())
        fuente.setPixelSize(12)
        p.setFont(fuente)
        p.setPen(QColor(C["texto2"]))
        p.drawText(QRectF(12, 8, w - 24, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Esta semana")
        if self._record > 0:
            dia, mes = self._fecha[8:10], self._fecha[5:7]
            record = f"Récord: {self._record} ({dia}/{mes})"
        else:
            record = "Todavía sin récord"
        p.setPen(QColor(C["dorado"]))
        p.drawText(QRectF(12, 8, w - 24, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   record)

        if self._dias:
            maximo = max([self._record, 1] + [n for _, n, _, _ in self._dias])
            hueco = 8
            ancho = (w - 24 - hueco * (len(self._dias) - 1)) / len(self._dias)
            # La línea del récord va primero, detrás de las barras: así no
            # tacha los números.
            if self._record > 0:
                lapiz = QPen(QColor(C["dorado"]), 1)
                lapiz.setDashPattern([3, 3])
                p.setPen(lapiz)
                y = self.BASE - self._record / maximo * self.MAXIMO
                p.drawLine(QLineF(8, y, w - 8, y))
            fuente.setPixelSize(11)
            p.setFont(fuente)
            for i, (etiqueta, n, es_hoy, futuro) in enumerate(self._dias):
                x = 12 + i * (ancho + hueco)
                if not futuro:
                    alto = max(2, round(n / maximo * self.MAXIMO)) if n > 0 else 0
                    if n > 0:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor("#FFC83D" if es_hoy else C["barra_semana"]))
                        p.drawRoundedRect(QRectF(x, self.BASE - alto, ancho, alto), 3, 3)
                    # El número adentro de la barra si entra; si no, arriba.
                    adentro = alto >= 18
                    if adentro:
                        p.setPen(QColor("#3A2A00" if es_hoy else C["texto"]))
                        caja = QRectF(x, self.BASE - alto + 2, ancho, 14)
                    else:
                        p.setPen(QColor(C["dorado_texto"] if es_hoy else C["texto2"]))
                        caja = QRectF(x - 4, self.BASE - alto - 16, ancho + 8, 14)
                    p.drawText(caja, Qt.AlignmentFlag.AlignCenter, str(n))
                p.setPen(QColor(C["marca_baja"] if futuro else C["tenue"]))
                p.drawText(QRectF(x - 4, self.BASE + 3, ancho + 8, 14),
                           Qt.AlignmentFlag.AlignCenter, etiqueta)
        if self._pie:
            p.setPen(QColor(C["tenue2"]))
            p.drawText(QRectF(12, h - 26, w - 24, 18), Qt.AlignmentFlag.AlignCenter, self._pie)


class BotonCofre(QWidget):
    """El cofre sorpresa esperando al lado del contador: se hamaca hasta que lo abren."""

    abierto = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Cofre sorpresa: clic para abrirlo")
        self._inicio = time.perf_counter()
        self._reloj = QTimer(self)
        self._reloj.timeout.connect(self.update)

    def showEvent(self, event):
        self._reloj.start(33)
        super().showEvent(event)

    def hideEvent(self, event):
        self._reloj.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.abierto.emit()

    def paintEvent(self, event):
        t = time.perf_counter() - self._inicio
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        # Se hamaca a golpes, cada poco más de un segundo, y quieto entre uno y otro.
        golpe = max(0.0, math.sin(t * 2.5)) ** 2
        p.translate(self.width() / 2, self.height() - 4)
        p.rotate(math.sin(t * 14) * 12 * golpe)
        p.translate(0, -abs(math.sin(t * 7)) * 3 * golpe)
        p.setBrush(QColor("#8B5A2B"))
        p.drawRoundedRect(QRectF(-10, -11, 20, 11), 2, 2)
        p.setBrush(QColor("#A0683A"))
        p.drawRoundedRect(QRectF(-11, -17, 22, 7), 3, 3)
        p.setBrush(QColor("#FFC83D"))
        p.drawRect(QRectF(-7, -17, 3, 17))
        p.drawRect(QRectF(4, -17, 3, 17))
        p.drawRoundedRect(QRectF(-2.5, -13, 5, 6), 1, 1)


COFRE_PROBABILIDAD = 0.01   # después de cada escaneo
COFRES_POR_DIA = 2


class Spinner(QWidget):
    """Ruedita de espera: un arco que gira mientras algo está en curso."""

    def __init__(self, lado=16, color=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(lado, lado)
        self._color = QColor(color or C["link"])
        self._angulo = 0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360)
        self._anim.setDuration(900)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._girar)
        self.hide()

    def _girar(self, angulo):
        self._angulo = angulo
        self.update()

    def start(self):
        self.show()
        # Como la barra de espera: con las animaciones de Windows apagadas,
        # queda quieta.
        if (QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo)
                and self._anim.state() != QVariantAnimation.State.Running):
            self._anim.start()

    def stop(self):
        self._anim.stop()
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grosor = max(2.0, self.width() / 8)
        caja = QRectF(self.rect()).adjusted(grosor, grosor, -grosor, -grosor)
        pista = QColor(self._color)
        pista.setAlpha(50)
        p.setPen(QPen(pista, grosor))
        p.drawEllipse(caja)
        p.setPen(QPen(self._color, grosor, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        # drawArc mide en dieciseisavos de grado, en sentido antihorario.
        p.drawArc(caja, int(-self._angulo * 16), 100 * 16)


class FlatComboBox(QComboBox):
    """
    Desplegable plano. El que dibuja Windows por defecto trae un botón con
    relieve y una flecha negra que no pegan con el resto de la ventana; acá el
    marco lo pone la hoja de estilos y la flecha se dibuja a mano.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flecha = None     # (color, pixmap): se rehace si cambia el tema
        # Con este delegado la lista desplegada respeta la hoja de estilos
        # (alto y color de cada renglón).
        self.setItemDelegate(QStyledItemDelegate(self))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._flecha is None or self._flecha[0] != C["tenue"]:
            self._flecha = (C["tenue"], icon_pixmap("flecha_abajo", C["tenue"], 14))
        painter = QPainter(self)
        painter.drawPixmap(self.width() - 14 - 10, (self.height() - 14) // 2, self._flecha[1])


# Versión corta de los avisos y errores del registro, para la línea de abajo.
# Lo que no está en la lista se resume cortando en la primera pausa.
_AVISOS_CORTOS = (
    ("no acepto", "El escáner no aceptó esa resolución"),
    ("toca el borde", "El documento toca el borde"),
    ("no se detecto el documento", "No se detectó el documento"),
    ("muy por debajo", "Resolución más baja que la pedida"),
    ("destino configurado no está disponible", "Destino no disponible"),
    ("No se detectó ningún escáner", "No hay escáner conectado"),
    ("Error durante el escaneo", "Error al escanear"),
    ("Error en procesamiento", "Error al procesar la imagen"),
    ("Error procesando imagen local", "Error al procesar el archivo"),
    ("no se pudo guardar", "No se pudo guardar la configuración"),
)


def _aviso_corto(message):
    for clave, corto in _AVISOS_CORTOS:
        if clave in message:
            return corto
    texto = message.split(": ", 1)[-1] if message.startswith("AVISO") else message
    for corte in (". ", " (", ": "):
        texto = texto.split(corte, 1)[0]
    texto = texto.rstrip(".")
    return texto[:1].upper() + texto[1:]


def _fmt_mb(mb):
    """Tamaño en MB como se escribe aca: con coma, y sin decimales desde 10."""
    return (f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB").replace(".", ",")


def _porcentaje(hecho, total):
    return int(100 * hecho / total) if total else 0


class ElidedLabel(QLabel):
    """
    Etiqueta de una linea que recorta el texto con "…" cuando no entra, en vez
    de imponerle su ancho a la ventana. Avisa cuando le hacen clic.
    """
    clicked = pyqtSignal()

    def __init__(self, text="", mode=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(text, parent)
        self._mode = mode

    def minimumSizeHint(self):
        return QSize(20, super().minimumSizeHint().height())

    def paintEvent(self, event):
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), self._mode, rect.width())
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _manchas(p, colores, x, y, radio, paso, aro):
    """
    Los cinco colores de un tema como círculos solapados, de izquierda a
    derecha a partir del centro (x, y). Cada uno lleva un aro del color de
    lo que tiene atrás (`aro`), así se distinguen aunque se toquen.
    """
    for i, clave in enumerate(temas.BASE):
        centro = QPointF(x + i * paso, y)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(aro))
        p.drawEllipse(centro, radio + 2, radio + 2)
        # Un filete fino: si no, un color parecido al de atrás se pierde.
        p.setPen(QPen(QColor(temas.mezcla(colores[clave], C["texto"], 0.25)), 1))
        p.setBrush(QColor(colores[clave]))
        p.drawEllipse(centro, radio - 0.5, radio - 0.5)


class PaletaTemas(QWidget):
    """
    El selector de temas, que se despliega bajo el botón de la paleta. Cada
    tema es un renglón con sus cinco colores en círculos solapados, como
    manchas de pintura. Pasar el mouse por un tema lo muestra en la ventana;
    un clic lo elige, y si se cierra sin elegir vuelve el que estaba. Los
    temas propios tienen además un lápiz y un tacho. El último renglón agrega
    uno nuevo.

    Se pinta con los colores que había al abrirlo: si cambiara con cada tema
    que se mira, bailaría bajo el mouse.
    """

    ANCHO = 290
    SOMBRA = 14         # margen transparente alrededor, para la sombra
    TITULO = 34
    FILA = 42
    RADIO = 10
    PASO = 13           # cuánto se corre cada círculo respecto del anterior
    LADO_ICONO = 26     # el lápiz y el tacho

    def __init__(self, ventana, lista, actual):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._v = ventana
        self._lista = lista             # [(tema, es propio)]
        self._actual = actual           # nombre del tema elegido
        self._c = dict(C)
        self._fila = None               # renglón bajo el mouse; len(lista) es "Agregar"
        self._boton = None              # "lapiz" o "tacho" bajo el mouse
        self._mostrado = actual         # el tema que se ve ahora en la ventana
        self._alto = self.TITULO + (len(lista) + 1) * self.FILA + 8
        self.setFixedSize(self.ANCHO + 2 * self.SOMBRA, self._alto + 2 * self.SOMBRA)
        self._iconos = {n: icon_pixmap(n, self._c["tenue"], 16) for n in ("lapiz", "tacho")}
        self._iconos["tilde"] = icon_pixmap("tilde", self._c["link"], 16)
        self._iconos["mas"] = icon_pixmap("mas", self._c["link"], 14)
        # Se despliega: el panel crece hacia abajo y en cada renglón los
        # círculos se abren en abanico, uno detrás del otro.
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(360)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._avanzar)
        if QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo):
            self._t = 0.0
            self._anim.start()

    def _avanzar(self, t):
        self._t = t
        self.update()

    # --- Geometría ---

    def _panel(self):
        return QRectF(self.SOMBRA, self.SOMBRA, self.ANCHO, self._alto)

    def _rect_fila(self, i):
        return QRectF(self.SOMBRA + 6, self.SOMBRA + self.TITULO + i * self.FILA, self.ANCHO - 12, self.FILA)

    def _rect_boton(self, i, cual):
        r = self._rect_fila(i)
        x = r.right() - 8 - self.LADO_ICONO * (2 if cual == "lapiz" else 1)
        return QRectF(x, r.center().y() - self.LADO_ICONO / 2, self.LADO_ICONO, self.LADO_ICONO)

    def _donde(self, pos):
        """(renglón, botón) en el punto `pos`."""
        for i in range(len(self._lista) + 1):
            if self._rect_fila(i).contains(QPointF(pos)):
                if i < len(self._lista) and self._lista[i][1]:
                    for cual in ("lapiz", "tacho"):
                        if self._rect_boton(i, cual).contains(QPointF(pos)):
                            return i, cual
                return i, None
        return None, None

    # --- Lo que pasa en la ventana ---

    def _mostrar_fila(self, fila):
        """Muestra en la ventana el tema del renglón (o el elegido, si no hay ninguno)."""
        if fila is not None and fila < len(self._lista):
            tema = self._lista[fila][0]
        else:
            tema = self._v.tema_actual()
        if tema["nombre"] != self._mostrado:
            self._mostrado = tema["nombre"]
            self._v.aplicar_tema(tema["colores"])

    def _marcar(self, fila, boton):
        if (fila, boton) != (self._fila, self._boton):
            self._fila, self._boton = fila, boton
            self.update()
        self._mostrar_fila(fila)

    def mouseMoveEvent(self, event):
        self._marcar(*self._donde(event.position()))

    def leaveEvent(self, event):
        self._marcar(None, None)

    def mousePressEvent(self, event):
        if not self._panel().contains(event.position()):
            self.close()
            return
        fila, boton = self._donde(event.position())
        if fila is not None and event.button() == Qt.MouseButton.LeftButton:
            self._activar(fila, boton)

    def keyPressEvent(self, event):
        tecla = event.key()
        n = len(self._lista) + 1
        if tecla in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            paso = 1 if tecla == Qt.Key.Key_Down else -1
            if self._fila is None:
                fila = 0 if paso > 0 else n - 1
            else:
                fila = (self._fila + paso) % n
            self._marcar(fila, None)
        elif tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self._fila is not None:
            self._activar(self._fila, None)
        else:
            super().keyPressEvent(event)

    def _activar(self, fila, boton):
        # Primero se cierra (y vuelve el tema elegido): lo que sigue puede
        # abrir un diálogo, y no tiene que quedar el que se estaba mirando.
        self.close()
        if fila == len(self._lista):
            self._v.nuevo_tema()
            return
        tema = self._lista[fila][0]
        if boton == "lapiz":
            self._v.editar_tema(tema)
        elif boton == "tacho":
            self._v.borrar_tema(tema)
        else:
            self._v.elegir_tema(tema)

    def closeEvent(self, event):
        self._anim.stop()
        self._mostrar_fila(None)
        super().closeEvent(event)

    # --- Dibujo ---

    def paintEvent(self, event):
        c = self._c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = self._panel()
        # El panel se despliega hacia abajo desde el botón.
        visible = QRectF(panel)
        visible.setHeight(max(self.TITULO, panel.height() * self._t))

        # Sombra suave: capas cada vez más grandes y más transparentes.
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self.SOMBRA, 0, -2):
            p.setBrush(QColor(0, 0, 0, int(36 * (1 - i / self.SOMBRA) ** 2 * self._t)))
            p.drawRoundedRect(visible.adjusted(-i, -i + 4, i, i + 4), 10 + i, 10 + i)
        p.setPen(QPen(QColor(c["borde"]), 1))
        p.setBrush(QColor(c["flotante"]))
        p.drawRoundedRect(visible.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.setClipRect(visible)

        fuente = QFont(self.font())
        fuente.setPixelSize(12)
        p.setFont(fuente)
        p.setPen(QColor(c["tenue"]))
        p.drawText(QRectF(panel.left() + 16, panel.top(), panel.width() - 32, self.TITULO),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Temas")
        fuente.setPixelSize(13)
        p.setFont(fuente)

        n = len(self._lista)
        for i in range(n + 1):
            r = self._rect_fila(i)
            # Cada renglón llega un poco después que el anterior.
            escalon = min(0.05, 0.5 / (n + 1))
            k = min(1.0, max(0.0, (self._t - escalon * i) / (1 - escalon * n)))
            if k <= 0:
                continue
            p.setOpacity(k)
            if i == self._fila:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(c["paneles_hover"]))
                p.drawRoundedRect(r, 7, 7)
            cx, cy = r.left() + 10 + self.RADIO, r.center().y()
            texto_x = cx + self.RADIO + 4 * self.PASO + 14
            caja_texto = QRectF(texto_x, r.top(), r.right() - texto_x - 64, r.height())

            if i == n:
                # "Agregar": un círculo punteado con un más.
                lapiz = QPen(QColor(c["link"]), 1.4)
                lapiz.setDashPattern([2.5, 2.5])
                p.setPen(lapiz)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), self.RADIO, self.RADIO)
                p.drawPixmap(QPointF(cx - 7, cy - 7), self._iconos["mas"])
                p.setPen(QColor(c["link"]))
                p.drawText(QRectF(cx + self.RADIO + 12, r.top(), 200, r.height()),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Agregar tema")
                continue

            tema, propio = self._lista[i]
            _manchas(p, tema["colores"], cx, cy, self.RADIO, self.PASO * k,
                     c["paneles_hover"] if i == self._fila else c["flotante"])
            p.setPen(QColor(c["texto"]))
            nombre = p.fontMetrics().elidedText(tema["nombre"], Qt.TextElideMode.ElideRight,
                                                int(caja_texto.width()))
            p.drawText(caja_texto, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, nombre)
            if propio and i == self._fila:
                for cual in ("lapiz", "tacho"):
                    caja = self._rect_boton(i, cual)
                    if cual == self._boton:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(c["borde"]))
                        p.drawRoundedRect(caja, 6, 6)
                    p.drawPixmap(QPointF(caja.center().x() - 8, caja.center().y() - 8), self._iconos[cual])
            elif tema["nombre"] == self._actual:
                p.drawPixmap(QPointF(r.right() - 30, cy - 8), self._iconos["tilde"])
        p.setOpacity(1.0)


class MuestraTema(QWidget):
    """La ventana en miniatura, pintada con los colores que se están eligiendo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(214)
        self._c = temas.paleta(temas.POR_DEFECTO["colores"])

    def set_colores(self, colores):
        self._c = temas.paleta(colores)
        self.update()

    def paintEvent(self, event):
        c = self._c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ventana = QRectF(0.5, 0.5, w - 1, h - 1)
        p.setPen(QPen(QColor(C["borde"]), 1))
        p.setBrush(QColor(c["fondo"]))
        p.drawRoundedRect(ventana, 8, 8)
        fuente = QFont(self.font())
        fuente.setPixelSize(10)
        p.setFont(fuente)
        izq = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        def pastilla(x, y, ancho, alto, radio=4, fondo=None, borde=None):
            p.setPen(QPen(QColor(borde or c["borde"]), 1) if borde is not False else Qt.PenStyle.NoPen)
            p.setBrush(QColor(fondo or c["paneles"]))
            p.drawRoundedRect(QRectF(x + 0.5, y + 0.5, ancho, alto), radio, radio)

        # Arriba: el escáner y los botones chicos.
        p.setPen(QColor(c["tenue"]))
        p.drawText(QRectF(14, 10, 50, 20), izq, "Escáner")
        pastilla(58, 10, 96, 20)
        p.setPen(QColor(c["texto2"]))
        p.drawText(QRectF(66, 10, 80, 20), izq, "Auto-Detectar")
        for i in range(3):
            pastilla(w - 14 - 26 - i * 32, 10, 26, 20)
        # El destino, con el enlace.
        p.setPen(QColor(c["tenue"]))
        p.drawText(QRectF(14, 36, 120, 16), izq, "H:\\escaneos")
        p.setPen(QColor(c["link"]))
        p.drawText(QRectF(84, 36, 120, 16), izq, "Cambiar destino")
        # La ficha escaneada: siempre es papel.
        hoja = QRectF(w / 2 - 44, 60, 88, 82)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, min(120, c["sombra_alfa"])))
        p.drawRoundedRect(hoja.translated(0, 4), 3, 3)
        p.setBrush(QColor("#F7F5EF"))
        p.drawRoundedRect(hoja, 3, 3)
        p.setBrush(QColor("#C9C5BA"))
        for j in range(5):
            p.drawRect(QRectF(hoja.left() + 10, hoja.top() + 14 + j * 12, 68 - (j % 2) * 22, 3))
        # El botón de escanear y el manual.
        boton = QRectF(14, 152, w - 28 - 36, 30)
        p.setBrush(QColor(c["escanear"]))
        p.drawRoundedRect(boton, 5, 5)
        fuente.setPixelSize(11)
        fuente.setBold(True)
        p.setFont(fuente)
        p.setPen(QColor(c["sobre_escanear"]))
        p.drawText(boton, Qt.AlignmentFlag.AlignCenter, "Iniciar escaneo")
        pastilla(w - 14 - 30, 152, 30, 30, 5)
        # Abajo: la calidad, el registro y el contador (que no cambia de color).
        fuente.setBold(False)
        fuente.setPixelSize(10)
        p.setFont(fuente)
        p.setPen(QColor(c["tenue"]))
        p.drawText(QRectF(14, 190, 50, 16), izq, "Calidad")
        pastilla(58, 192, 80, 12, 6, c["apagado"], c["apagado_borde"])
        pastilla(84, 193, 9, 10, 4, c["tirador"], False)
        p.setPen(QColor(c["link"]))
        p.drawText(QRectF(w - 110, 190, 60, 16), izq, "Registro")
        pastilla(w - 14 - 34, 190, 34, 16, 8, "#C9CED6", "#D9DEE5")
        p.setPen(QColor("#2A2E35"))
        fuente.setBold(True)
        p.setFont(fuente)
        p.drawText(QRectF(w - 14 - 34, 190, 34, 17), Qt.AlignmentFlag.AlignCenter, "27")


class SelectorPastel(QWidget):
    """
    Los colores para elegir uno de los cinco de un tema: pasteles medios como
    gotas de pintura (temas.PASTELES), una fila de neutros y, al final, "Otro
    color…" para el selector completo. Las gotas aparecen de a una, en onda.

    `al_mirar(color)` se llama al pasar el mouse por una gota (con None al
    salir), `al_elegir(color)` con el clic, y `al_otro()` con "Otro color…".
    """

    SOMBRA = 14
    CELDA = 34
    RADIO = 12
    TITULO = 34
    HUECO = 10          # entre los pasteles y los neutros
    PIE = 34            # "Otro color…"

    def __init__(self, titulo, actual, al_mirar, al_elegir, al_otro):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._titulo = titulo
        self._actual = actual.upper()
        self._mirar, self._elegir, self._otro = al_mirar, al_elegir, al_otro
        self._filas = temas.PASTELES + [temas.NEUTROS]
        self._columnas = len(self._filas[0])
        self._ancho = 12 * 2 + self._columnas * self.CELDA
        self._alto = self.TITULO + len(self._filas) * self.CELDA + self.HUECO + self.PIE + 6
        self.setFixedSize(self._ancho + 2 * self.SOMBRA, self._alto + 2 * self.SOMBRA)
        self._c = dict(C)
        self._sobre = None          # (fila, columna) bajo el mouse, o "otro"
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(420)
        self._anim.valueChanged.connect(self._avanzar)
        if QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo):
            self._t = 0.0
            self._anim.start()

    def _avanzar(self, t):
        self._t = t
        self.update()

    def _centro(self, fila, columna):
        x = self.SOMBRA + 12 + columna * self.CELDA + self.CELDA / 2
        y = self.SOMBRA + self.TITULO + fila * self.CELDA + self.CELDA / 2
        if fila == len(self._filas) - 1:
            y += self.HUECO
        return QPointF(x, y)

    def _rect_otro(self):
        return QRectF(self.SOMBRA + 8, self.SOMBRA + self._alto - self.PIE - 4, self._ancho - 16, self.PIE)

    def _donde(self, pos):
        for f, fila in enumerate(self._filas):
            for col in range(len(fila)):
                d = self._centro(f, col) - QPointF(pos)
                if d.x() ** 2 + d.y() ** 2 <= (self.CELDA / 2) ** 2:
                    return (f, col)
        if self._rect_otro().contains(QPointF(pos)):
            return "otro"
        return None

    def _color(self, sobre):
        return self._filas[sobre[0]][sobre[1]] if isinstance(sobre, tuple) else None

    def _marcar(self, sobre):
        if sobre != self._sobre:
            self._sobre = sobre
            self._mirar(self._color(sobre))
            self.update()

    def mouseMoveEvent(self, event):
        self._marcar(self._donde(event.position()))

    def leaveEvent(self, event):
        self._marcar(None)

    def mousePressEvent(self, event):
        sobre = self._donde(event.position())
        if event.button() != Qt.MouseButton.LeftButton or sobre is None:
            self.close()
            return
        self._activar(sobre)

    def _activar(self, sobre):
        self._sobre = None
        self.close()
        if sobre == "otro":
            self._otro()
        else:
            self._elegir(self._color(sobre))

    def keyPressEvent(self, event):
        # Flechas para moverse entre las gotas; Enter elige.
        tecla = event.key()
        movs = {Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1),
                Qt.Key.Key_Up: (-1, 0), Qt.Key.Key_Down: (1, 0)}
        if tecla in movs:
            f, col = self._sobre if isinstance(self._sobre, tuple) else (0, -1 if tecla == Qt.Key.Key_Right else 0)
            df, dc = movs[tecla]
            self._marcar(((f + df) % len(self._filas), (col + dc) % self._columnas))
        elif tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self._sobre is not None:
            self._activar(self._sobre)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._anim.stop()
        if self._sobre is not None:
            self._mirar(None)
        super().closeEvent(event)

    def paintEvent(self, event):
        c = self._c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.SOMBRA, self.SOMBRA, self._ancho, self._alto)
        aparece = min(1.0, self._t * 3)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self.SOMBRA, 0, -2):
            p.setBrush(QColor(0, 0, 0, int(36 * (1 - i / self.SOMBRA) ** 2 * aparece)))
            p.drawRoundedRect(panel.adjusted(-i, -i + 4, i, i + 4), 10 + i, 10 + i)
        p.setOpacity(aparece)
        p.setPen(QPen(QColor(c["borde"]), 1))
        p.setBrush(QColor(c["flotante"]))
        p.drawRoundedRect(panel.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        fuente = QFont(self.font())
        fuente.setPixelSize(12)
        p.setFont(fuente)
        p.setPen(QColor(c["tenue"]))
        p.drawText(QRectF(panel.left() + 16, panel.top(), panel.width() - 32, self.TITULO),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._titulo)
        p.setOpacity(1.0)

        # Las gotas llegan en onda, en diagonal desde arriba a la izquierda,
        # y cada una crece con un rebotito.
        total = len(self._filas) + self._columnas - 2
        for f, fila in enumerate(self._filas):
            for col, color in enumerate(fila):
                k = min(1.0, max(0.0, (self._t - 0.45 * (f + col) / total) / 0.55))
                if k <= 0:
                    continue
                crece = 1 + 0.25 * math.sin(math.pi * k) * (1 - k) * 2 if k < 1 else 1.0
                radio = self.RADIO * min(k * 1.4, 1.0) * crece
                if (f, col) == self._sobre:
                    radio += 2.5
                centro = self._centro(f, col)
                if color == self._actual:
                    p.setPen(QPen(QColor(c["texto"]), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(centro, radio + 4, radio + 4)
                p.setPen(QPen(QColor(temas.mezcla(color, c["texto"], 0.2)), 1))
                p.setBrush(QColor(color))
                p.drawEllipse(centro, radio, radio)

        r = self._rect_otro()
        if self._sobre == "otro":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["paneles_hover"]))
            p.drawRoundedRect(r, 7, 7)
        p.setOpacity(aparece)
        p.setPen(QColor(c["link"]))
        p.setFont(fuente)
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Otro color…")


class CirculoColor(QWidget):
    """Uno de los cinco colores de un tema: un círculo grande que se elige con un clic."""

    cambiado = pyqtSignal()

    def __init__(self, clave, color, parent=None):
        super().__init__(parent)
        self.clave = clave
        self.color = color
        self.setFixedSize(76, 86)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{temas.AYUDA_BASE[clave]}. Clic para cambiarlo.")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def elegir(self):
        """Despliega los pasteles debajo del círculo."""
        original = self.color

        def mirar(color):
            # Mientras el mouse pasa por los colores, la muestra los va probando.
            self._poner(color or original)

        def elegido(color):
            nonlocal original
            original = color
            self._poner(color)

        selector = SelectorPastel(temas.NOMBRES_BASE[self.clave], original, mirar, elegido,
                                  self._otro_color)
        abajo = self.mapToGlobal(QPoint(self.width() // 2, 58))
        x = abajo.x() - selector.width() // 2
        y = abajo.y()
        pantalla = self.screen().availableGeometry() if self.screen() else None
        if pantalla is not None:
            x = max(pantalla.left(), min(x, pantalla.right() - selector.width()))
            if y + selector.height() > pantalla.bottom():
                y = self.mapToGlobal(QPoint(0, 0)).y() - selector.height()
        selector.move(x, y)
        self._selector = selector       # si nadie la guarda, Python la borra (ver abrir_paleta)
        selector.show()
        selector.setFocus()

    def _otro_color(self):
        """El selector completo de Qt, para quien quiera un color fuera de la paleta."""
        nombre = temas.NOMBRES_BASE[self.clave]
        elegido = QColorDialog.getColor(QColor(self.color), self.window(), f"Color: {nombre}")
        if elegido.isValid():
            self._poner(elegido.name().upper())

    def _poner(self, color):
        if color != self.color:
            self.color = color
            self.update()
            self.cambiado.emit()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.elegir()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.elegir()
        else:
            super().keyPressEvent(event)

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def focusInEvent(self, event):
        self.update()

    def focusOutEvent(self, event):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centro = QPointF(self.width() / 2, 28)
        resaltado = self.underMouse() or self.hasFocus()
        if resaltado:
            p.setPen(QPen(QColor(C["acento"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(centro, 27, 27)
        p.setPen(QPen(QColor(C["borde"]), 1))
        p.setBrush(QColor(self.color))
        p.drawEllipse(centro, 23, 23)
        fuente = QFont(self.font())
        fuente.setPixelSize(12)
        p.setFont(fuente)
        p.setPen(QColor(C["texto2"] if resaltado else C["tenue"]))
        p.drawText(QRectF(0, 58, self.width(), 16), Qt.AlignmentFlag.AlignCenter,
                   temas.NOMBRES_BASE[self.clave])
        fuente.setPixelSize(10)
        p.setFont(fuente)
        p.setPen(QColor(C["apagado_texto"]))
        p.drawText(QRectF(0, 72, self.width(), 14), Qt.AlignmentFlag.AlignCenter, self.color)


class EditorTema(QDialog):
    """Para armar un tema nuevo o cambiar uno propio: un nombre y cinco colores."""

    def __init__(self, ventana, colores, nombre="", editando=False):
        super().__init__(ventana)
        self.setWindowTitle("Editar tema" if editando else "Nuevo tema")
        self.setFixedWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(4)
        titulo = QLabel("Editar tema" if editando else "Nuevo tema")
        titulo.setObjectName("acercaTitulo")
        layout.addWidget(titulo)
        layout.addSpacing(12)

        lbl_nombre = QLabel("Nombre")
        lbl_nombre.setObjectName("mutedLabel")
        layout.addWidget(lbl_nombre)
        self.txt_nombre = QLineEdit(nombre)
        self.txt_nombre.setPlaceholderText("Mi tema")
        self.txt_nombre.setMaxLength(30)
        layout.addWidget(self.txt_nombre)
        layout.addSpacing(12)

        lbl_colores = QLabel("Colores: hacé clic en cada uno para cambiarlo")
        lbl_colores.setObjectName("mutedLabel")
        layout.addWidget(lbl_colores)
        fila = QHBoxLayout()
        fila.setSpacing(0)
        self.circulos = []
        for clave in temas.BASE:
            circulo = CirculoColor(clave, colores[clave])
            circulo.cambiado.connect(self._actualizar)
            self.circulos.append(circulo)
            fila.addWidget(circulo)
        layout.addLayout(fila)
        layout.addSpacing(8)

        self.muestra = MuestraTema()
        layout.addWidget(self.muestra)
        self.lbl_nota = QLabel()
        self.lbl_nota.setObjectName("mutedLabel")
        self.lbl_nota.setWordWrap(True)
        layout.addWidget(self.lbl_nota)
        layout.addSpacing(10)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("secondaryButton")
        btn_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancelar.clicked.connect(self.reject)
        btn_guardar = QPushButton(" Guardar")
        btn_guardar.setIcon(icon("tilde", C["sobre_acento"]))
        btn_guardar.setIconSize(QSize(16, 16))
        btn_guardar.setObjectName("updateButton")
        btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_guardar.setDefault(True)
        btn_guardar.clicked.connect(self.accept)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(btn_cancelar)
        botones.addWidget(btn_guardar)
        layout.addLayout(botones)
        self._actualizar()

    def colores(self):
        return {c.clave: c.color for c in self.circulos}

    def nombre(self):
        return self.txt_nombre.text().strip() or self.txt_nombre.placeholderText()

    def _actualizar(self):
        colores = self.colores()
        self.muestra.set_colores(colores)
        self.lbl_nota.setText(
            "El texto no se leía bien sobre ese fondo: se ajustó un poco para que se lea."
            if temas.paleta(colores)["texto_ajustado"] else "")


class ScannerApp(QMainWindow):
    # Lo que se hace en segundo plano para las actualizaciones avisa por acá:
    # (resultado, error), uno de los dos en None.
    _act_buscada = pyqtSignal(object, object)
    _act_copiada = pyqtSignal(object, object)
    _act_avance = pyqtSignal(object, object)    # (bytes copiados, total)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"La bestia {actualizador.VERSION}")
        self.resize(800, 700)
        cfg = load_config()
        self.output_dir = cfg.get("output_dir") or DEFAULT_OUTPUT_DIR
        self.file_prefix = cfg.get("file_prefix") or DEFAULT_PREFIX
        self.config_cargada = bool(cfg.get("output_dir"))

        # Actualizaciones. "update_dir" no se ofrece en la ventana: es para la
        # PC que tenga la carpeta compartida en otra letra de unidad.
        self.update_dir = cfg.get("update_dir") or actualizador.CARPETA_ACTUALIZACIONES
        self.act = None               # última búsqueda: (estado, versión, ruta o detalle)
        self._act_ocupado = None      # "buscando", "copiando", "instalando" o None
        self._act_copiado = None      # (bytes copiados, total) mientras se copia
        self._act_error = None        # por qué falló el último intento de actualizar
        self._act_impedimento = None  # por qué este ejecutable no se puede actualizar solo
        self.dlg_acerca = None
        self._act_buscada.connect(self.on_update_checked)
        self._act_copiada.connect(self.on_update_copied)
        self._act_avance.connect(self.on_update_progress)
        self._accion_estado = None    # qué hace un clic en el aviso del pie

        # Si el destino no está disponible (unidad de red caída, por ejemplo)
        # se usa una carpeta local, pero NO se persiste: si se guardara, una
        # desconexión temporal borraría para siempre el destino configurado.
        self.destino_disponible = True
        if not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir)
            except Exception:
                self.destino_disponible = False
                self.output_dir = os.path.join(os.getcwd(), "Scans")
                try:
                    os.makedirs(self.output_dir, exist_ok=True)
                except Exception:
                    pass

        self.is_first_scan = True
        self._preview_pixmap = None

        self.scan_dpi = cfg.get("scan_dpi")
        if self.scan_dpi not in DPI_OPCIONES:
            self.scan_dpi = SCAN_DPI
        self._dpi_ultimo_escaneo = None   # resolución que ya se le pasó al robot
        self._dpi_en_curso = None         # resolución del escaneo que se está mostrando
        self._inicio_escaneo = None       # para informar cuánto tardó
        # Tamaño de archivo de referencia, llevado a 300 dpi, para estimar el
        # de las otras resoluciones. Arranca con el de una ficha típica y se
        # corrige con cada escaneo real.
        self._mb_a_300 = 4.4
        # Imágenes escaneadas desde el último canje. Se recuerda entre sesiones.
        self._escaneos = cfg.get("contador_escaneos", 0)
        if not isinstance(self._escaneos, int):
            self._escaneos = 0
        # Fichas escaneadas por día ("AAAA-MM-DD": n), para la semana y el
        # récord del día. Cuentan las imágenes de verdad.
        por_dia = cfg.get("escaneos_por_dia")
        self._por_dia = ({d: n for d, n in por_dia.items()
                          if isinstance(d, str) and isinstance(n, int)}
                         if isinstance(por_dia, dict) else {})
        self._record_festejado = cfg.get("record_festejado")    # fecha de la última medalla
        # Cuántos cofres salieron hoy, y si quedó uno sin abrir al cerrar.
        cofres = cfg.get("cofres")
        self._cofres = cofres if isinstance(cofres, dict) else {}
        self._cofre_pendiente = cfg.get("cofre_pendiente") is True
        # Temas: el elegido (por nombre) y los que armó cada uno.
        propios = cfg.get("temas_propios")
        self._temas_propios = [t for t in propios if temas.es_tema(t)] if isinstance(propios, list) else []
        tema = self._buscar_tema(cfg.get("tema")) or temas.POR_DEFECTO
        self._tema = tema["nombre"]
        temas.usar(tema["colores"])
        self._estado_pie = None

        self.setup_ui()
        self.aplicar_tema(tema["colores"])
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Top Bar (Scanner Select & herramientas)
        top_layout = QHBoxLayout()
        self.cb_scanner = FlatComboBox()
        self.cb_scanner.setFixedWidth(200)
        self.populate_scanners()

        # Los íconos de esta ventana los pone _poner_iconos, con los colores del tema.
        self.btn_debug = QPushButton()
        self.btn_debug.setIconSize(QSize(18, 18))
        self.btn_debug.setCheckable(True)
        self.btn_debug.setObjectName("debugButton")
        self.btn_debug.setToolTip(
            "Modo debug: guarda imágenes de diagnóstico y muestra «Procesar archivo»"
        )

        # Reprocesar un archivo ya escaneado. Sirve sobre todo para analizar un
        # _raw.bmp que quedó guardado porque la detección falló: genera una
        # máscara por estrategia y muestra en cuál se rompió. Es una
        # herramienta de diagnóstico, así que solo aparece con el modo debug.
        self.btn_local = QPushButton(" Procesar archivo")
        self.btn_local.setIconSize(QSize(16, 16))
        self.btn_local.setObjectName("secondaryButton")
        self.btn_local.setToolTip(
            "Procesa una imagen existente sin escanear y genera las máscaras de "
            "diagnóstico de cada estrategia de detección."
        )
        self.btn_local.clicked.connect(self.process_local_image)
        self.btn_local.setVisible(False)
        self.btn_debug.toggled.connect(self.btn_local.setVisible)

        # Versión del programa y actualizaciones. El botón de actualizar solo
        # aparece cuando hay una versión nueva publicada.
        self.btn_info = QPushButton()
        self.btn_info.setIconSize(QSize(18, 18))
        self.btn_info.setObjectName("infoButton")
        # La versión va a la vista, en el mismo botón: después de actualizar
        # se ve de un vistazo que cambió.
        self.btn_info.setText(f" {actualizador.VERSION}")
        self.btn_info.setToolTip("Versión del programa y actualizaciones")
        self.btn_info.clicked.connect(self.open_about)
        self.btn_update = QPushButton()
        self.btn_update.setIconSize(QSize(16, 16))
        self.btn_update.setObjectName("updateButton")
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.setToolTip("Hay una versión nueva del programa")
        self.btn_update.clicked.connect(self.open_about)
        self.btn_update.setVisible(False)

        # Los temas: una paleta de pintor que despliega los temas de colores.
        self.btn_tema = QPushButton()
        self.btn_tema.setIconSize(QSize(18, 18))
        self.btn_tema.setObjectName("temaButton")
        self.btn_tema.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tema.setToolTip("Colores de la ventana")
        self.btn_tema.clicked.connect(self.abrir_paleta)

        lbl_escaner = QLabel("Escáner")
        lbl_escaner.setObjectName("mutedLabel")
        top_layout.addWidget(lbl_escaner)
        top_layout.addWidget(self.cb_scanner)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_update)
        top_layout.addWidget(self.btn_local)
        top_layout.addWidget(self.btn_debug)
        top_layout.addWidget(self.btn_tema)
        top_layout.addWidget(self.btn_info)
        main_layout.addLayout(top_layout)

        # Destino: la carpeta a la vista y, al lado, el acceso para cambiarla.
        # Un clic en la carpeta la abre en el Explorador; el botón, la
        # configuración.
        destino_layout = QHBoxLayout()
        destino_layout.setSpacing(8)
        self.lbl_carpeta = lbl_carpeta = QLabel()
        self.lbl_destino = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.lbl_destino.setObjectName("destinoPath")
        self.lbl_destino.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_destino.setToolTip("Carpeta donde se guardan los escaneos. Clic para abrirla.")
        self.lbl_destino.clicked.connect(self.abrir_destino)
        btn_destino = QPushButton("Cambiar destino")
        btn_destino.setObjectName("linkButton")
        btn_destino.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_destino.clicked.connect(self.open_settings)
        destino_layout.addWidget(lbl_carpeta)
        destino_layout.addWidget(self.lbl_destino)
        destino_layout.addWidget(btn_destino)
        destino_layout.addStretch()
        main_layout.addLayout(destino_layout)
        self.update_destino_label()

        # Center Preview
        self.lbl_preview = QLabel("Poné el documento en la cama y presioná Enter")
        self.lbl_preview.setObjectName("previewCanvas")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Sombra de la imagen. El visor no tiene fondo propio, así que la
        # sombra toma la forma de lo único que pinta: la imagen. Se apaga
        # cuando hay un mensaje, para no sombrear el texto.
        self.preview_shadow = QGraphicsDropShadowEffect(self.lbl_preview)
        self.preview_shadow.setBlurRadius(48)
        self.preview_shadow.setOffset(0, 12)
        self.preview_shadow.setColor(QColor(0, 0, 0, C["sombra_alfa"]))
        self.preview_shadow.setEnabled(False)
        self.lbl_preview.setGraphicsEffect(self.preview_shadow)
        # Ignored en ambos ejes: sin esto el sizeHint del label crece con el
        # pixmap que se le pone, y el tamaño de la vista previa termina
        # dependiendo de la imagen anterior y del historial de resizes.
        self.lbl_preview.setSizePolicy(QSizePolicy.Policy.Ignored,
                                       QSizePolicy.Policy.Ignored)
        self.lbl_preview.setMinimumSize(QSize(1, 1))
        # Se escucha el resize del label, no el de la ventana: el label se
        # redimensiona después, cuando el layout ya repartió el espacio.
        self.lbl_preview.installEventFilter(self)
        # Barra de espera, centrada bajo el mensaje mientras dura el escaneo.
        self.busy_bar = BusyBar(self.lbl_preview)
        main_layout.addWidget(self.lbl_preview, stretch=1)

        # Pie de la imagen: nombre del archivo, cuánto tardó y cuánto pesa,
        # centrado bajo la imagen. La fila conserva su alto aunque esté
        # vacía, para que el botón de escaneo no salte de lugar cuando
        # aparece la imagen.
        pie_imagen = QWidget()
        pie_imagen.setFixedHeight(20)
        pie_imagen_layout = QHBoxLayout(pie_imagen)
        pie_imagen_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_info = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.lbl_info.setObjectName("captionInfo")
        pie_imagen_layout.addStretch()
        pie_imagen_layout.addWidget(self.lbl_info)
        pie_imagen_layout.addStretch()
        main_layout.addWidget(pie_imagen)
        self.lbl_info.setVisible(False)

        # Scan Button. El texto y la tecla van como etiquetas adentro del
        # botón, para poder dibujar "Enter" como una tecla.
        self.btn_scan = QPushButton()
        self.btn_scan.setObjectName("scanButton")
        self.btn_scan.setFixedHeight(56)
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_scan.setToolTip("Inicia el escaneo seleccionando automáticamente la Configuración Personalizada")
        self.lbl_scan = QLabel("Iniciar escaneo")
        self.lbl_scan.setObjectName("scanText")
        self.lbl_scan_key = QLabel("Enter")
        self.lbl_scan_key.setObjectName("scanKey")
        scan_inner = QHBoxLayout(self.btn_scan)
        scan_inner.setSpacing(10)
        scan_inner.addStretch()
        for etiqueta in (self.lbl_scan, self.lbl_scan_key):
            etiqueta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            scan_inner.addWidget(etiqueta, alignment=Qt.AlignmentFlag.AlignVCenter)
        scan_inner.addStretch()

        self.btn_manual = QPushButton()
        self.btn_manual.setIconSize(QSize(20, 20))
        self.btn_manual.setFixedSize(56, 56)
        self.btn_manual.setObjectName("secondaryButton")
        self.btn_manual.setToolTip("Modo Manual: Abre la ventana sin robot para que lo inspecciones")
        self.btn_manual.clicked.connect(self.start_scan_manual)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_scan, stretch=1)
        btn_layout.addWidget(self.btn_manual)

        main_layout.addLayout(btn_layout)

        # Shortcut for Enter key
        self.shortcut_enter = QShortcut(QKeySequence("Return"), self)
        self.shortcut_enter.activated.connect(self.start_scan)
        self.shortcut_enter2 = QShortcut(QKeySequence("Enter"), self)
        self.shortcut_enter2.activated.connect(self.start_scan)

        # Pie de la ventana. A la izquierda, la calidad (resolución del
        # escaneo). A la derecha, el botón que despliega el registro, que
        # arranca escondido. Entre los dos solo aparece algo cuando hay un
        # aviso o un error, y en pocas palabras: lo de rutina no se muestra.
        pie_layout = QHBoxLayout()
        pie_layout.setSpacing(10)
        lbl_calidad = QLabel("Calidad")
        lbl_calidad.setObjectName("mutedLabel")
        self.slider_dpi = QualitySlider(DPI_OPCIONES, self.scan_dpi)
        self.slider_dpi.setToolTip(
            "Resolución del escaneo. Más resolución da más detalle, pero el "
            "archivo pesa más y el escaneo tarda más."
        )
        self.slider_dpi.valueChanged.connect(self.on_dpi_changed)
        self.lbl_dpi = QLabel()
        self.lbl_dpi.setObjectName("valueLabel")
        self.lbl_peso = QLabel()
        self.lbl_peso.setObjectName("mutedLabel")
        self.lbl_peso.setToolTip("Tamaño estimado de cada archivo, calculado a partir del último escaneo")
        self.update_quality_labels()
        # Ancho reservado para el texto más largo: si no, la barra se corre
        # cada vez que cambia la cantidad de cifras.
        self.lbl_dpi.setMinimumWidth(52)
        self.lbl_peso.setMinimumWidth(70)

        self.btn_log = QPushButton(" Registro")
        self.btn_log.setObjectName("linkButton")
        self.btn_log.setCheckable(True)
        self.btn_log.setIconSize(QSize(14, 14))
        self.btn_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_log.setToolTip("Muestra u oculta el registro de mensajes")
        self.btn_log.toggled.connect(self.toggle_log)
        self.contador = ContadorEscaneos(self._escaneos)
        self.contador.canjeado.connect(self.canjear_contador)
        self.contador.senalado.connect(self.mostrar_semana)
        self.btn_cofre = BotonCofre()
        self.btn_cofre.abierto.connect(self.abrir_cofre)
        self.btn_cofre.setVisible(self._cofre_pendiente)
        self.lbl_status_icon = QLabel()
        self.lbl_status = ElidedLabel()
        self.lbl_status.setObjectName("statusLine")
        self.lbl_status.clicked.connect(self._clic_en_aviso)

        pie_layout.addWidget(lbl_calidad)
        pie_layout.addWidget(self.slider_dpi)
        pie_layout.addWidget(self.lbl_dpi)
        pie_layout.addWidget(self.lbl_peso)
        pie_layout.addStretch()
        pie_layout.addWidget(self.lbl_status_icon)
        pie_layout.addWidget(self.lbl_status)
        pie_layout.addSpacing(6)
        pie_layout.addWidget(self.btn_log)
        pie_layout.addWidget(self.btn_cofre)
        pie_layout.addWidget(self.contador)
        main_layout.addLayout(pie_layout)
        self.clear_warning()

        # Console
        self.console = QTextEdit()
        self.console.setObjectName("consoleOutput")
        self.console.setReadOnly(True)
        self.console.setFixedHeight(100)
        self.console.document().setMaximumBlockCount(100) # Limita el log a 100 mensajes
        main_layout.addWidget(self.console)
        self.toggle_log(False)

        # La semana, flotando arriba del contador mientras el mouse está encima.
        self.panel_semana = PanelSemana(central_widget)

        if not self.destino_disponible:
            self.log_to_console(
                f"AVISO: el destino configurado no está disponible. Guardando "
                f"temporalmente en: {self.output_dir} (no se cambió la configuración)."
            )
        else:
            origen = "configuración guardada" if self.config_cargada else "valor por defecto"
            self.log_to_console(f"Sistema listo ({origen}). Guardando en: {self.output_dir}")

    def populate_scanners(self):
        self.cb_scanner.addItem("Auto-Detectar")
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            dev_manager = win32com.client.Dispatch("WIA.DeviceManager")
            for i in range(1, dev_manager.DeviceInfos.Count + 1):
                device = dev_manager.DeviceInfos(i)
                if device.Type == 1: # 1 = Scanner
                    name = "Escáner WIA"
                    for prop in device.Properties:
                        if prop.Name == "Name":
                            name = prop.Value
                            break
                    self.cb_scanner.addItem(name)
            pythoncom.CoUninitialize()
        except Exception:
            pass

    def abrir_destino(self):
        """Abre la carpeta de destino en el Explorador de Windows."""
        if not os.path.isdir(self.output_dir):
            self.log_to_console(f"AVISO: la carpeta {self.output_dir} no está disponible.")
            self.open_settings()
            return
        try:
            os.startfile(os.path.normpath(self.output_dir))
        except OSError as e:
            self.log_to_console(f"AVISO: no se pudo abrir la carpeta ({e}).")

    def open_settings(self):
        dlg = SettingsDialog(self, self.output_dir, self.file_prefix)
        if dlg.exec():
            self.output_dir = dlg.txt_dir.text()
            self.file_prefix = dlg.txt_prefix.text()
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir)
            self.destino_disponible = True
            self.update_destino_label()
            self.log_to_console(f"Destino actualizado: {self.output_dir}")

            ok, detalle = save_config(output_dir=self.output_dir, file_prefix=self.file_prefix)
            if ok:
                self.log_to_console("Configuración guardada: se va a recordar al reiniciar.")
            else:
                self.log_to_console(f"AVISO: no se pudo guardar la configuración ({detalle}).")

    # --- Versión y actualizaciones (el mecanismo está en actualizador.py) ---

    def _en_segundo_plano(self, fn, senal):
        """
        Corre fn fuera del hilo de la ventana y entrega (resultado, error) por
        la señal. Es un hilo demonio y no un QThread: si la unidad de red no
        contesta puede quedar colgado un rato largo, y eso no tiene que
        impedir que el programa cierre.
        """
        def trabajo():
            try:
                salida = (fn(), None)
            except Exception as e:
                salida = (None, e)
            try:
                senal.emit(*salida)
            except RuntimeError:
                pass    # la ventana ya no existe

        threading.Thread(target=trabajo, daemon=True).start()

    def _refrescar_acerca(self):
        if self.dlg_acerca is not None:
            self.dlg_acerca.refrescar()

    def open_about(self):
        self.dlg_acerca = AcercaDialog(self)
        self.check_updates()
        self.dlg_acerca.exec()
        self.dlg_acerca = None

    def estado_actualizacion(self):
        """(texto, hay algo en curso, se puede actualizar ya) para el diálogo de versión."""
        if self._act_ocupado == "copiando":
            texto = (f"Paso 1 de 3: copiando la versión {self.act[1]} desde la "
                     f"carpeta compartida…")
            if self._act_copiado:
                hecho, total = self._act_copiado
                mb = 1024 * 1024
                texto += (f" {hecho / mb:.0f} de {total / mb:.0f} MB "
                          f"({_porcentaje(hecho, total)}%).")
            return texto, True, False
        if self._act_ocupado == "instalando":
            return ("Paso 2 de 3: abriendo el instalador. El programa se cierra, "
                    "se reemplaza y vuelve a abrir solo.", True, False)
        if self._act_ocupado == "buscando":
            return "Buscando actualizaciones en la carpeta compartida…", True, False
        if self.act is None:
            return "", False, False
        estado, version, detalle = self.act
        if estado == "nueva":
            if self._act_error:
                return f"No se pudo actualizar a la {version}: {self._act_error}", False, True
            if self._act_impedimento:
                return f"Hay una versión nueva: {version}. {self._act_impedimento}", False, False
            return f"Hay una versión nueva: {version}.", False, True
        return {
            "al_dia": "Tenés la última versión.",
            "sin_publicar": f"No hay ninguna versión publicada en {self.update_dir}.",
            "sin_carpeta": f"No se pudo abrir la carpeta de actualizaciones ({self.update_dir}).",
            "error": f"No se pudo buscar: {detalle}",
        }[estado], False, False

    def check_updates(self):
        """Mira si hay una versión nueva publicada, sin trabar la ventana."""
        if self._act_ocupado:
            return
        self._act_ocupado = "buscando"
        self._act_error = None
        self._refrescar_acerca()
        carpeta = self.update_dir

        def buscar():
            actualizador.limpiar_restos()
            return actualizador.buscar(carpeta), actualizador.impedimento()

        self._en_segundo_plano(buscar, self._act_buscada)

    @pyqtSlot(object, object)
    def on_update_checked(self, resultado, error):
        self._act_ocupado = None
        anterior = self.act
        if error is None:
            self.act, self._act_impedimento = resultado
        else:
            self.act = ("error", None, str(error))
        nueva = self.act[0] == "nueva"
        if nueva:
            self.btn_update.setText(f" Actualizar a {self.act[1]}")
            if self.act != anterior:
                self.log_to_console(
                    f"Hay una versión nueva del programa: {self.act[1]} "
                    f"(esta es la {actualizador.VERSION})."
                )
        self.btn_update.setVisible(nueva)
        self._refrescar_acerca()

    def start_update(self):
        if self._act_ocupado or not self.act or self.act[0] != "nueva":
            return
        if not self.btn_scan.isEnabled():
            self._act_error = "hay un escaneo en curso. Esperá a que termine."
            self._refrescar_acerca()
            return
        self._act_ocupado = "copiando"
        self._act_copiado = None
        self._act_error = None
        # Que no arranque un escaneo: el programa está por cerrarse.
        self.btn_scan.setEnabled(False)
        self.btn_manual.setEnabled(False)
        self.btn_update.setText(" Actualizando…")
        self._refrescar_acerca()
        origen = self.act[2]

        def avance(hecho, total):
            try:
                self._act_avance.emit(hecho, total)
            except RuntimeError:
                pass    # la ventana ya no existe

        self._en_segundo_plano(lambda: actualizador.preparar(origen, avance),
                               self._act_copiada)

    @pyqtSlot(object, object)
    def on_update_progress(self, hecho, total):
        anterior = self._act_copiado
        self._act_copiado = (hecho, total)
        # Se avisa por cada mega copiado; alcanza con redibujar cuando cambia
        # el porcentaje.
        if anterior is None or _porcentaje(*anterior) != _porcentaje(hecho, total):
            self.btn_update.setText(f" Actualizando… {_porcentaje(hecho, total)}%")
            self._refrescar_acerca()

    @pyqtSlot(object, object)
    def on_update_copied(self, nuevo, error):
        if error is None:
            try:
                actualizador.lanzar_instalacion(nuevo)
            except OSError as e:
                error = e
        if error is not None:
            self._act_ocupado = None
            self._act_error = str(error)
            self.btn_scan.setEnabled(True)
            self.btn_manual.setEnabled(True)
            self.btn_update.setText(f" Actualizar a {self.act[1]}")
            self.log_to_console(f"Error al actualizar: {error}")
            self._refrescar_acerca()
            return
        # El ejecutable nuevo ya arrancó y espera a que este cierre para
        # reemplazarlo. Un instante con el paso 2 a la vista, para que se
        # entienda por qué se cierra la ventana.
        self._act_ocupado = "instalando"
        self._refrescar_acerca()
        QTimer.singleShot(1200, QApplication.quit)

    def get_next_filename(self):
        # Auto-increment rellenando huecos: un solo listdir en vez de un
        # os.path.exists por número (clave en unidades de red).
        import re
        # Se cuentan los .png y tambien los _raw.bmp: si el procesamiento
        # falla no se llega a crear el .png, y sin mirar los crudos el
        # siguiente escaneo reusaria el mismo numero y pisaria el anterior.
        pattern = re.compile(
            re.escape(self.file_prefix) + r"(\d+)(?:_raw)?\.(?:png|bmp)$", re.IGNORECASE
        )
        try:
            names = os.listdir(self.output_dir)
        except OSError:
            names = []
        used = {int(m.group(1)) for n in names if (m := pattern.match(n))}
        counter = 1
        while counter in used:
            counter += 1
        return os.path.join(self.output_dir, f"{self.file_prefix}{counter}.png")

    def update_destino_label(self):
        self.lbl_destino.setText(os.path.normpath(self.output_dir))

    def update_quality_labels(self):
        """Resolución elegida y cuánto va a pesar, aproximadamente, cada archivo."""
        self.lbl_dpi.setText(f"{self.scan_dpi} dpi")
        # El tamaño crece con la cantidad de píxeles, o sea con el cuadrado
        # de la resolución.
        self.lbl_peso.setText("≈ " + _fmt_mb(self._mb_a_300 * (self.scan_dpi / 300) ** 2))

    def on_dpi_changed(self, dpi):
        self.scan_dpi = dpi
        self.update_quality_labels()
        ok, detalle = save_config(scan_dpi=dpi)
        if not ok:
            self.log_to_console(f"AVISO: no se pudo guardar la calidad elegida ({detalle}).")

    def toggle_log(self, visible):
        self.console.setVisible(visible)
        self.btn_log.setIcon(icon("flecha_abajo" if visible else "flecha_derecha", C["link"], 14))
        if visible:
            self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def show_warning(self, message, tipo="aviso"):
        """
        Aviso ("aviso") o error ("error") en pocas palabras, al pie. El texto
        completo queda en el registro.
        """
        self._show_status("alerta", tipo, _aviso_corto(message), message)

    def show_notice(self, message, accion=None, ayuda=None):
        """
        Una buena noticia al pie, hasta el próximo escaneo. Con `accion`, un
        clic en el aviso la ejecuta y `ayuda` explica qué hace.
        """
        self._show_status("tilde", "ok", message, ayuda or message, accion)

    def _show_status(self, icono, tipo, corto, completo, accion=None):
        # `tipo` es el nombre del color en la paleta: si cambia el tema, el
        # aviso se vuelve a pintar con el color nuevo (ver aplicar_tema).
        self._estado_pie = (icono, tipo, corto, completo, accion)
        color = C[tipo]
        self.lbl_status_icon.setPixmap(icon_pixmap(icono, color, 14))
        self.lbl_status.setStyleSheet(f"color: {color};")
        self.lbl_status.setText(corto)
        self.lbl_status.setToolTip(completo)
        self.lbl_status_icon.setVisible(True)
        self.lbl_status.setVisible(True)
        self._accion_estado = accion
        self.lbl_status.setCursor(Qt.CursorShape.PointingHandCursor if accion
                                  else Qt.CursorShape.ArrowCursor)

    def clear_warning(self):
        self._estado_pie = None
        self.lbl_status_icon.setVisible(False)
        self.lbl_status.setVisible(False)
        self._accion_estado = None

    def _clic_en_aviso(self):
        if self._accion_estado is not None:
            self._accion_estado()

    @pyqtSlot(str)
    def log_to_console(self, message):
        # Avisos y errores en color. Son lo único que además se muestra al
        # pie de la ventana; el resto queda solo en el registro.
        if message.startswith("AVISO") or message.startswith("Captura directa no disponible"):
            tipo = "aviso"
        elif message.startswith("Error"):
            tipo = "error"
        else:
            tipo = None

        # El color va siempre explícito: si no, el renglón hereda el del
        # anterior y todo lo que sigue a un aviso sale en ámbar.
        timestamp = time.strftime("%H:%M:%S")
        texto = f"<span style='color:{C[tipo or 'texto2']};'>{html.escape(message)}</span>"
        self.console.append(f"<span style='color:{C['link']};'>[{timestamp}]</span> {texto}")
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

        if tipo:
            self.show_warning(message, tipo)

    def set_scanning(self, activo, mensaje=""):
        """Estado de la ventana mientras hay un escaneo en curso."""
        self.btn_scan.setEnabled(not activo)
        self.btn_manual.setEnabled(not activo)
        self.lbl_scan.setText("Escaneando…" if activo else "Iniciar escaneo")
        self.lbl_scan_key.setVisible(not activo)
        if activo:
            # Los avisos del escaneo anterior ya no corresponden.
            self.clear_warning()
            self.set_preview_text(mensaje)
            self.place_busy_bar()
            self.busy_bar.start()
        else:
            self.busy_bar.stop()

    def start_scan(self):
        if not self.btn_scan.isEnabled():
            return

        self.set_scanning(True, "Escaneando…")

        scanner = self.cb_scanner.currentText()
        out_path = self.get_next_filename()
        debug_active = self.btn_debug.isChecked()

        # Si la captura directa no está disponible, el robot del diálogo
        # nativo tipea la resolución solo en el primer escaneo. Cuando la
        # resolución cambió, tiene que volver a tipearla.
        primero = self.is_first_scan or self.scan_dpi != self._dpi_ultimo_escaneo
        self._dpi_ultimo_escaneo = self.scan_dpi
        self._dpi_en_curso = self.scan_dpi
        self._inicio_escaneo = time.perf_counter()

        self.thread = ScannerThread(scanner, out_path, debug_active, primero, dpi=self.scan_dpi)
        self.is_first_scan = False
        self.thread.log_signal.connect(self.log_to_console)
        self.thread.image_signal.connect(self.display_image)
        self.thread.image_signal.connect(self.contar_escaneo)
        self.thread.finished_signal.connect(self.scan_finished)
        self.thread.start()

    def start_scan_manual(self):
        if not self.btn_scan.isEnabled():
            return

        self.set_scanning(True, "Modo manual activo…")

        scanner = self.cb_scanner.currentText()
        out_path = self.get_next_filename()
        debug_active = self.btn_debug.isChecked()

        # En modo manual la resolución la elige el usuario en el diálogo, así
        # que ese escaneo no sirve para estimar tamaños.
        self._dpi_en_curso = None
        self._inicio_escaneo = time.perf_counter()

        self.thread = ScannerThread(scanner, out_path, debug_active, is_first_scan=False,
                                    manual_mode=True, dpi=self.scan_dpi)
        self.thread.log_signal.connect(self.log_to_console)
        self.thread.image_signal.connect(self.display_image)
        self.thread.image_signal.connect(self.contar_escaneo)
        self.thread.finished_signal.connect(self.scan_finished)
        self.thread.start()

    def contar_escaneo(self, *_):
        hoy = _hoy()
        self._por_dia[hoy] = self._por_dia.get(hoy, 0) + 1
        self.contador.sumar(1)
        self._guardar_contador()
        self._revisar_record(hoy)
        self._revisar_cofre(hoy)

    def _revisar_record(self, hoy):
        """
        La medalla cae la primera vez en el día que se pasa el mejor día de
        siempre. Hace falta otro día con escaneos para que haya un récord.
        """
        record, _ = _record_previo(self._por_dia, hoy)
        if record <= 0 or self._record_festejado == hoy or self._por_dia[hoy] <= record:
            return False
        self._record_festejado = hoy
        save_config(record_festejado=hoy)
        base = self.centralWidget()
        Festejo(base, base.rect().center(), "record", datos={
            "fichas": self._por_dia[hoy], "semana": _semana(self._por_dia), "record": record,
        })
        self.log_to_console(f"Récord del día: {self._por_dia[hoy]} fichas (el anterior era {record}).")
        return True

    def mostrar_semana(self, visible):
        if not visible:
            self.panel_semana.hide()
            return
        hoy = _hoy()
        record, fecha = _record_previo(self._por_dia, hoy)
        if self._por_dia.get(hoy, 0) > record:
            record, fecha = self._por_dia[hoy], hoy
        base = self.centralWidget()
        esquina = self.contador.mapTo(base, QPoint(self.contador.width(), -6))
        self.panel_semana.mostrar(_semana(self._por_dia), record, fecha,
                                  "Clic en el número para canjear" if self.contador.valor else "",
                                  esquina)

    def _revisar_cofre(self, hoy):
        """Después de un escaneo, de vez en cuando aparece un cofre al lado del contador."""
        if self.btn_cofre.isVisible():
            return
        if self._cofres.get("fecha") != hoy:
            self._cofres = {"fecha": hoy, "dados": 0}
        if self._cofres["dados"] >= COFRES_POR_DIA or random.random() >= COFRE_PROBABILIDAD:
            return
        self._cofres["dados"] += 1
        save_config(cofres=self._cofres, cofre_pendiente=True)
        self.btn_cofre.show()

    def abrir_cofre(self):
        self.btn_cofre.hide()
        save_config(cofre_pendiente=False)
        base = self.centralWidget()
        origen = self.contador.mapTo(base, self.contador.rect().center())
        nombre, premio = random.choice([("lluvia de billetes", 250), ("jackpot", 500)])

        def al_abrir():
            Festejo(base, origen, premio)

        Festejo(base, base.rect().center(), "cofre", datos={"premio": nombre, "al_abrir": al_abrir})

    def canjear_contador(self, escalon):
        base = self.centralWidget()
        origen = self.contador.mapTo(base, self.contador.rect().center())
        if escalon == 0:
            # El número se va cuando el fuego ya lo tapó. Se descuenta lo
            # quemado y no se pone en cero: si mientras tanto terminó un
            # escaneo, ese no se pierde.
            quemado = self.contador.valor
            self.contador.setEnabled(False)     # que no se prenda dos veces

            def al_quemar():
                self.contador.set_valor(self.contador.valor - quemado)
                self._guardar_contador()

            zona = QRect(self.contador.mapTo(base, QPoint(0, 0)), self.contador.size())
            Festejo(base, origen, 0, zona=zona, al_quemar=al_quemar)
            return
        Festejo(base, origen, escalon)
        self.contador.set_valor(0)
        self._guardar_contador()

    def _guardar_contador(self):
        ok, detalle = save_config(contador_escaneos=self.contador.valor,
                                  escaneos_por_dia=self._por_dia)
        if not ok:
            self.log_to_console(f"AVISO: no se pudo guardar el contador ({detalle}).")

    @pyqtSlot()
    def scan_finished(self):
        self.set_scanning(False)
        # Si el escaneo no dejó ninguna imagen (cancelado, error), el visor
        # no puede quedarse diciendo que sigue escaneando.
        if self._preview_pixmap is None:
            self.set_preview_text("Listo para el siguiente escaneo.")

    def run_wia_diagnostics(self):
        self.log_to_console("--- INICIANDO MODO ESPÍA WIA ---")
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            
            self.log_to_console("Abriendo diálogo para seleccionar escáner...")
            dialog = win32com.client.Dispatch("WIA.CommonDialog")
            device = dialog.ShowSelectDevice()
            
            if not device:
                self.log_to_console("No se seleccionó escáner.")
                return

            self.log_to_console(f"Escáner: {device.Properties('Name').Value}")
            
            initial_props = {}
            for p in device.Properties:
                try:
                    initial_props[p.PropertyID] = p.Value
                except:
                    pass
                    
            initial_items = {}
            for idx in range(1, device.Items.Count + 1):
                initial_items[idx] = {}
                for p in device.Items[idx].Properties:
                    try:
                        initial_items[idx][p.PropertyID] = p.Value
                    except:
                        pass

            self.log_to_console("SE ABRIRÁ LA VENTANA. ELIGE 'PLANO' Y DALE ACEPTAR/ESCANEAR.")
            # Obligamos a la UI a actualizarse para que el usuario lea el mensaje
            QApplication.processEvents()
            
            try:
                selected_items = dialog.ShowSelectItems(device)
            except Exception as e:
                self.log_to_console(f"Diálogo cancelado o falló: {e}")
                return

            self.log_to_console("--- CAMBIOS DETECTADOS DESPUÉS DEL DIÁLOGO ---")
            
            for p in device.Properties:
                try:
                    new_val = p.Value
                    old_val = initial_props.get(p.PropertyID)
                    if old_val != new_val:
                        self.log_to_console(f"Device Prop [{p.PropertyID}] {p.Name}: {old_val} ---> {new_val}")
                except:
                    pass

            for idx in range(1, device.Items.Count + 1):
                for p in device.Items[idx].Properties:
                    try:
                        new_val = p.Value
                        old_val = initial_items[idx].get(p.PropertyID)
                        if old_val != new_val:
                            self.log_to_console(f"Item {idx} Prop [{p.PropertyID}] {p.Name}: {old_val} ---> {new_val}")
                    except:
                        pass
            
            self.log_to_console("--- PROPIEDADES FINALES DEL ITEM SELECCIONADO ---")
            if selected_items:
                for idx in range(1, selected_items.Count + 1):
                    item = selected_items[idx]
                    self.log_to_console(f"Item Seleccionado {idx}:")
                    for p in item.Properties:
                        try:
                            self.log_to_console(f"  [{p.PropertyID}] {p.Name}: {p.Value}")
                        except:
                            pass
            else:
                self.log_to_console("No hay items seleccionados.")
                
            self.log_to_console("--- FIN DEL MODO ESPÍA ---")
            pythoncom.CoUninitialize()
        except Exception as e:
            self.log_to_console(f"Error en modo espía: {e}")

    def run_wia_diagnostics_silent(self):
        self.log_to_console("--- INICIANDO INFO WIA SILENCIOSO ---")
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            
            dev_manager = win32com.client.Dispatch("WIA.DeviceManager")
            scanner_name = self.cb_scanner.currentText()
            device = None
            
            for i in range(1, dev_manager.DeviceInfos.Count + 1):
                dev_info = dev_manager.DeviceInfos(i)
                if dev_info.Type == 1:
                    name = "Escáner WIA"
                    for prop in dev_info.Properties:
                        if prop.Name == "Name":
                            name = prop.Value
                            break
                    if scanner_name == "Auto-Detectar" or name == scanner_name:
                        device = dev_info.Connect()
                        self.log_to_console(f"Conectado a: {name}")
                        break
                        
            if not device:
                self.log_to_console("No se pudo conectar al escáner seleccionado.")
                pythoncom.CoUninitialize()
                return

            self.log_to_console("\n>> PROPIEDADES DEL DISPOSITIVO:")
            for p in device.Properties:
                try:
                    self.log_to_console(f"  [{p.PropertyID}] {p.Name}: {p.Value}")
                except:
                    pass

            for idx in range(1, device.Items.Count + 1):
                item = device.Items[idx]
                self.log_to_console(f"\n>> PROPIEDADES DEL ITEM {idx}:")
                for p in item.Properties:
                    try:
                        self.log_to_console(f"  [{p.PropertyID}] {p.Name}: {p.Value}")
                    except:
                        pass

            self.log_to_console("--- FIN INFO WIA SILENCIOSO ---")
            pythoncom.CoUninitialize()
        except Exception as e:
            self.log_to_console(f"Error en info silencioso: {e}")

    def process_local_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar imagen", "", "Images (*.png *.jpg *.bmp *.jpeg)")
        if file_path:
            out_path = self.get_next_filename()
            debug_active = self.btn_debug.isChecked()
            self.clear_warning()
            self.set_preview_text("Procesando imagen local...")
            self.log_to_console(f"Procesando archivo local: {file_path}")
            # No se sabe a qué resolución se escaneó ese archivo: no sirve
            # para estimar tamaños.
            self._dpi_en_curso = None
            self._inicio_escaneo = time.perf_counter()

            try:
                # process_and_crop espera algo con .emit() (normalmente una
                # pyqtSignal del hilo de escaneo). Acá ya estamos en el hilo de
                # UI, así que alcanza con un adaptador que escriba directo.
                class _LogDirecto:
                    def __init__(self, fn): self.emit = fn

                final_path, detectado, imagen = process_and_crop_image(
                    file_path, out_path, _LogDirecto(self.log_to_console), debug_active
                )
                self.display_image(final_path, detectado, to_qimage(imagen))
                if debug_active:
                    self.log_to_console(
                        f"Máscaras de diagnóstico escritas en {os.path.dirname(out_path)}"
                    )
                self.log_to_console(
                    "Procesamiento local terminado."
                    if detectado else
                    "Procesamiento local terminado SIN detectar documento."
                )
            except Exception as e:
                self.log_to_console(f"Error procesando imagen local: {e}")
                self.set_preview_text("Listo para el siguiente escaneo.")

    def update_caption(self, filepath, detectado):
        """Pie de la imagen: nombre del archivo, cuánto tardó y cuánto pesa."""
        partes = [os.path.basename(filepath)]
        if self._inicio_escaneo is not None:
            segundos = time.perf_counter() - self._inicio_escaneo
            partes.append(f"{segundos:.1f} s".replace(".", ","))
            self._inicio_escaneo = None
        try:
            mb = os.path.getsize(filepath) / 1e6
        except OSError:
            mb = None
        if mb is not None:
            partes.append(_fmt_mb(mb))
        self.lbl_info.setText("  ·  ".join(partes))
        self.lbl_info.setToolTip(filepath)
        self.lbl_info.setVisible(True)

        # Un recorte real a una resolución conocida corrige la estimación de
        # tamaño de la barra de calidad.
        if detectado and mb and self._dpi_en_curso:
            self._mb_a_300 = mb * (300 / self._dpi_en_curso) ** 2
            self.update_quality_labels()

    def set_preview_text(self, mensaje):
        """Mensaje en el visor, descartando la imagen que hubiera."""
        self._preview_pixmap = None
        self.preview_shadow.setEnabled(False)
        self.lbl_info.setVisible(False)
        self.lbl_preview.setText(mensaje)

    def place_busy_bar(self):
        """La barra de espera, centrada un poco por debajo del mensaje."""
        area = self.lbl_preview.contentsRect()
        self.busy_bar.move(area.center().x() - self.busy_bar.width() // 2,
                           area.center().y() + 22)

    def eventFilter(self, obj, event):
        if obj is self.lbl_preview and event.type() == QEvent.Type.Resize:
            self.render_preview()
            self.place_busy_bar()
        return super().eventFilter(obj, event)

    def render_preview(self):
        """
        Reescala desde el original en cada resize. Escalar una sola vez al
        cargar dejaba la vista previa al tamaño que la ventana tenía en ese
        momento, y no se actualizaba nunca más.
        """
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        # Margen libre alrededor de la imagen: es donde cae la sombra.
        margen = 32
        area = self.lbl_preview.contentsRect().size() - QSize(2 * margen, 2 * margen)
        if area.width() < 2 or area.height() < 2:
            return
        # Se escala en píxeles físicos: en una pantalla con escala de Windows
        # al 125 o 150 %, hacerlo en píxeles lógicos dejaba la imagen borrosa.
        dpr = self.lbl_preview.devicePixelRatioF()
        scaled = self._preview_pixmap.scaled(
            area * dpr,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Esquinas apenas redondeadas. Se pinta la imagen como relleno de un
        # rectángulo redondeado (y no con un recorte) para que el borde salga
        # suavizado.
        rounded = QPixmap(scaled.size())
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(scaled))
        radio = 6 * dpr
        painter.drawRoundedRect(QRectF(0, 0, scaled.width(), scaled.height()), radio, radio)
        painter.end()
        rounded.setDevicePixelRatio(dpr)

        self.lbl_preview.setPixmap(rounded)
        self.preview_shadow.setEnabled(True)

    @pyqtSlot(str, bool, object)
    def display_image(self, filepath, detectado=True, imagen=None):
        # Lo normal es que la imagen llegue ya en memoria desde quien la
        # procesó. Leerla del archivo queda para cuando no vino (por ejemplo,
        # un crudo que no se pudo procesar y se muestra tal cual).
        if isinstance(imagen, QImage) and not imagen.isNull():
            pixmap = QPixmap.fromImage(imagen)
        else:
            pixmap = QPixmap(filepath)
        if pixmap.isNull():
            self.set_preview_text("Error al cargar la imagen.")
            return
        # Se guarda el original y se escala una copia: reescalar sobre lo ya
        # escalado degrada la imagen con cada resize.
        self._preview_pixmap = pixmap
        self.render_preview()
        self.update_caption(filepath, detectado)

    # --- Temas de colores (los colores y las cuentas están en temas.py) ---

    def _buscar_tema(self, nombre):
        for tema in temas.TEMAS + self._temas_propios:
            if tema["nombre"] == nombre:
                return tema
        return None

    def tema_actual(self):
        return self._buscar_tema(self._tema) or temas.POR_DEFECTO

    def aplicar_tema(self, colores):
        """Pinta la ventana con estos colores. No los guarda: eso lo hace elegir_tema."""
        temas.usar(colores)
        self.setStyleSheet(temas.hoja())
        self._poner_iconos()
        self.contador._pintar()
        self.preview_shadow.setColor(QColor(0, 0, 0, C["sombra_alfa"]))
        if self._estado_pie is not None:
            self._show_status(*self._estado_pie)
        # Los controles que se dibujan a mano leen la paleta al pintarse.
        for w in self.findChildren(QWidget):
            w.update()

    def _poner_iconos(self):
        self.btn_debug.setIcon(icon("bicho", C["texto2"], 18))
        self.btn_local.setIcon(icon("archivo", C["texto2"]))
        self.btn_info.setIcon(icon("info", C["texto2"], 18))
        self.btn_update.setIcon(icon("descargar", C["sobre_acento"]))
        self.btn_tema.setIcon(QIcon(pixmap_paleta(C, 18)))
        self.lbl_carpeta.setPixmap(icon_pixmap("carpeta", C["tenue"]))
        self.btn_manual.setIcon(icon("ajustes", C["texto2"], 20))
        self.toggle_log(self.btn_log.isChecked())

    def abrir_paleta(self):
        lista = [(t, False) for t in temas.TEMAS] + [(t, True) for t in self._temas_propios]
        paleta = PaletaTemas(self, lista, self._tema)
        # Abajo del botón, alineada por la derecha y sin salirse de la pantalla.
        esquina = self.btn_tema.mapToGlobal(QPoint(self.btn_tema.width(), self.btn_tema.height() + 2))
        x = esquina.x() - paleta.width() + PaletaTemas.SOMBRA
        y = esquina.y() - PaletaTemas.SOMBRA + 4
        pantalla = self.screen().availableGeometry() if self.screen() else None
        if pantalla is not None:
            x = max(pantalla.left(), min(x, pantalla.right() - paleta.width()))
            y = min(y, pantalla.bottom() - paleta.height())
        paleta.move(x, y)
        # Hay que guardarla: es una ventana suelta, sin padre, y si nadie la
        # guarda Python la borra apenas termina esta función.
        self._paleta = paleta
        paleta.show()
        paleta.setFocus()

    def elegir_tema(self, tema):
        self._tema = tema["nombre"]
        self.aplicar_tema(tema["colores"])
        ok, detalle = save_config(tema=self._tema)
        if not ok:
            self.log_to_console(f"AVISO: no se pudo guardar el tema elegido ({detalle}).")

    def _nombre_libre(self, nombre, salvo=None):
        """`nombre`, o con un número al final si ya hay un tema que se llama así."""
        usados = {t["nombre"].casefold() for t in temas.TEMAS + self._temas_propios
                  if t["nombre"] != salvo}
        candidato, n = nombre, 2
        while candidato.casefold() in usados:
            candidato, n = f"{nombre} {n}", n + 1
        return candidato

    def nuevo_tema(self):
        # Arranca con los colores del tema que está puesto: casi siempre se
        # quiere cambiar uno o dos, no armar todo de cero.
        dlg = EditorTema(self, dict(self.tema_actual()["colores"]), "")
        dlg.txt_nombre.setPlaceholderText(self._nombre_libre("Mi tema"))
        if dlg.exec():
            tema = {"nombre": self._nombre_libre(dlg.nombre()), "colores": dlg.colores()}
            self._temas_propios.append(tema)
            self._guardar_temas_propios()
            self.elegir_tema(tema)

    def editar_tema(self, tema):
        dlg = EditorTema(self, dict(tema["colores"]), tema["nombre"], editando=True)
        if dlg.exec():
            era = tema["nombre"]
            tema["nombre"] = self._nombre_libre(dlg.nombre(), salvo=era)
            tema["colores"] = dlg.colores()
            self._guardar_temas_propios()
            if self._tema == era:
                self.elegir_tema(tema)

    def borrar_tema(self, tema):
        respuesta = QMessageBox.question(
            self, "Borrar tema", f"¿Borrar el tema «{tema['nombre']}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        self._temas_propios = [t for t in self._temas_propios if t is not tema]
        self._guardar_temas_propios()
        if self._tema == tema["nombre"]:
            self.elegir_tema(temas.POR_DEFECTO)

    def _guardar_temas_propios(self):
        ok, detalle = save_config(temas_propios=self._temas_propios)
        if not ok:
            self.log_to_console(f"AVISO: no se pudieron guardar los temas ({detalle}).")


def run_instalar(app, destino):
    """
    Lo que hace el ejecutable nuevo durante una actualización (ver
    actualizador.py): un cartel mientras reemplaza al instalado, y después lo
    abre. Si no pudo reemplazarlo, avisa y abre el que estaba.
    """
    cartel = QFrame()
    cartel.setObjectName("cartel")
    cartel.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint)
    cartel.setStyleSheet(
        "#cartel { background-color: #1E1E1E; border: 1px solid #454545; }"
        "QLabel { color: #D4D4D4; background: transparent; }"
        "#cartelTitulo { color: #FFFFFF; font-size: 15px; font-weight: bold; }"
        "#cartelEtapa { color: #9A9A9A; font-size: 12px; }"
    )
    titulo = QLabel(f"Actualizando La bestia a la versión {actualizador.VERSION}")
    titulo.setObjectName("cartelTitulo")
    etapa = QLabel("Paso 3 de 3: reemplazando el programa…")
    etapa.setObjectName("cartelEtapa")
    spinner = Spinner(22)
    textos = QVBoxLayout()
    textos.setSpacing(4)
    textos.addWidget(titulo)
    textos.addWidget(etapa)
    fila = QHBoxLayout(cartel)
    fila.setContentsMargins(28, 22, 36, 22)
    fila.setSpacing(16)
    fila.addWidget(spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
    fila.addLayout(textos)
    cartel.setMinimumWidth(460)
    cartel.show()
    spinner.start()

    ETAPAS = {
        "copiando": "Paso 3 de 3: reemplazando el programa…",
        "esperando": "Paso 3 de 3: esperando a que termine de cerrarse la versión anterior…",
    }
    resultado = []
    avisos = []     # etapas que informa el hilo; las muestra el reloj

    def trabajo():
        try:
            resultado.append(actualizador.instalar(destino, aviso=avisos.append))
        except Exception as e:
            resultado.append(e)

    def revisar():
        if avisos:
            etapa.setText(ETAPAS.get(avisos[-1], etapa.text()))
        if not resultado:
            return
        reloj.stop()
        error = resultado[0]
        if error is not None:
            cartel.hide()
            QMessageBox.warning(
                None, "La bestia",
                "No se pudo actualizar: el programa sigue abierto, quizás en otra "
                "sesión de esta PC.\n\nSe abre la versión que ya estaba instalada."
            )
        if error is None:
            etapa.setText("Listo. Abriendo el programa…")
            # Con este aviso el programa dice, al abrir, que quedó actualizado.
            actualizador.abrir(destino, "--actualizado")
        else:
            actualizador.abrir(destino)
        # El programa tarda unos segundos en aparecer: el cartel queda hasta
        # entonces, para que nadie crea que no pasó nada y lo abra de nuevo.
        QTimer.singleShot(0 if error is not None else 4000, app.quit)

    reloj = QTimer()
    reloj.setInterval(200)
    reloj.timeout.connect(revisar)
    reloj.start()
    threading.Thread(target=trabajo, daemon=True).start()
    app.exec()
    return 0 if resultado and resultado[0] is None else 1


if __name__ == '__main__':
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Inter", 10))
    # Los diálogos que trae Qt (el de elegir color, los botones Sí/No) en
    # castellano. Si la traducción no está, quedan en inglés y nada más.
    traduccion = QTranslator(app)
    if traduccion.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(traduccion)
    if "--instalar" in sys.argv:
        sys.exit(run_instalar(app, sys.argv[sys.argv.index("--instalar") + 1]))
    window = ScannerApp()
    window.show()
    if "--actualizado" in sys.argv:
        window.log_to_console(f"Programa actualizado a la versión {actualizador.VERSION}.")
        # Si hay un aviso al pie (destino no disponible), ese importa más.
        if not window.lbl_status.isVisible():
            window.show_notice(f"Actualizado a la versión {actualizador.VERSION} · ver novedades",
                               accion=window.open_about,
                               ayuda="Clic para ver qué cambió en esta versión")
    window.check_updates()
    app.aboutToQuit.connect(lambda: _limpiar_crudos_pendientes())
    sys.exit(app.exec())
