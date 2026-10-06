"""
Lectura del crudo y escritura del PNG final, las dos operaciones que se
llevaban tres cuartos del tiempo de procesamiento de cada escaneo.

    read_image(path)      lo mismo que cv2.imread(path)
    image_size(path)      (ancho, alto) sin decodificar la imagen
    write_png(img, path)  lo mismo que cv2.imwrite(path, img) para un .png

Las dos dan el mismo resultado que OpenCV: read_image devuelve el mismo
ndarray y write_png un PNG que decodifica a los mismos pixeles. Todo lo que no
sea el caso comun (y cualquier error inesperado) cae a cv2, que es la
referencia.

Lectura
-------
Solo se lee a mano el BMP que escribe WIA (y cv2.imwrite): BITMAPINFOHEADER de
40 bytes, 24 bits, sin compresion, alto positivo (filas de abajo hacia arriba)
y con los datos enteros dentro del archivo. En ese formato cada fila ocupa
`paso = ancho*3 redondeado a multiplo de 4` bytes y los pixeles ya estan en
BGR, asi que "decodificar" es copiar las filas en orden inverso descartando el
relleno. La lectura y la copia se reparten entre hasta 3 hilos (las dos sueltan
el GIL): unos 9 ms para un crudo de 32 MB, contra 30 de cv2.imread.

Las rutas con caracteres no ASCII van a cv2.imread a proposito: en Windows
OpenCV no las puede abrir (imread da None) y la app se apoya en eso para
conservar el crudo; leerlas aca cambiaria ese comportamiento.

Escritura
---------
Mismo formato que cv2.imwrite por defecto: 8 bits, gris / RGB / RGBA, sin
entrelazado, filtro Sub en todas las filas, un solo flujo zlib. Casi todo el
tiempo de escribir un PNG es el deflate, y cv2 lo hace en un solo hilo. Aca la
imagen se parte en bandas de filas que zlib (stdlib) comprime en paralelo y que
se pegan en un unico flujo valido, una banda por chunk IDAT. Los bytes del
archivo no dependen de la cantidad de nucleos.

Cada banda elige la estrategia de deflate:
  - Z_RLE (la de cv2) donde hay corridas que valen la pena;
  - Z_HUFFMAN_ONLY donde no (ruido de escaner): pesa ~1% menos y es mas rapida.
Decide un modelo de entropia sobre 1 de cada 4 filas de la banda; si despues la
banda comprime bastante mas de lo que la muestra hacia esperar, se vuelve a
decidir mirando la banda entera. Elegir mal solo cambia el tamano del archivo:
los pixeles salen siempre exactos.
"""
import os
import struct
import threading
import zlib

import cv2
import numpy as np


# --- Lectura del crudo ------------------------------------------------------

# magic, bfSize, res1, res2, bfOffBits | biSize, ancho, alto, planos, bpp, compresion
_CAB = struct.Struct("<2sIHHIIiiHHI")
_LARGO_CAB = 54            # 14 (archivo) + 40 (BITMAPINFOHEADER)

# Limites con los que cv2.imread acepta una imagen (CV_IO_MAX_IMAGE_*). Mas
# alla de esto imread tira una excepcion: que la tire el.
_MAX_LADO = 1 << 20
_MAX_PIXELES = 1 << 30

_TROZO = 256 * 1024        # bytes por lectura (medido: 128K y 1M rinden menos)
_HILOS = 3                 # con 4 no se midio mejora y no queda nucleo libre
_MIN_POR_HILO = 4 << 20    # crear un hilo cuesta ~0,6 ms: no se paga con menos


