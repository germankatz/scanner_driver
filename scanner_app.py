import sys
import os
import time
import glob
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QTextEdit, QFrame,
    QDialog, QFileDialog, QGraphicsDropShadowEffect, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QPixmap, QKeySequence, QShortcut

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

    strategies = []

    # A) Otsu, las dos polaridades (el papel puede quedar en cualquiera de las
    #    dos clases segun de que lado caiga el umbral).
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    strategies.append(("otsu", otsu))
    strategies.append(("otsu_inv", cv2.bitwise_not(otsu)))

    # B) Bordes: el canto del papel deja una sombra aunque el contraste de
    #    brillo entre papel y tapa sea casi nulo. No depende del histograma
    #    global, asi que la suciedad no lo corre.
    edges = cv2.Canny(blurred, 30, 90)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    strategies.append(("canny", edges))

    # C) Desvio respecto del fondo de la cama, estimado con la mediana del
    #    marco exterior (ahi nunca hay documento).
    border = np.concatenate([
        blurred[:10, :].ravel(), blurred[-10:, :].ravel(),
        blurred[:, :10].ravel(), blurred[:, -10:].ravel(),
    ])
    bed = int(np.median(border))
    diff = cv2.absdiff(blurred, np.full_like(blurred, bed))
    _, dev = cv2.threshold(diff, 12, 255, cv2.THRESH_BINARY)
    strategies.append(("fondo", dev))

    kernel = np.ones((5, 5), np.uint8)

    # Se guarda aparte el mejor candidato "flojo" (el que pasa el filtro de
    # area pero no el de rectangularidad). Solo se usa si ninguna estrategia
    # da un candidato bueno. Asi esta funcion nunca rechaza algo que el
    # algoritmo anterior habria aceptado: en el peor caso empata.
    flojo = None

    for name, mask in strategies:
        m = mask.copy()
        # Borde negro para despegar el papel que toque el limite de la imagen
        cv2.rectangle(m, (0, 0), (w, h), 0, 10)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=2)

        if debug_dir:
            cv2.imwrite(os.path.join(debug_dir, f"debug_mask_{name}.jpg"), m)

        contours, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

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


def process_and_crop(input_path, output_path, log_signal=None, debug_mode=False):
    """
    Procesa la imagen escaneada mediante una transformacion de perspectiva.
    Optimizado: Reduce la resolucion para hallar contornos rapido y aplica el
    recorte en alta res. Recorta los bordes iniciales para evitar el marco
    plastico del escaner.

    Devuelve (ruta_final, detectado). "detectado" en False significa que se
    guardo la cama completa como fallback.
    """
    output_path_png = output_path.replace('.jpg', '.png')
    try:
        import cv2
        import numpy as np
        img = cv2.imread(input_path)
        if img is None:
            return input_path, False

        # 1. Recortar el marco fisico del escaner. Las margenes van en
        #    proporcion, no en pixeles fijos: el marco es de tamano fisico
        #    constante, asi que en pixeles depende del dpi. Con los 35/30 px
        #    fijos de antes, un escaneo a 300 dpi dejaba la mitad del marco.
        h_orig, w_orig = img.shape[:2]
        v_margin = int(round(h_orig * 0.0233))   # equivale a 35 px sobre 1500
        h_margin = int(round(w_orig * 0.0250))   # equivale a 30 px sobre 1200

        if h_orig > 2 * v_margin and w_orig > 2 * h_margin:
            img = img[v_margin:h_orig - v_margin, h_margin:w_orig - h_margin]

        # 2. Bajar la resolucion temporalmente para procesar rapido
        ratio = img.shape[0] / 800.0
        orig = img.copy()

        if ratio > 1:
            small_img = cv2.resize(img, (int(img.shape[1] / ratio), 800))
        else:
            small_img = img.copy()
            ratio = 1.0

        debug_dir = os.path.dirname(output_path) if debug_mode else None
        c, strategy = _detect_document(small_img, debug_dir)

        if c is not None:
            # Ajustar contorno a la escala original
            c = (c.astype("float") * ratio).astype("int")

            if debug_mode:
                debug_img = orig.copy()
                cv2.drawContours(debug_img, [c], -1, (0, 255, 0), 10)
                cv2.imwrite(os.path.join(debug_dir, "debug_4_contour.jpg"), debug_img)

            box = cv2.boxPoints(cv2.minAreaRect(c))
            pts = np.array(box, dtype=np.int32).reshape(4, 2)
            rect = order_points(pts)
            (tl, tr, br, bl) = rect

            widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
            widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
            maxWidth = max(int(widthA), int(widthB))

            heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
            heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
            maxHeight = max(int(heightA), int(heightB))

            dst = np.array([
                [0, 0],
                [maxWidth - 1, 0],
                [maxWidth - 1, maxHeight - 1],
                [0, maxHeight - 1]], dtype="float32")

            M = cv2.getPerspectiveTransform(rect, dst)
            warped = cv2.warpPerspective(orig, M, (maxWidth, maxHeight))

            if warped.size > 0:
                cv2.imwrite(output_path_png, warped)
                if log_signal:
                    log_signal.emit(
                        f"Documento detectado ({strategy}), enderezado y guardado "
                        f"sin perdida: {maxWidth}x{maxHeight} px."
                    )
                return output_path_png, True

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
        cv2.imwrite(output_path_png, img)
        return output_path_png, False
    except Exception as e:
        if log_signal:
            log_signal.emit(f"Error en procesamiento: {e}")
        return input_path, False


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

