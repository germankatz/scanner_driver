@echo off
setlocal
rem Instala La bestia en esta PC, para todos los usuarios, de una sola vez:
rem doble clic desde la cuenta de soporte y listo. Tiene que estar en la misma
rem carpeta que LaBestia.exe (puede ser una carpeta de red).
rem
rem   - copia el programa a C:\LaBestia y deja que cualquier usuario de la PC
rem     pueda modificar esa carpeta, para que el programa se actualice solo;
rem   - le saca al ejecutable la marca de "bajado de internet";
rem   - crea el acceso directo "La bestia" en el escritorio de todos;
rem   - borra de ese escritorio el ejecutable suelto de la instalacion anterior.
rem
rem El programa no queda en el Escritorio publico porque ahi los usuarios
rem comunes no pueden escribir, y entonces no podria actualizarse solo.
rem
rem Sin acentos a proposito: la consola los muestra mal.

set "ORIGEN=%~dp0LaBestia.exe"
set "CARPETA=C:\LaBestia"
set "ESCRITORIO=%PUBLIC%\Desktop"

if not exist "%ORIGEN%" (
    echo No esta LaBestia.exe al lado de este archivo.
    goto :fallo
)

rem Hace falta poder escribir en el Escritorio publico. Una cuenta
rem administradora no puede hasta que esto corre con permisos elevados: en ese
rem caso se vuelve a lanzar pidiendolos.
copy /y nul "%ESCRITORIO%\LaBestia.prueba" >nul 2>&1
if errorlevel 1 (
    if "%~1"=="elevado" goto :sin_acceso
    goto :elevar
)
del /q "%ESCRITORIO%\LaBestia.prueba" 2>nul

if not exist "%CARPETA%\" mkdir "%CARPETA%"
if not exist "%CARPETA%\" (
    echo No se pudo crear %CARPETA%.
    goto :fallo
)

rem El grupo Usuarios (S-1-5-32-545) puede modificar la carpeta: asi cualquier
rem usuario de la PC puede actualizar el programa desde adentro.
icacls "%CARPETA%" /grant *S-1-5-32-545:(OI)(CI)M >nul
if errorlevel 1 (
    echo No se pudieron dar los permisos sobre %CARPETA%.
    goto :fallo
)

copy /y "%ORIGEN%" "%CARPETA%\LaBestia.exe" >nul
if errorlevel 1 (
    echo No se pudo copiar el programa a %CARPETA%.
    echo Si esta abierto en esta PC, cerralo y proba de nuevo.
    goto :fallo
)

rem Un archivo bajado con el navegador queda marcado como "de internet", y la
rem marca viaja con la copia: Windows mostraria una advertencia de seguridad
rem cada vez que alguien abre el programa. Aca se le saca.
powershell -NoProfile -Command "Unblock-File -LiteralPath ($env:CARPETA + '\LaBestia.exe')" 2>nul

powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $a = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ESCRITORIO + '\La bestia.lnk'); $a.TargetPath = $env:CARPETA + '\LaBestia.exe'; $a.WorkingDirectory = $env:CARPETA; $a.Description = 'La bestia'; $a.Save()" 2>nul
if errorlevel 1 goto :sin_atajo
if not exist "%ESCRITORIO%\La bestia.lnk" goto :sin_atajo

rem El ejecutable suelto de la instalacion anterior ya no se usa.
del /q "%ESCRITORIO%\LaBestia.exe" 2>nul
del /q "%ESCRITORIO%\AntigravityScanner.exe" 2>nul

echo.
echo Listo. La bestia quedo instalada en %CARPETA%, con un acceso directo
echo en el escritorio de todos los usuarios.
pause
exit /b 0

:elevar
rem Con permisos elevados Windows no ve las unidades de red, asi que los dos
rem archivos se llevan primero a una carpeta de la PC y se corre desde ahi.
set "PASO=%TEMP%\LaBestia-instalar"
if exist "%PASO%\" rd /s /q "%PASO%"
mkdir "%PASO%"
copy /y "%ORIGEN%" "%PASO%\LaBestia.exe" >nul
rem Con type y no con copy: asi esta copia no arrastra la marca de "bajado de
rem internet" y Windows no vuelve a preguntar al lanzarla.
type "%~f0" > "%PASO%\instalar.cmd"
if not exist "%PASO%\LaBestia.exe" goto :sin_paso
if not exist "%PASO%\instalar.cmd" goto :sin_paso
echo Windows va a pedir permiso para instalar: hay que aceptarlo.
powershell -NoProfile -Command "$p = Start-Process -FilePath ($env:PASO + '\instalar.cmd') -ArgumentList 'elevado' -Verb RunAs -Wait -PassThru; exit $p.ExitCode" 2>nul
set "SALIDA=%errorlevel%"
rd /s /q "%PASO%" 2>nul
if "%SALIDA%"=="0" exit /b 0
echo No se acepto el pedido de permisos, o la instalacion fallo.
goto :fallo

:sin_paso
echo No se pudo preparar la instalacion en %PASO%.
goto :fallo

:sin_atajo
echo No se pudo crear el acceso directo en %ESCRITORIO%.
goto :fallo

:sin_acceso
echo No se puede escribir en %ESCRITORIO%.
echo Hay que correr esto desde una cuenta de administrador.

:fallo
echo.
echo NO se instalo.
pause
exit /b 1