def _cabecera_bmp(f):
    """(offset de los datos, ancho, alto, paso) si f es el BMP simple; si no, None."""
    cab = f.read(_LARGO_CAB)
    if len(cab) != _LARGO_CAB:
        return None
    magic, _, _, _, off, tam_cab, w, h, planos, bpp, compresion = _CAB.unpack_from(cab)
    if magic != b"BM" or tam_cab != 40 or planos != 1 or bpp != 24 or compresion != 0:
        return None
    if not (0 < w <= _MAX_LADO and 0 < h <= _MAX_LADO and w * h <= _MAX_PIXELES):
        return None
    paso = (w * 3 + 3) & -4
    if off < _LARGO_CAB or off + paso * h > os.fstat(f.fileno()).st_size:
        return None
    return off, w, h, paso


def _trabajar(f, off, paso, w3, filas, h, n, nt, est, candado):
    """
    Toma trozos de a uno hasta que no queden. El trozo j son las filas de
    archivo [j*n, j*n + k), que estan guardadas de abajo hacia arriba: la fila
    de archivo r es la fila de imagen h-1-r.

    est = [siguiente trozo libre, hubo una falla, trozos completados]
    """
    tmp = np.empty((n, paso), np.uint8)
    mv = memoryview(tmp).cast("B")
    hechos = 0
    while True:
        with candado:
            j = est[0]
            if j >= nt or est[1]:
                break
            est[0] = j + 1
        r0 = j * n
        k = n if r0 + n <= h else h - r0
        f.seek(off + r0 * paso)
        if f.readinto(mv[:k * paso]) != k * paso:
            est[1] = True       # el archivo se quedo corto
            break
        # tmp[k-1], ..., tmp[0] van a las filas y1-k, ..., y1-1; el relleno queda afuera
        y1 = h - r0
        filas[y1 - k:y1] = tmp[k - 1::-1, :w3]
        hechos += 1
    with candado:
        est[2] += hechos


def _hilo(path, args):
    try:
        # Descriptor propio: la posicion de lectura no se comparte entre hilos.
        with open(path, "rb", buffering=0) as f:
            _trabajar(f, *args)
    except Exception:
        args[7][1] = True       # est: hubo una falla -> se cae a cv2.imread