SCAN_DPI = 300


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
        import cv2
        img = cv2.imread(raw_path)
        if img is None:
            return
        h, w = img.shape[:2]
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


class ScannerThread(QThread):
    log_signal = pyqtSignal(str)
    image_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, scanner_name, output_path, debug_mode, is_first_scan=False, manual_mode=False):
        super().__init__()
        self.scanner_name = scanner_name
        self.output_path = output_path
        self.debug_mode = debug_mode
        self.is_first_scan = is_first_scan
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
                        w, h = acquire_wia_direct(dev_info, raw_path, SCAN_DPI, self.log_signal)
                        self.log_signal.emit(f"Captura directa WIA a {SCAN_DPI} dpi: {w}x{h} px.")
                        acquired = True
                    except Exception as e:
                        self.log_signal.emit(
                            f"Captura directa no disponible ({e}). Cayendo al diálogo nativo."
                        )

            # --- Fallback: diálogo nativo (y modo manual) ---
            if not acquired:
                import threading

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
                            shell.SendKeys(str(SCAN_DPI))
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
                _warn_if_low_res(raw_path, SCAN_DPI, self.log_signal)

                self.log_signal.emit("Procesando imagen (Enderezado y recorte automático)...")
                final_path, detectado = process_and_crop(
                    raw_path, self.output_path, self.log_signal, self.debug_mode
                )

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

                if final_path:
                    self.image_signal.emit(final_path)

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


