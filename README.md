# Antigravity Scanner

[![Build Windows](https://github.com/germankatz/scanner_driver/actions/workflows/build-windows.yml/badge.svg)](https://github.com/germankatz/scanner_driver/actions/workflows/build-windows.yml)

Aplicación de escritorio para digitalizar documentos en lote con un escáner de
cama plana en Windows. Escanea a resolución fija, detecta el documento sobre la
cama, lo endereza por transformación de perspectiva y lo guarda recortado y sin
pérdida, numerando los archivos solo.

Pensada para tandas largas: se escanea con Enter y no hay que tocar el diálogo
del escáner en ningún momento.

## Descarga

El ejecutable no necesita Python ni instalación:

**[Descargar la última versión](https://github.com/germankatz/scanner_driver/releases/latest)**

Requiere Windows y un escáner con driver WIA (los de Windows desde XP en
adelante lo son; TWAIN no está soportado).

## Uso

1. Elegí el escáner en el desplegable de arriba, o dejá **Auto-Detectar**.
2. Configurá la carpeta de destino y el prefijo con **⚙️ Configurar Destino**.
3. Poné el documento en la cama y presioná **Enter** (o el botón de escaneo).

Los archivos se numeran solos como `prefijo1.png`, `prefijo2.png`, etc. Si
borrás uno del medio, el siguiente escaneo rellena ese hueco.

Se guardan en **PNG**, que no tiene pérdida: para documentos con texto chico o
huellas dactilares, JPEG introduce artefactos justo en los bordes de alto
contraste, que es donde está la información.

### Modo manual

El botón de modo manual abre el diálogo nativo de Windows y te deja controlarlo
a mano. Sirve cuando necesitás una configuración puntual que la app no expone
—escanear desde el alimentador, cambiar el modo de color— sin perder el recorte
automático posterior.

## Configuración

Se guarda en `%APPDATA%\AntigravityScanner\config.json` y se recuerda entre
reinicios:

```json
{
  "output_dir": "H:\\ruta\\a\\la\\carpeta",
  "file_prefix": "doc_"
}
```

Si al arrancar el destino no está disponible —una unidad de red caída, por
ejemplo— la app avisa y guarda en una carpeta local temporal, **sin pisar la
configuración**. Cuando la unidad vuelve, sigue escribiendo donde corresponde.

## Qué dice el log

La consola de abajo reporta cada paso. Vale la pena mirarla en la primera
corrida de cada jornada:

| Mensaje | Significa |
|---|---|
| `Captura directa WIA a 300 dpi: 2550x3500 px.` | Todo bien. La resolución se fijó y el driver la aceptó. |
| `Crudo recibido: 2550x3500 px.` | Tamaño de lo que entregó el escáner, antes de procesar. |
| `Documento detectado (otsu), enderezado y guardado...` | Se encontró el documento y se recortó. Entre paréntesis, la estrategia que funcionó. |
| `AVISO: el crudo salió 1200x1500 px (~150 dpi estimados)...` | La resolución quedó por debajo de lo pedido. El escaneo sirve pero tiene menos detalle del esperado. |
| `Captura directa no disponible (...). Cayendo al diálogo nativo.` | El driver rechazó el control directo. Funciona igual, por el camino viejo. |
| `AVISO: no se detectó el documento con ninguna estrategia...` | Se guardó la cama completa. El documento queda más chico dentro del archivo. |

## Cuando algo sale mal

**Si la detección falla**, la app conserva el archivo `_raw.bmp` de ese escaneo
en vez de borrarlo. Ese crudo es lo que hace falta para averiguar por qué falló:
no lo borres.

Para analizarlo sin tener que reproducir el error: activá el botón **🐛** y abrí
ese `_raw.bmp` con **📂 Procesar archivo**. Escribe un `debug_mask_*.jpg` por
cada estrategia que se intentó, así se ve en cuál se rompió la detección.

**Si la resolución baja**, mirá si aparece el aviso en el log. Suele indicar que
el driver no aceptó los 300 dpi y hubo que caer al diálogo nativo.

**Si el escáner no aparece** en el desplegable, revisá que Windows lo reconozca
en *Dispositivos e impresoras*. La app solo lista dispositivos WIA de tipo
escáner.

## Cómo funciona por dentro

**Captura.** Se conecta por WIA y fija `XRES`/`YRES` a 300 dpi por propiedades,
releyéndolas después para confirmar que el driver las aceptó de verdad. El área
de escaneo se recalcula desde el tamaño físico de la cama, porque cambiar la
resolución no siempre reescala el extent y quedarse con el viejo significa
escanear solo un pedazo.

**Detección.** Sobre una copia reducida a 800 px de alto (por velocidad) se
prueban cuatro estrategias en cascada, y se usa la primera que da un resultado
plausible:

1. Umbralización de Otsu
2. Otsu invertido, por si el papel cayó en la otra clase
3. Bordes de Canny, que encuentran el canto del papel aunque el contraste de
   brillo contra la tapa sea casi nulo
4. Desvío respecto del fondo de la cama, estimado con la mediana del marco

**Recorte.** El contorno se escala de vuelta a la resolución original y se
aplica una transformación de perspectiva, así que un documento apoyado torcido
sale derecho.

## Desarrollo

```bash
pip install -r requirements.txt
python scanner_app.py
```

Para empaquetar (solo en Windows: PyInstaller no cross-compila):

```bash
pip install pyinstaller
pyinstaller AntigravityScanner.spec
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