def _leer_bmp_simple(path):
    """El ndarray BGR si `path` es el BMP simple; None en cualquier otro caso."""
    if not isinstance(path, str) or not path.isascii():
        return None
    try:
        with open(path, "rb", buffering=0) as f:
            cab = _cabecera_bmp(f)
            if cab is None:
                return None
            off, w, h, paso = cab
            w3 = w * 3

            img = np.empty((h, w, 3), np.uint8)
            filas = img.reshape(h, w3)      # vista: mismas filas, sin el eje de canal
            n = max(1, _TROZO // paso)      # filas por trozo
            nt = -(-h // n)                 # cantidad de trozos
            est = [0, False, 0]
            args = (off, paso, w3, filas, h, n, nt, est, threading.Lock())

            nh = min(_HILOS, os.cpu_count() or 1, (paso * h) // _MIN_POR_HILO, nt)
            hilos = []
            try:
                for _ in range(1, nh):
                    t = threading.Thread(target=_hilo, args=(path, args))
                    try:
                        t.start()
                    except RuntimeError:
                        break               # no hay mas hilos: se sigue con los que haya
                    hilos.append(t)
                _trabajar(f, *args)
            except BaseException:
                est[1] = True               # que los demas corten
                raise
            finally:
                # Pase lo que pase, al salir nadie escribe en img ni tiene el
                # archivo abierto.
                for t in hilos:
                    t.join()
            return img if (est[2] == nt and not est[1]) else None
    except Exception:
        return None


def read_image(path):
    """
    Lo mismo que cv2.imread(path): ndarray uint8 BGR contiguo, dueno de su
    memoria y completo en RAM (el archivo queda cerrado), o None si no se
    puede leer.
    """
    img = _leer_bmp_simple(path)
    if img is None:
        img = cv2.imread(path)      # todo lo que no sea el caso simple
    return img


def image_size(path):
    """(ancho, alto) de la imagen, o None. En el BMP simple lee solo el encabezado."""
    if isinstance(path, str) and path.isascii():
        try:
            with open(path, "rb", buffering=0) as f:
                cab = _cabecera_bmp(f)
            if cab is not None:
                return cab[1], cab[2]
        except Exception:
            pass
    img = cv2.imread(path)
    if img is None:
        return None
    return img.shape[1], img.shape[0]


# --- Escritura del PNG ------------------------------------------------------

_FIRMA = b"\x89PNG\r\n\x1a\n"
_BANDA = 512 * 1024      # bytes filtrados por banda (aprox.)
_MAX_HILOS = 8
_TOL = 0.02              # Huffman solo si no pesa mas que RLE*(1+_TOL) segun el modelo
_PASO = 4                # el modelo mira 1 fila de cada _PASO de la banda
_GUARDA = 0.90           # si la banda comprime mas que esto x lo previsto, la muestra no sirve
_ADLER = 65521
# Codigos de largo de deflate (RFC 1951, 3.2.5): largo base y bits extra.
_LBASE = np.array([3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51,
                   59, 67, 83, 99, 115, 131, 163, 195, 227, 258], np.intp)
_LEXTRA = np.array([0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4,
                    4, 5, 5, 5, 5, 0], np.float64)


def _adler_combinar(a1, a2, largo2):
    """adler32(A+B) a partir de adler32(A), adler32(B) y len(B) (adler32_combine de zlib)."""
    rem = largo2 % _ADLER
    s1 = a1 & 0xFFFF
    s2 = (rem * s1) % _ADLER
    s1 += (a2 & 0xFFFF) + _ADLER - 1
    s2 += ((a1 >> 16) & 0xFFFF) + ((a2 >> 16) & 0xFFFF) + _ADLER - rem
    if s1 >= _ADLER:
        s1 -= _ADLER
    if s1 >= _ADLER:
        s1 -= _ADLER
    if s2 >= (_ADLER << 1):
        s2 -= (_ADLER << 1)
    if s2 >= _ADLER:
        s2 -= _ADLER
    return s1 | (s2 << 16)


def _chunk(tipo, datos):
    return (struct.pack(">I", len(datos)) + tipo + datos
            + struct.pack(">I", zlib.crc32(datos, zlib.crc32(tipo))))


def _ihdr(img):
    alto, ancho = img.shape[:2]
    bpp = 1 if img.ndim == 2 else img.shape[2]
    return _chunk(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, {1: 0, 3: 2, 4: 6}[bpp], 0, 0, 0))


def _bits(cuentas):
    """Bits de un codigo ideal (entropia) para esas cuentas de simbolos."""
    c = cuentas[cuentas > 0]
    n = float(c.sum())
    return n * np.log2(n) - float(np.dot(c, np.log2(c)))


class _Obrero:
    """Buffers de trabajo de un hilo y las etapas por banda."""

    def __init__(self, img, filas_banda):
        self.img = img
        self.alto, self.ancho = img.shape[:2]
        self.bpp = 1 if img.ndim == 2 else img.shape[2]
        self.fila = self.ancho * self.bpp
        hb = min(filas_banda, self.alto)
        self.buf = np.empty((hb, self.fila + 1), np.uint8)
        self.buf[:, 0] = 1                                  # filtro Sub en todas las filas
        if self.bpp > 1:
            self.tmp = np.empty((hb, self.fila), np.uint8)
            self.codigo = cv2.COLOR_BGR2RGB if self.bpp == 3 else cv2.COLOR_BGRA2RGBA
        self.e1 = self.e2 = None
        self.deflate = {}                     # un compresor por estrategia, reusado entre bandas

    def filtrar(self, y0, y1):
        """Filas y0:y1 ya filtradas (byte de filtro + Sub), en orden RGB. Vista 2-D contigua."""
        h, bpp, fila = y1 - y0, self.bpp, self.fila
        src = self.img[y0:y1].reshape(h, fila)
        b = self.buf[:h]
        if bpp == 1:
            b[:, 1] = src[:, 0]
            np.subtract(src[:, 1:], src[:, :-1], out=b[:, 2:])
            return b
        # Sub es por canal, asi que da lo mismo restar en BGR y despues invertir canales.
        t = self.tmp[:h]
        t[:, :bpp] = src[:, :bpp]
        np.subtract(src[:, bpp:], src[:, :-bpp], out=t[:, bpp:])
        destino = b[:, 1:].reshape(h, self.ancho, bpp)       # vista: filas con salto fila+1
        r = cv2.cvtColor(t.reshape(h, self.ancho, bpp), self.codigo, dst=destino)
        if (r is not destino and
                r.__array_interface__["data"][0] != destino.__array_interface__["data"][0]):
            destino[...] = r                                  # cv2 no escribio en el lugar
        return b

    def modelo(self, b):
        """(bits con Huffman solo, bits con Z_RLE) para los bytes de b, segun entropia.

        Arma, con las corridas reales de b, las cuentas de simbolos que emitiria
        deflate_rle de zlib (lo que usa cv2) y compara los dos flujos.
        b: 2-D uint8 contiguo.
        """
        n = b.size
        cuentas = np.empty(286)               # 256 literales, fin de bloque, 29 largos
        cuentas[:256] = cv2.calcHist([b], [0], None, [256], [0, 256]).ravel()
        cuentas[256] = 1.0
        cuentas[257:] = 0.0
        costo_h = _bits(cuentas)
        if n < 8:
            return costo_h, costo_h
        if self.e1 is None or self.e1.size < n:
            self.e1 = np.empty(n, np.bool_)
            self.e2 = np.empty(n, np.bool_)
        f = b.reshape(-1)
        e1 = self.e1[:n - 1]
        np.equal(f[1:], f[:-1], out=e1)
        # e3[i]: f[i] == f[i+1] == f[i+2] == f[i+3]. Se guarda con un False a cada lado.
        ex = self.e2[:n - 1]
        ex[0] = ex[n - 2] = False
        e3 = ex[1:n - 2]
        np.bitwise_and(e1[:-2], e1[1:-1], out=e3)
        np.bitwise_and(e3, e1[2:], out=e3)
        q = int(np.count_nonzero(e3))
        if q == 0:
            return costo_h, costo_h           # ni una corrida de 4: RLE emite lo mismo
        if 4 * q > n:
            return costo_h, 0.0               # corridas por todos lados: RLE sin vueltas
        # Bordes de las corridas de e3: posiciones pares = inicio, impares = fin (exclusivo).
        bordes = np.flatnonzero(np.not_equal(ex[1:], ex[:-1], out=e1[:n - 2]))
        ini = bordes[0::2]
        # Corrida de L bytes iguales (L >= 4): deflate_rle emite 1 literal y cubre los L-1
        # restantes con matches de hasta 258; si sobran 1 o 2 bytes van como literales.
        cubre = bordes[1::2] - ini
        cubre += 2
        sim = f[ini]
        if int(cubre.max()) < 258:
            n258 = 0
            resto = en_match = cubre
        else:
            n258, resto = np.divmod(cubre, 258)
            en_match = cubre - np.where(resto >= 3, 0, resto)
            n258 = int(n258.sum())
        largos = np.add.reduceat(np.bincount(resto, minlength=259)[:259], _LBASE)
        largos = largos.astype(np.float64)
        largos[28] += n258
        cuentas[:256] -= np.bincount(sim, weights=en_match, minlength=256)
        cuentas[257:] = largos
        # + bits extra de los largos + 1 bit de distancia por match
        costo_r = _bits(cuentas) + float(np.dot(largos, _LEXTRA)) + float(largos.sum())
        return costo_h, costo_r

    def _deflate(self, b, estrategia, ultima):
        """Deflate crudo de b como tramo independiente y alineado a byte.

        El compresor se reusa entre bandas del mismo hilo (ahorra crearlo cada vez). Las
        bandas de un hilo no son contiguas en el archivo, asi que cada tramo se cierra con
        Z_FULL_FLUSH: deja el flujo alineado a byte y borra el estado, de modo que el tramo
        siguiente no referencia nada anterior y se puede pegar en cualquier lugar.
        """
        c = self.deflate.get(estrategia)
        if c is None:
            c = self.deflate[estrategia] = zlib.compressobj(1, zlib.DEFLATED, -15, 8, estrategia)
        z = c.compress(b)
        if ultima:
            del self.deflate[estrategia]
            return z, c.flush(zlib.Z_FINISH)
        return z, c.flush(zlib.Z_FULL_FLUSH)

    def comprimir(self, b, k, ultima):
        """Elige la estrategia de la banda k (ya filtrada) y la comprime."""
        n = b.size
        previsto = None
        if n < 4096:
            rle = True                        # banda chica: lo mismo que cv2, sin estimar
        else:
            if b.shape[0] >= 4 * _PASO:       # muestra: 1 fila de cada _PASO, la fase rota
                muestra = np.ascontiguousarray(b[k % _PASO::_PASO])
                costo_h, costo_r = self.modelo(muestra)
                previsto = costo_h * (n / muestra.size)
            else:
                costo_h, costo_r = self.modelo(b)
            rle = costo_r * (1.0 + _TOL) < costo_h
        if rle:
            return self._deflate(b, zlib.Z_RLE, ultima)
        z, z2 = self._deflate(b, zlib.Z_HUFFMAN_ONLY, False)
        if previsto is not None and 8 * (len(z) + len(z2)) < _GUARDA * previsto:
            # La banda entera comprime bastante mas que lo que decia la muestra: no la
            # representa. Se decide de nuevo mirando la banda completa.
            costo_h, costo_r = self.modelo(b)
            if costo_r * (1.0 + _TOL) < costo_h:
                return self._deflate(b, zlib.Z_RLE, ultima)
        if ultima:
            # Cierre del flujo: bloque fijo vacio marcado como final (BFINAL=1, BTYPE=01,
            # fin de bloque). Es lo mismo que emite zlib para una entrada vacia.
            z2 += b"\x03\x00"
        return z, z2


def _png_un_flujo(img, filas_banda):
    """Camino secuencial: un solo flujo Sub + Z_RLE, igual que cv2."""
    ob = _Obrero(img, filas_banda)
    c = zlib.compressobj(1, zlib.DEFLATED, 15, 8, zlib.Z_RLE)
    trozos = []
    for y0 in range(0, ob.alto, filas_banda):
        trozos.append(c.compress(ob.filtrar(y0, min(y0 + filas_banda, ob.alto))))
    trozos.append(c.flush())
    return b"".join((_FIRMA, _ihdr(img), _chunk(b"IDAT", b"".join(trozos)), _chunk(b"IEND", b"")))


def _escribir(img, f):
    """Codifica img y la va escribiendo en f (binario) a medida que hay bandas listas."""
    alto, ancho = img.shape[:2]
    bpp = 1 if img.ndim == 2 else img.shape[2]
    por_fila = ancho * bpp + 1
    # Cantidad de bandas: cerca de _BANDA bytes cada una y, si son varias, multiplo de 4 para
    # que se repartan parejo entre 2 o 4 nucleos. No depende de la maquina: mismos bytes siempre.
    n = int(round(alto * por_fila / _BANDA))
    n = 4 * int(round(n / 4.0)) if n >= 4 else max(1, n)
    filas_banda = -(-alto // min(n, alto))
    cortes = list(range(0, alto, filas_banda)) + [alto]
    n = len(cortes) - 1
    salida = [None] * n               # por banda: (chunk IDAT, adler, largo crudo, largo z)
    crc_idat = zlib.crc32(b"IDAT")
    turno = iter(range(n))            # next() de un iterador es atomico bajo el GIL
    errores = []
    estado = [0]                      # proxima banda a escribir

    def escribir_listas():
        k = estado[0]
        while k < n - 1 and salida[k] is not None:
            f.write(salida[k][0])
            k += 1
        estado[0] = k

    def obrero(principal):
        try:
            ob = _Obrero(img, filas_banda)
            for k in turno:
                if errores:
                    return
                b = ob.filtrar(cortes[k], cortes[k + 1])
                adler = zlib.adler32(b)
                z, z2 = ob.comprimir(b, k, k == n - 1)
                cab = b"\x78\x01" if k == 0 else b""        # cabecera zlib: deflate, ventana 32K
                largo = len(cab) + len(z) + len(z2)
                crc = zlib.crc32(z2, zlib.crc32(z, zlib.crc32(cab, crc_idat)))
                if k == n - 1:        # a la ultima le falta el adler32 de todo el flujo
                    trozo = (struct.pack(">I", largo + 4) + b"IDAT" + cab + z + z2, crc)
                else:
                    trozo = b"".join((struct.pack(">I", largo), b"IDAT", cab, z, z2,
                                      struct.pack(">I", crc)))
                salida[k] = (trozo, adler, b.size, largo)
                if principal:
                    escribir_listas()
        except BaseException as e:    # se relanza en el hilo principal
            errores.append(e)

    f.write(_FIRMA + _ihdr(img))
    hilos = []
    for _ in range(min(os.cpu_count() or 1, _MAX_HILOS, n) - 1):
        t = threading.Thread(target=obrero, args=(False,))
        try:
            t.start()
        except RuntimeError:          # no se pudo crear el hilo: se sigue con los que haya
            break
        hilos.append(t)
    obrero(True)
    for t in hilos:
        t.join()
    if errores:
        raise errores[0]

    # Imagen ultra compresible (lisa): el costo fijo por banda ya pesa; un solo flujo.
    if n > 1 and sum(s[3] for s in salida) * 64 < alto * por_fila:
        f.seek(0)
        f.truncate()
        f.write(_png_un_flujo(img, filas_banda))
        return
    escribir_listas()
    adler = 1
    for _, a, largo, _ in salida:
        adler = _adler_combinar(adler, a, largo)
    cola = struct.pack(">I", adler)
    trozo, crc = salida[n - 1][0]
    f.write(b"".join((trozo, cola, struct.pack(">I", zlib.crc32(cola, crc)), _chunk(b"IEND", b""))))


def write_png(img, path):
    """
    Lo mismo que cv2.imwrite(path, img) para un .png: sin perdida, y el
    archivo queda completo y cerrado al retornar. Lo que no sea una imagen
    uint8 de 1, 3 o 4 canales con ruta .png va por cv2.imwrite.
    """
    try:
        ruta = os.fspath(path)
    except TypeError:
        ruta = None
    if not (isinstance(ruta, str) and ruta.lower().endswith(".png")
            and type(img) is np.ndarray and img.dtype == np.uint8 and img.size > 0
            and (img.ndim == 2 or (img.ndim == 3 and img.shape[2] in (1, 3, 4)))):
        cv2.imwrite(path, img)                 # cualquier caso raro: lo resuelve cv2
        return
    try:
        with open(ruta, "wb") as f:
            _escribir(np.ascontiguousarray(img), f)
    except Exception:
        # No se pudo abrir o escribir (o paso algo inesperado): que resuelva cv2, que
        # ante una ruta invalida tampoco lanza excepcion.
        cv2.imwrite(path, img)
    except BaseException:
        try:                                   # interrupcion: no dejar un PNG a medio escribir
            os.remove(ruta)
        except OSError:
            pass
        raise