def save_config(output_dir, file_prefix):
    """Devuelve (ok, detalle) para poder informarlo en el log."""
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump({"output_dir": output_dir, "file_prefix": file_prefix},
                      f, indent=2, ensure_ascii=False)
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
            
        self.setup_ui()
        self.apply_dark_theme()
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Top Bar (Scanner Select & Config)
        top_layout = QHBoxLayout()
        self.cb_scanner = QComboBox()
        self.cb_scanner.setFixedWidth(200)
        self.populate_scanners()
        
        btn_config = QPushButton("⚙️ Configurar Destino")
        btn_config.clicked.connect(self.open_settings)
        btn_config.setObjectName("secondaryButton")
        
        self.btn_debug = QPushButton("🐛")
        self.btn_debug.setCheckable(True)
        self.btn_debug.setObjectName("debugButton")
        self.btn_debug.setToolTip("Activar Modo Debug (Guarda imágenes para diagnóstico)")
        
        top_layout.addWidget(QLabel("Escáner:"))
        top_layout.addWidget(self.cb_scanner)
        top_layout.addStretch()
        top_layout.addWidget(btn_config)
        top_layout.addWidget(self.btn_debug)
        main_layout.addLayout(top_layout)

        # Center Preview
        self.lbl_preview = QLabel("Presiona ENTER o haz clic en 'INICIAR ESCANEO'")
        self.lbl_preview.setObjectName("previewCanvas")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.lbl_preview, stretch=1)

        # Scan Button
        self.btn_scan = QPushButton("INICIAR ESCANEO (Enter)")
        self.btn_scan.setObjectName("primaryButton")
        self.btn_scan.setStyleSheet("background-color: #D84315; border-radius: 6px;")
        self.btn_scan.setFixedHeight(60)
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_scan.setToolTip("Inicia el escaneo seleccionando automáticamente la Configuración Personalizada")
        
        self.btn_manual = QPushButton("⚙")
        self.btn_manual.setFixedWidth(50)
        self.btn_manual.setFixedHeight(60)
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

        # Console
        self.console = QTextEdit()
        self.console.setObjectName("consoleOutput")
        self.console.setReadOnly(True)
        self.console.setFixedHeight(100)
        self.console.document().setMaximumBlockCount(100) # Limita el log a 100 mensajes
        main_layout.addWidget(self.console)

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
            self.log_to_console(f"Destino actualizado: {self.output_dir}")

            ok, detalle = save_config(self.output_dir, self.file_prefix)
            if ok:
                self.log_to_console("Configuración guardada: se va a recordar al reiniciar.")
            else:
                self.log_to_console(f"AVISO: no se pudo guardar la configuración ({detalle}).")

    def get_next_filename(self):
        # Auto-increment rellenando huecos: un solo listdir en vez de un
        # os.path.exists por número (clave en unidades de red).
        import re
        pattern = re.compile(re.escape(self.file_prefix) + r"(\d+)\.png$", re.IGNORECASE)
        try:
            names = os.listdir(self.output_dir)
        except OSError:
            names = []
        used = {int(m.group(1)) for n in names if (m := pattern.match(n))}
        counter = 1
        while counter in used:
            counter += 1
        return os.path.join(self.output_dir, f"{self.file_prefix}{counter}.png")

    @pyqtSlot(str)
    def log_to_console(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.console.append(f"<span style='color:#569CD6;'>[{timestamp}]</span> {message}")
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def start_scan(self):
        if not self.btn_scan.isEnabled():
            return
            
        self.btn_scan.setEnabled(False)
        self.lbl_preview.setText("Escaneando...")
        
        scanner = self.cb_scanner.currentText()
        out_path = self.get_next_filename()
        debug_active = self.btn_debug.isChecked()
        
        self.thread = ScannerThread(scanner, out_path, debug_active, self.is_first_scan)
        self.is_first_scan = False
        self.thread.log_signal.connect(self.log_to_console)
        self.thread.image_signal.connect(self.display_image)
        self.thread.finished_signal.connect(self.scan_finished)
        self.thread.start()

    def scan_finished(self):
        self.btn_scan.setEnabled(True)
        if self.lbl_preview.text() in ["Escaneando...", "Modo Manual Activo..."]:
            self.lbl_preview.setText("Listo para el siguiente escaneo.")

    def start_scan_manual(self):
        if not self.btn_scan.isEnabled():
            return
            
        self.btn_scan.setEnabled(False)
        self.lbl_preview.setText("Modo Manual Activo...")
        
        scanner = self.cb_scanner.currentText()
        out_path = self.get_next_filename()
        debug_active = self.btn_debug.isChecked()
        
        self.thread = ScannerThread(scanner, out_path, debug_active, is_first_scan=False, manual_mode=True)
        self.thread.log_signal.connect(self.log_to_console)
        self.thread.image_signal.connect(self.display_image)
        self.thread.finished_signal.connect(self.scan_finished)
        self.thread.start()

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
            self.lbl_preview.setText("Procesando imagen local...")
            self.log_to_console(f"Procesando archivo local: {file_path}")
            
            try:
                final_path, _detectado = process_and_crop(file_path, out_path, None, debug_active)
                self.display_image(final_path)
                self.log_to_console("Procesamiento local terminado.")
                self.lbl_preview.setText("Listo para el siguiente escaneo.")
            except Exception as e:
                self.log_to_console(f"Error procesando imagen local: {e}")

    @pyqtSlot(str)
    def display_image(self, filepath):
        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(self.lbl_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.lbl_preview.setPixmap(scaled_pixmap)
        else:
            self.lbl_preview.setText("Error al cargar la imagen.")

    @pyqtSlot()
    def scan_finished(self):
        self.btn_scan.setEnabled(True)
        if hasattr(self, 'btn_scan_auto'):
            self.btn_scan_auto.setEnabled(True)
        if self.lbl_preview.text() == "Escaneando...":
            self.lbl_preview.setText("Listo para el siguiente escaneo.")

    def apply_dark_theme(self):
        qss = """
        QWidget {
            background-color: #1E1E1E;
            color: #D4D4D4;
            font-family: 'Segoe UI', 'Roboto', 'Inter', sans-serif;
            font-size: 13px;
        }
        QComboBox, QLineEdit {
            background-color: #3C3C3C;
            border: 1px solid #3C3C3C;
            border-radius: 4px;
            padding: 5px 10px;
            color: #CCCCCC;
        }
        QComboBox:focus, QLineEdit:focus {
            border: 1px solid #007ACC;
            background-color: #404040;
        }
        #previewCanvas {
            background-color: #121212;
            border: 2px dashed #333333;
            border-radius: 12px;
            color: #666666;
            font-size: 14px;
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
