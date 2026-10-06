"""
Prueba de punta a punta de la actualización, con el ejecutable de verdad:

    python ci/probar_actualizacion.py dist/LaBestia.exe [--oculto]

Arma en una carpeta temporal una "PC" con el ejecutable instalado y una carpeta
de actualizaciones con el mismo ejecutable, retocado para que diga ser una
versión más nueva. Le pide al instalado que se actualice y verifica que quede
reemplazado, que el programa vuelva a abrir y que no queden restos.

No toca nada fuera de esa carpeta temporal: la configuración y los escaneos del
programa se redirigen ahí. Con --oculto las ventanas no se muestran.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import actualizador

ESPERA = 180


def subir_version(ruta):
    """Le suma uno al parche de la versión grabada en el .exe, sin recompilar."""
    with open(ruta, "r+b") as f:
        datos = f.read()
        # VS_FIXEDFILEINFO: firma, versión de la estructura, mayor.menor, parche.compilación
        i = datos.find(b"\xbd\x04\xef\xfe")
        if i < 0:
            raise SystemExit("FALLA: el ejecutable no tiene recurso de versión")
        bajo = int.from_bytes(datos[i + 12:i + 16], "little") + (1 << 16)
        f.seek(i + 12)
        f.write(bajo.to_bytes(4, "little"))


def sha(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def procesos(base):
    """[(pid, ruta del ejecutable)] de los procesos que corren desde `base`."""
    salida = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
         "$_.ExecutablePath.StartsWith($env:PRUEBA_BASE, 'OrdinalIgnoreCase') } | "
         "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)\" }"],
        env=dict(os.environ, PRUEBA_BASE=base), capture_output=True, text=True,
    ).stdout
    return [(int(pid), ruta) for pid, ruta in
            (linea.split("|", 1) for linea in salida.splitlines() if "|" in linea)]


def main():
    exe = os.path.abspath(sys.argv[1])
    base = os.path.realpath(tempfile.mkdtemp(prefix="labestia-prueba-"))
    instalado, publicado = os.path.join(base, "instalado"), os.path.join(base, "publicado")
    for carpeta in (instalado, publicado, os.path.join(base, "escaneos"),
                    os.path.join(base, "appdata", "LaBestia")):
        os.makedirs(carpeta)
    exe_instalado = os.path.join(instalado, actualizador.EXE)
    exe_publicado = os.path.join(publicado, actualizador.EXE)
    exe_nuevo = os.path.join(instalado, actualizador.EXE_NUEVO)
    shutil.copyfile(exe, exe_instalado)
    shutil.copyfile(exe, exe_publicado)
    subir_version(exe_publicado)

    v_instalado = actualizador.version_de_exe(exe_instalado)
    v_publicado = actualizador.version_de_exe(exe_publicado)
    print(f"instalado {v_instalado}, publicado {v_publicado}")
    if v_instalado != actualizador._tupla(actualizador.VERSION) or not v_publicado > v_instalado:
        raise SystemExit("FALLA: las versiones grabadas no son las esperadas")

    with open(os.path.join(base, "appdata", "LaBestia", "config.json"), "w") as f:
        json.dump({"output_dir": os.path.join(base, "escaneos"), "update_dir": publicado}, f)
    env = dict(os.environ, APPDATA=os.path.join(base, "appdata"))
    if "--oculto" in sys.argv:
        env["QT_QPA_PLATFORM"] = "offscreen"

    ok = False
    try:
        codigo = subprocess.run([exe_instalado, "--actualizar-desde", publicado],
                                env=env, cwd=instalado, timeout=ESPERA).returncode
        print(f"--actualizar-desde salió con {codigo}")
        if codigo != 0:
            raise SystemExit("FALLA: el instalado no arrancó la actualización")

        esperado = sha(exe_publicado)
        limite = time.monotonic() + ESPERA
        while True:
            try:
                reemplazado = sha(exe_instalado) == esperado
            except OSError:
                reemplazado = False     # lo están reemplazando justo ahora
            abierto = any(os.path.normcase(ruta) == os.path.normcase(exe_instalado)
                          for _, ruta in procesos(base))
            sin_restos = not os.path.exists(exe_nuevo)
            print(f"  reemplazado={reemplazado} abierto={abierto} sin_restos={sin_restos}")
            if reemplazado and abierto and sin_restos:
                ok = True
                break
            if time.monotonic() > limite:
                break
            time.sleep(2)
    finally:
        for pid, _ in procesos(base):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        time.sleep(2)
        shutil.rmtree(base, ignore_errors=True)

    print("RESULTADO:", "OK" if ok else "FALLA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
