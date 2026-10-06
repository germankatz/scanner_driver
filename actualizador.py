r"""
Actualización del programa desde una carpeta compartida, para no tener que
pasar PC por PC.

El ejecutable publicado es un LaBestia.exe común, copiado en una carpeta que
todas las PCs alcanzan (CARPETA_ACTUALIZACIONES). Su versión se lee del recurso
de versión del .exe, el que Windows muestra en Propiedades > Detalles: publicar
una versión es copiar ese archivo ahí, nada más.

Cuando el programa instalado encuentra una versión más alta que la suya:

  1. copia el ejecutable nuevo al lado suyo, como LaBestia.nuevo.exe;
  2. lo arranca con --instalar y se cierra;
  3. el nuevo espera a que el viejo termine de cerrarse, se copia encima y
     abre el programa ya actualizado.

El reemplazo lo hace el nuevo porque Windows no deja escribir un .exe que se
está ejecutando. De paso, si el nuevo no arranca (copia incompleta, una DLL que
falta), el instalado queda como estaba.

Nada de esto funciona si el programa está en una carpeta donde el usuario no
puede escribir, como el Escritorio público. Por eso se instala en C:\LaBestia
(ver instalar.cmd) y en el escritorio queda un acceso directo.

Este módulo no usa Qt ni numpy: se importa antes que todo lo pesado.
"""
import os
import shutil
import subprocess
import sys
import time

# La versión del programa. El tag del release tiene que ser "v" + esto: CI lo
# verifica, y también que el ejecutable la lleve en su recurso de versión.
VERSION = "1.3.0"

EXE = "LaBestia.exe"
EXE_NUEVO = "LaBestia.nuevo.exe"    # el ejecutable nuevo mientras se instala
_PARCIAL = ".parcial"               # una copia que todavía no terminó

CARPETA_ACTUALIZACIONES = r"H:\see\imagenes_fallecidos\LaBestia"


def _tupla(version):
    return tuple(int(parte) for parte in version.split("."))


def _texto(tupla):
    return ".".join(str(n) for n in tupla)


def version_de_exe(ruta):
    """
    (mayor, menor, parche) del recurso de versión de un .exe, o None si no lo
    tiene o no se puede leer. Lee solo ese recurso, no el archivo entero.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        api = ctypes.WinDLL("version")
        largo = api.GetFileVersionInfoSizeW(ruta, None)
        if not largo:
            return None
        datos = ctypes.create_string_buffer(largo)
        if not api.GetFileVersionInfoW(ruta, 0, largo, datos):
            return None
        puntero, cuantos = ctypes.c_void_p(), ctypes.c_uint()
        if not api.VerQueryValueW(datos, "\\", ctypes.byref(puntero), ctypes.byref(cuantos)):
            return None
        if cuantos.value < 16:
            return None
        # VS_FIXEDFILEINFO: firma, versión de la estructura, y la versión del
        # archivo en dos enteros de 32 bits (mayor.menor y parche.compilación).
        firma, _, alto, bajo = (ctypes.c_uint32 * 4).from_address(puntero.value)
        if firma != 0xFEEF04BD:
            return None
        return alto >> 16, alto & 0xFFFF, bajo >> 16
    except Exception:
        return None


def texto_version_info():
    """El recurso de versión del ejecutable, en el formato que lee PyInstaller."""
    a, b, c = _tupla(VERSION)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('0C0A04B0', [
      StringStruct('FileDescription', 'La bestia'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'LaBestia'),
      StringStruct('OriginalFilename', '{EXE}'),
      StringStruct('ProductName', 'La bestia'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [0x0C0A, 1200])])
  ]
)
"""


def buscar(carpeta):
    """
    Qué hay publicado en la carpeta de actualizaciones. Devuelve
    (estado, versión, ruta del ejecutable publicado):

        "nueva"         hay una versión más alta que la de este programa
        "al_dia"        lo publicado no es más nuevo que este programa
        "sin_publicar"  la carpeta está, pero sin un LaBestia.exe con versión
        "sin_carpeta"   no se llega a la carpeta (unidad de red caída)

    Toca la red: no llamar desde el hilo de la ventana.
    """
    ruta = os.path.join(carpeta, EXE)
    if not os.path.isdir(carpeta):
        return "sin_carpeta", None, ruta
    version = version_de_exe(ruta) if os.path.isfile(ruta) else None
    if version is None:
        return "sin_publicar", None, ruta
    estado = "nueva" if version > _tupla(VERSION) else "al_dia"
    return estado, _texto(version), ruta


