# La bestia

[![Build Windows](https://github.com/germankatz/scanner_driver/actions/workflows/build-windows.yml/badge.svg)](https://github.com/germankatz/scanner_driver/actions/workflows/build-windows.yml)

Aplicación de escritorio para digitalizar documentos en lote con un escáner de
cama plana en Windows. Escanea a la resolución elegida (300 dpi por defecto),
detecta el documento sobre la cama, lo endereza y lo guarda recortado y sin
pérdida, numerando los archivos solo.

Pensada para tandas largas: se escanea con Enter y no hay que tocar el diálogo
del escáner en ningún momento.

## Descarga

El ejecutable no necesita Python ni instalación:

**[Descargar la última versión](https://github.com/germankatz/scanner_driver/releases/latest)**

Requiere Windows y un escáner con driver WIA (los de Windows desde XP en
adelante lo son; TWAIN no está soportado).

Hasta la versión 1.1.1 el programa se llamaba Antigravity Scanner y el
ejecutable `AntigravityScanner.exe`. Es el mismo programa: al actualizar
conserva la carpeta de destino, el prefijo y la calidad que ya estaban
configurados.

## Uso

1. Elegí el escáner en el desplegable de arriba, o dejá **Auto-Detectar**.
2. La carpeta de destino está a la vista arriba. Para cambiarla, o cambiar el
   prefijo, hacé clic en la carpeta o en **Cambiar destino**.
3. Poné el documento en la cama y presioná **Enter** (o el botón de escaneo).

Los archivos se numeran solos como `prefijo1.png`, `prefijo2.png`, etc. Si
borrás uno del medio, el siguiente escaneo rellena ese hueco.

Se guardan en **PNG**, que no tiene pérdida: para documentos con texto chico o
huellas dactilares, JPEG introduce artefactos justo en los bordes de alto
contraste, que es donde está la información.

Debajo de la imagen queda el nombre del archivo, cuánto tardó el escaneo y
cuánto pesa.

### Calidad

La barra de abajo a la izquierda elige la resolución del escaneo: 100, 150,
200, 300, 400 o 600 dpi. Al lado muestra cuánto va a pesar cada archivo,
estimado a partir del último escaneo. Más resolución da más detalle, pero el
archivo pesa más (el doble de dpi son cuatro veces más píxeles) y el escáner
tarda más en recorrer la cama. Se recuerda entre reinicios.

Si el driver del escáner no acepta la resolución elegida, el registro lo avisa
y la captura cae al diálogo nativo de Windows.

### Modo manual

El botón de modo manual abre el diálogo nativo de Windows y te deja controlarlo
a mano. Sirve cuando necesitás una configuración puntual que la app no expone
—escanear desde el alimentador, cambiar el modo de color— sin perder el recorte
automático posterior.

## Configuración

Se guarda en `%APPDATA%\LaBestia\config.json` y se recuerda entre reinicios.
Si ese archivo todavía no existe, se lee el del nombre anterior
(`%APPDATA%\AntigravityScanner\config.json`):

```json
{
  "output_dir": "H:\\ruta\\a\\la\\carpeta",
  "file_prefix": "doc_",
  "scan_dpi": 300
}
```

Si al arrancar el destino no está disponible —una unidad de red caída, por
ejemplo— la app avisa y guarda en una carpeta local temporal, **sin pisar la
configuración**. Cuando la unidad vuelve, sigue escribiendo donde corresponde.

## Qué dice el log

El registro reporta cada paso y arranca escondido; **Registro** (abajo a la
derecha) lo despliega. Con el registro cerrado, lo de rutina no se muestra:
solo cuando hay un aviso o un error aparece al pie, en pocas palabras (por
ejemplo, "El documento toca el borde"), y el detalle queda en el registro. Vale
la pena abrirlo en la primera corrida de cada jornada:

| Mensaje | Significa |
|---|---|
| `Captura directa WIA a 300 dpi: 2550x3500 px.` | Todo bien. La resolución se fijó y el driver la aceptó. |
| `Crudo recibido: 2550x3500 px.` | Tamaño de lo que entregó el escáner, antes de procesar. |
| `Documento detectado (otsu), enderezado y guardado...` | Se encontró el documento y se recortó. Entre paréntesis, la estrategia que funcionó. |
| `AVISO: el crudo salió 1200x1500 px (~150 dpi estimados)...` | La resolución quedó por debajo de lo pedido. El escaneo sirve pero tiene menos detalle del esperado. |
| `Captura directa no disponible (...). Cayendo al diálogo nativo.` | El driver rechazó el control directo. Funciona igual, por el camino viejo. |
| `AVISO: no se detectó el documento con ninguna estrategia...` | Se guardó la cama completa. El documento queda más chico dentro del archivo. |
| `AVISO: el documento toca el borde derecho de la cama...` | El documento llega al límite de lo que ve el escáner. Si ese borde salió cortado, correlo unos milímetros hacia adentro y volvé a escanear. |

## Cuando algo sale mal

**Si la detección falla**, la app conserva el archivo `_raw.bmp` de ese escaneo
en vez de borrarlo. Ese crudo es lo que hace falta para averiguar por qué falló:
no lo borres.

Para analizarlo sin tener que reproducir el error: activá el modo debug (el
botón del bicho, arriba a la derecha). Al lado aparece **Procesar archivo**,
que solo se muestra en ese modo: abrí con él ese `_raw.bmp`. Hace el mismo
recorte que un escaneo pero sobre un archivo que ya está en disco, lo guarda
como un archivo nuevo y escribe un `debug_mask_*.jpg` por
cada estrategia que se intentó, así se ve en cuál se rompió la detección, y un
`debug_4_contour.jpg` con el contorno aproximado en rojo y el recorte final en
verde. El log agrega cuántos de los cuatro lados se pudieron medir sobre el
crudo.

**Si la resolución baja**, mirá si aparece el aviso en el log. Suele indicar que
el driver no aceptó los 300 dpi y hubo que caer al diálogo nativo.

**Si el escáner no aparece** en el desplegable, revisá que Windows lo reconozca
en *Dispositivos e impresoras*. La app solo lista dispositivos WIA de tipo
escáner.

## Cómo funciona por dentro

**Captura.** Se conecta por WIA y fija `XRES`/`YRES` a la resolución elegida por propiedades,
releyéndolas después para confirmar que el driver las aceptó de verdad. El área
de escaneo se recalcula desde el tamaño físico de la cama, porque cambiar la
resolución no siempre reescala el extent y quedarse con el viejo significa
escanear solo un pedazo.

**Marco.** El crudo trae en los bordes el labio del marco del escáner, una
franja clara de punta a punta. Se mide en cada escaneo y se recorta solo eso:
con el porcentaje fijo que se usaba antes, una ficha apoyada cerca del marco
perdía un borde.

**Detección.** Sobre una copia reducida a 800 px de alto (por velocidad) se
prueban cuatro estrategias en cascada, y se usa la primera que da un resultado
plausible:

1. Umbralización de Otsu
2. Otsu invertido, por si el papel cayó en la otra clase
3. Bordes de Canny, que encuentran el canto del papel aunque el contraste de
   brillo contra la tapa sea casi nulo
4. Desvío respecto del fondo de la cama, estimado con la mediana del marco

**Recorte.** El contorno de la copia reducida solo da un rectángulo aproximado:
cada píxel de ahí son unos 5 del crudo, y usarlo directo se comía varios
píxeles de papel o dejaba una cuña de cama. Los cuatro lados se vuelven a medir
sobre el crudo a resolución completa, ajustando una recta al canto del papel en
cada uno. Con eso se endereza el documento y se recorta dejando 2 px de cama
alrededor. Una ficha cortada fuera de escuadra deja ver un poco de cama de un
lado en vez de salir deformada. Si un lado no se puede medir (documento contra
el marco, tapa del mismo tono que el papel) se usa el del contorno aproximado.

**Lectura y guardado.** Leer el crudo y escribir el PNG eran tres cuartos del
tiempo de procesamiento, así que `fast_io.py` los hace por su cuenta: lee el
BMP del escáner directo a memoria y comprime el PNG por bandas en paralelo. El
resultado es el mismo que con OpenCV (la misma imagen leída, un PNG que
decodifica a los mismos píxeles) y cualquier caso fuera de lo común se lo deja
a OpenCV. Con eso, y con no calcular lo que no se usa en los demás pasos, el
procesamiento de un escaneo de cama oficio a 300 dpi pasó de unos 290 ms a
unos 85 ms. `LaBestia.exe --selftest` verifica que `fast_io` dé lo
mismo que OpenCV dentro del ejecutable.

## Desarrollo

```bash
pip install -r requirements.txt
python scanner_app.py
```

Para empaquetar (solo en Windows: PyInstaller no cross-compila):

```bash
pip install pyinstaller
pyinstaller LaBestia.spec
```

Cada push a `main` dispara un build en CI que deja el `.exe` como artifact.
Pushear un tag `v*` además publica un release:

```bash
git tag -a v1.0.1 -m "descripción del cambio" && git push origin v1.0.1
```

### Utilidades de diagnóstico

Scripts sueltos para inspeccionar el escáner, útiles cuando un driver se
comporta distinto a lo esperado:

- `dump_properties.py` — vuelca todas las propiedades WIA del dispositivo
- `wia_interceptor.py` — muestra resolución, origen y modo de color, con los
  valores que cada uno admite
- `spy_wia.py` — compara las propiedades antes y después de usar el diálogo
  nativo, para ver qué toca realmente

## Datos personales

Esta herramienta se usa con documentación que contiene datos personales. Los
escaneos, los crudos `_raw.bmp` y las imágenes de debug están excluidos por
`.gitignore` y no deben subirse al repositorio.
