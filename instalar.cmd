@echo off
setlocal
rem Instala La bestia en esta PC, para todos los usuarios. Se corre una sola
rem vez por PC, desde una cuenta que pueda escribir en el Escritorio publico,
rem y tiene que estar en la misma carpeta que LaBestia.exe.
rem
rem El programa queda en C:\LaBestia y no en el Escritorio publico porque ahi
rem los usuarios comunes no pueden escribir, y entonces no podria actualizarse
rem solo. En el escritorio queda un acceso directo, y se borra el ejecutable
rem suelto que hubiera de una instalacion anterior.
rem
rem Sin acentos a proposito: la consola los muestra mal.

set "ORIGEN=%~dp0LaBestia.exe"
set "CARPETA=C:\LaBestia"
set "ESCRITORIO=%PUBLIC%\Desktop"

if not exist "%ORIGEN%" (
    echo No esta LaBestia.exe al lado de este archivo.
    goto :fallo
)

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

powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $a = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ESCRITORIO + '\La bestia.lnk'); $a.TargetPath = $env:CARPETA + '\LaBestia.exe'; $a.WorkingDirectory = $env:CARPETA; $a.Description = 'La bestia'; $a.Save()" 2>nul
if errorlevel 1 goto :sin_acceso
if not exist "%ESCRITORIO%\La bestia.lnk" goto :sin_acceso

rem El ejecutable suelto de la instalacion anterior ya no se usa.
del /q "%ESCRITORIO%\LaBestia.exe" 2>nul
del /q "%ESCRITORIO%\AntigravityScanner.exe" 2>nul

echo.
echo Listo. La bestia quedo instalada en %CARPETA%, con un acceso directo
echo en el escritorio de todos los usuarios.
pause
exit /b 0

:sin_acceso
echo No se pudo crear el acceso directo en %ESCRITORIO%.
echo Hay que correr esto desde una cuenta que pueda escribir ahi.

:fallo
echo.
echo NO se instalo.
pause
exit /b 1
