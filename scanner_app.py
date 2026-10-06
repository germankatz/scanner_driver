import sys
import os
import time
import glob
import json
import html


def run_selftest():
    """
    Verifica que las extensiones nativas carguen dentro del ejecutable
    empaquetado. Existe porque compilar sin error no garantiza que el .exe
    funcione: numpy y OpenCV cargan DLLs recien al importarse, y un fallo ahi
    solo aparece en tiempo de ejecucion.

    Escribe selftest.log junto al ejecutable y devuelve 0 si todo carga.
    Se usa en CI y sirve para diagnosticar una maquina concreta:
        AntigravityScanner.exe --selftest
    """
    lineas, ok = [], True
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


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QTextEdit, QFrame, QStyledItemDelegate,
    QDialog, QFileDialog, QGraphicsDropShadowEffect, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, pyqtSlot, QEvent, QSize, QRectF, QLineF,
    QByteArray, QVariantAnimation
)
from PyQt6.QtGui import (
    QFont, QColor, QPixmap, QImage, QKeySequence, QShortcut, QPainter, QBrush, QIcon,
    QPen
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
                        os.remove(raw_path)
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
    """
    %APPDATA%\AntigravityScanner\config.json en Windows, ~ como fallback.
    No se guarda junto al .exe a propósito: empaquetado con PyInstaller puede
    quedar en Program Files, donde el usuario no tiene permiso de escritura.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    carpeta = os.path.join(base, "AntigravityScanner")
    try:
        os.makedirs(carpeta, exist_ok=True)
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".antigravity_scanner.json")
    return os.path.join(carpeta, "config.json")


def load_config():
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
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
        self.setWindowTitle("Configurar Destino")
        self.setFixedSize(400, 200)
        self.setStyleSheet(parent.styleSheet())
        
        layout = QVBoxLayout(self)
        
        # Directorio
        layout.addWidget(QLabel("Carpeta de destino:"))
        dir_layout = QHBoxLayout()
        self.txt_dir = QLineEdit(current_dir)
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(40)
        btn_browse.clicked.connect(self.browse_dir)
        dir_layout.addWidget(self.txt_dir)
        dir_layout.addWidget(btn_browse)
        layout.addLayout(dir_layout)
        
        # Prefijo
        layout.addWidget(QLabel("Prefijo del nombre de archivo:"))
        self.txt_prefix = QLineEdit(current_prefix)
        layout.addWidget(self.txt_prefix)
        
        layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        
        # Botones
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("Guardar Configuración")
        btn_ok.setObjectName("primaryButton")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta")
        if d:
            self.txt_dir.setText(d)

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
        p.setPen(QPen(QColor("#007ACC" if self._foco_teclado else "#3A3A3A"), 1))
        p.setBrush(QColor("#2A2A2A"))
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
                color = "#9A9A9A" if permitido else "#6A6A6A"
            else:
                color = "#6A6A6A" if permitido else "#474747"
            p.setPen(QPen(QColor(color), 1))
            p.drawLine(QLineF(x, (h - alto) / 2, x, (h + alto) / 2))
            v += self._paso_marcas

        # Tirador: una pastilla clara con una sombra corta debajo.
        ancho_t, alto_t = 12, h - 6
        tirador = QRectF(x_tirador - ancho_t / 2, (h - alto_t) / 2, ancho_t, alto_t)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(tirador.translated(0, 1.5), 5, 5)
        p.setBrush(QColor("#FFFFFF" if self.underMouse() else "#EDEDED"))
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
        p.setBrush(QColor("#2D2D30"))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        p.setBrush(QColor("#D84315"))
        if self._anim.state() == QVariantAnimation.State.Running:
            largo = 0.35 * w
            x = -largo + self._fase * (w + largo)
            p.setClipRect(QRectF(0, 0, w, h))
            p.drawRoundedRect(QRectF(x, 0, largo, h), h / 2, h / 2)
        else:
            p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)


class FlatComboBox(QComboBox):
    """
    Desplegable plano. El que dibuja Windows por defecto trae un botón con
    relieve y una flecha negra que no pegan con el resto de la ventana; acá el
    marco lo pone la hoja de estilos y la flecha se dibuja a mano.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flecha = icon_pixmap("flecha_abajo", "#9A9A9A", 14)
        # Con este delegado la lista desplegada respeta la hoja de estilos
        # (alto y color de cada renglón).
        self.setItemDelegate(QStyledItemDelegate(self))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.drawPixmap(self.width() - 14 - 10, (self.height() - 14) // 2, self._flecha)


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


class ScannerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Antigravity Scanner - Simplificado")
        self.resize(800, 700)
        cfg = load_config()
        self.output_dir = cfg.get("output_dir") or DEFAULT_OUTPUT_DIR
        self.file_prefix = cfg.get("file_prefix") or DEFAULT_PREFIX
        self.config_cargada = bool(cfg.get("output_dir"))

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

        self.setup_ui()
        self.apply_dark_theme()
        
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

        self.btn_debug = QPushButton()
        self.btn_debug.setIcon(icon("bicho", "#CCCCCC", 18))
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
        self.btn_local.setIcon(icon("archivo", "#CCCCCC"))
        self.btn_local.setIconSize(QSize(16, 16))
        self.btn_local.setObjectName("secondaryButton")
        self.btn_local.setToolTip(
            "Procesa una imagen existente sin escanear y genera las máscaras de "
            "diagnóstico de cada estrategia de detección."
        )
        self.btn_local.clicked.connect(self.process_local_image)
        self.btn_local.setVisible(False)
        self.btn_debug.toggled.connect(self.btn_local.setVisible)

        lbl_escaner = QLabel("Escáner")
        lbl_escaner.setObjectName("mutedLabel")
        top_layout.addWidget(lbl_escaner)
        top_layout.addWidget(self.cb_scanner)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_local)
        top_layout.addWidget(self.btn_debug)
        main_layout.addLayout(top_layout)

        # Destino: la carpeta a la vista y, al lado, el acceso para cambiarla.
        # Un clic en cualquiera de los dos abre la configuración.
        destino_layout = QHBoxLayout()
        destino_layout.setSpacing(8)
        lbl_carpeta = QLabel()
        lbl_carpeta.setPixmap(icon_pixmap("carpeta", "#9A9A9A"))
        self.lbl_destino = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.lbl_destino.setObjectName("destinoPath")
        self.lbl_destino.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_destino.setToolTip("Carpeta donde se guardan los escaneos. Clic para cambiarla.")
        self.lbl_destino.clicked.connect(self.open_settings)
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
        self.preview_shadow.setColor(QColor(0, 0, 0, 230))
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
        self.btn_manual.setIcon(icon("ajustes", "#CCCCCC", 20))
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
        self.lbl_status_icon = QLabel()
        self.lbl_status = ElidedLabel()
        self.lbl_status.setObjectName("statusLine")

        pie_layout.addWidget(lbl_calidad)
        pie_layout.addWidget(self.slider_dpi)
        pie_layout.addWidget(self.lbl_dpi)
        pie_layout.addWidget(self.lbl_peso)
        pie_layout.addStretch()
        pie_layout.addWidget(self.lbl_status_icon)
        pie_layout.addWidget(self.lbl_status)
        pie_layout.addSpacing(6)
        pie_layout.addWidget(self.btn_log)
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
        self.btn_log.setIcon(icon("flecha_abajo" if visible else "flecha_derecha", "#569CD6", 14))
        if visible:
            self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def show_warning(self, message, color):
        """Aviso o error en pocas palabras, al pie. El texto completo queda en el registro."""
        self.lbl_status_icon.setPixmap(icon_pixmap("alerta", color, 14))
        self.lbl_status.setStyleSheet(f"color: {color};")
        self.lbl_status.setText(_aviso_corto(message))
        self.lbl_status.setToolTip(message)
        self.lbl_status_icon.setVisible(True)
        self.lbl_status.setVisible(True)

    def clear_warning(self):
        self.lbl_status_icon.setVisible(False)
        self.lbl_status.setVisible(False)

    @pyqtSlot(str)
    def log_to_console(self, message):
        # Avisos y errores en color. Son lo único que además se muestra al
        # pie de la ventana; el resto queda solo en el registro.
        if message.startswith("AVISO") or message.startswith("Captura directa no disponible"):
            color = "#F0C36B"
        elif message.startswith("Error"):
            color = "#F48771"
        else:
            color = None

        # El color va siempre explícito: si no, el renglón hereda el del
        # anterior y todo lo que sigue a un aviso sale en ámbar.
        timestamp = time.strftime("%H:%M:%S")
        texto = f"<span style='color:{color or '#CCCCCC'};'>{html.escape(message)}</span>"
        self.console.append(f"<span style='color:#569CD6;'>[{timestamp}]</span> {texto}")
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

        if color:
            self.show_warning(message, color)

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
        self.thread.finished_signal.connect(self.scan_finished)
        self.thread.start()

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

    def apply_dark_theme(self):
        qss = """
        QWidget {
            background-color: #1E1E1E;
            color: #D4D4D4;
            font-family: 'Segoe UI', 'Roboto', 'Inter', sans-serif;
            font-size: 13px;
        }
        QLineEdit {
            background-color: #3C3C3C;
            border: 1px solid #3C3C3C;
            border-radius: 4px;
            padding: 5px 10px;
            color: #CCCCCC;
        }
        QLineEdit:focus {
            border: 1px solid #007ACC;
            background-color: #404040;
        }
        /* Desplegable plano, con el mismo aspecto que los botones secundarios.
           La flecha la dibuja FlatComboBox. */
        QComboBox {
            background-color: #333333;
            border: 1px solid #454545;
            border-radius: 6px;
            padding: 5px 30px 5px 10px;
            color: #CCCCCC;
        }
        QComboBox:hover {
            background-color: #404040;
        }
        QComboBox:on {
            border: 1px solid #007ACC;
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
            background-color: #2D2D2D;
            border: 1px solid #454545;
            padding: 4px;
            outline: 0;
            color: #CCCCCC;
        }
        QComboBox QAbstractItemView::item {
            min-height: 26px;
            padding-left: 8px;
            border-radius: 4px;
        }
        QComboBox QAbstractItemView::item:hover,
        QComboBox QAbstractItemView::item:selected {
            background-color: #094771;
            color: #FFFFFF;
        }
        /* Barra de desplazamiento fina, sin flechas. */
        QScrollBar:vertical {
            background: transparent;
            width: 10px;
            margin: 2px;
        }
        QScrollBar::handle:vertical {
            background: #4A4A4A;
            border-radius: 3px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover {
            background: #5E5E5E;
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
            color: #666666;
            font-size: 14px;
        }
        #destinoPath {
            color: #9A9A9A;
        }
        #statusLine {
            color: #8A8A8A;
            font-size: 12px;
        }
        #linkButton {
            background: transparent;
            border: none;
            color: #569CD6;
            padding: 2px 2px;
        }
        #linkButton:hover {
            color: #8CC4F2;
        }
        #mutedLabel {
            color: #9A9A9A;
            font-size: 12px;
        }
        #valueLabel {
            color: #D4D4D4;
            font-size: 12px;
        }
        #captionInfo {
            color: #CCCCCC;
            font-size: 12px;
        }
        #scanButton {
            background-color: #D84315;
            border: none;
            border-radius: 6px;
        }
        #scanButton:hover {
            background-color: #E5501F;
        }
        #scanButton:pressed {
            background-color: #B5380F;
        }
        #scanButton:disabled {
            background-color: #333333;
        }
        #scanText {
            background: transparent;
            color: white;
            font-size: 15px;
            font-weight: bold;
        }
        #scanText:disabled {
            color: #8A8A8A;
        }
        #scanKey {
            background: transparent;
            color: white;
            border: 1px solid rgba(255, 255, 255, 140);
            border-radius: 4px;
            padding: 1px 6px;
            font-size: 11px;
        }
        #secondaryButton:disabled {
            background-color: #2A2A2A;
            border: 1px solid #383838;
        }
        #primaryButton {
            background-color: #007ACC;
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 15px;
            letter-spacing: 1px;
        }
        #primaryButton:hover {
            background-color: #0098FF;
        }
        #primaryButton:pressed {
            background-color: #005A9E;
        }
        #primaryButton:disabled {
            background-color: #333333;
            color: #777777;
        }
        #secondaryButton {
            background-color: #333333;
            color: #CCCCCC;
            border: 1px solid #454545;
            border-radius: 6px;
            padding: 6px 15px;
        }
        #secondaryButton:hover {
            background-color: #404040;
        }
        #debugButton {
            background-color: #333333;
            border: 1px solid #454545;
            border-radius: 6px;
            font-size: 16px;
            padding: 5px 12px;
        }
        #debugButton:hover {
            background-color: #404040;
        }
        #debugButton:checked {
            background-color: #2E7D32; /* Verde oscuro */
            border: 1px solid #4CAF50; /* Verde brillante */
        }
        #consoleOutput {
            background-color: #181818;
            color: #CCCCCC;
            border: 1px solid #2D2D30;
            border-radius: 6px;
            font-family: 'Consolas', monospace;
            font-size: 11px;
        }
        """
        self.setStyleSheet(qss)


if __name__ == '__main__':
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Inter", 10))
    window = ScannerApp()
    window.show()
    sys.exit(app.exec())