def impedimento():
    """Por qué este programa no puede actualizarse solo, o None si puede."""
    if not getattr(sys, "frozen", False):
        return "Se está ejecutando desde el código, no desde el ejecutable."
    carpeta = os.path.dirname(sys.executable)
    # En la variante en carpeta las DLLs van sueltas al lado del ejecutable:
    # habría que reemplazar la carpeta entera, no un archivo.
    interno = os.path.normcase(getattr(sys, "_MEIPASS", ""))
    if interno in (os.path.normcase(carpeta),
                   os.path.normcase(os.path.join(carpeta, "_internal"))):
        return "La variante en carpeta se actualiza a mano, reemplazando la carpeta."
    # os.access no mira los permisos de Windows: hay que probar de verdad. Y a
    # mano, porque tempfile se queda reintentando sin fin en una carpeta donde
    # no puede crear archivos.
    prueba = os.path.join(carpeta, f"LaBestia.{os.getpid()}.prueba")
    try:
        with open(prueba, "wb"):
            pass
        os.remove(prueba)
    except OSError:
        return (f"El programa está en {carpeta}, donde este usuario no puede "
                f"escribir. Hay que instalarlo con instalar.cmd.")
    return None


def _copiar(origen, destino):
    """Copia sin dejar nunca un archivo a medias con el nombre de destino."""
    try:
        shutil.copyfile(origen, destino)
    except BaseException:
        try:
            os.remove(destino)
        except OSError:
            pass
        raise


def preparar(origen):
    """
    Trae el ejecutable publicado al lado del instalado, como LaBestia.nuevo.exe,
    y devuelve esa ruta. Toca la red: no llamar desde el hilo de la ventana.
    """
    nuevo = os.path.join(os.path.dirname(sys.executable), EXE_NUEVO)
    parcial = nuevo + _PARCIAL
    antes = os.stat(origen)
    _copiar(origen, parcial)
    despues = os.stat(origen)
    # Si justo lo estaban publicando, lo copiado puede ser mitad de cada uno.
    cambio = (despues.st_size, despues.st_mtime_ns) != (antes.st_size, antes.st_mtime_ns)
    if cambio or os.path.getsize(parcial) != antes.st_size:
        os.remove(parcial)
        raise RuntimeError("el archivo publicado cambió mientras se copiaba; "
                           "probá de nuevo en un minuto")
    os.replace(parcial, nuevo)
    return nuevo


def abrir(*args):
    """Arranca un ejecutable del programa como proceso independiente de este."""
    env = dict(os.environ)
    # Un ejecutable de PyInstaller arrancado desde otro puede creerse parte del
    # primero y usar su carpeta temporal, que desaparece cuando aquel cierra.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env.pop("_MEIPASS2", None)
    subprocess.Popen(list(args), env=env, cwd=os.path.dirname(args[0]), close_fds=True)


def lanzar_instalacion(nuevo):
    """Arranca el ejecutable nuevo para que reemplace a este. Después hay que cerrar."""
    abrir(nuevo, "--instalar", sys.executable)


def instalar(destino, espera=30):
    """
    Lo corre el ejecutable nuevo: se copia encima de `destino` (el instalado)
    apenas este termina de cerrarse. Devuelve None, o el error si en `espera`
    segundos no se pudo: el programa sigue abierto, por ejemplo en otra sesión
    de la misma PC. No abre nada; eso queda para quien llama.
    """
    parcial = destino + _PARCIAL
    limite = time.monotonic() + espera
    while True:
        try:
            # Primero una copia completa al lado y recién después el cambio de
            # nombre: el instalado nunca queda a medio escribir.
            if not os.path.exists(parcial):
                _copiar(sys.executable, parcial)
            os.replace(parcial, destino)
            return None
        except OSError as error:
            if time.monotonic() > limite:
                try:
                    os.remove(parcial)
                except OSError:
                    pass
                return error
            time.sleep(0.5)


def limpiar_restos(intentos=8):
    """
    Borra lo que dejó la última actualización al lado del ejecutable. El
    LaBestia.nuevo.exe puede tardar unos segundos en terminar de cerrarse.
    """
    if not getattr(sys, "frozen", False):
        return
    carpeta = os.path.dirname(sys.executable)
    for nombre in (EXE_NUEVO, EXE_NUEVO + _PARCIAL, EXE + _PARCIAL):
        ruta = os.path.join(carpeta, nombre)
        for _ in range(intentos):
            try:
                os.remove(ruta)
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(1)


def actualizar_desde(carpeta):
    """
    LaBestia.exe --actualizar-desde <carpeta>: lo mismo que el botón
    "Actualizar ahora", sin abrir la ventana. Código de salida: 0 si arrancó la
    actualización, 10 si no había nada más nuevo, 1 si no se pudo.
    """
    try:
        estado, _, ruta = buscar(carpeta)
        if estado == "al_dia":
            return 10
        if estado != "nueva" or impedimento():
            return 1
        lanzar_instalacion(preparar(ruta))
        return 0
    except Exception:
        return 1
