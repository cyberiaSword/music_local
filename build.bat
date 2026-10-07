@echo off
echo ========================================
echo  Сборка YT Music Local
echo ========================================

call venv312\Scripts\activate.bat

echo.
echo [1/3] Очистка старых сборок...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist

echo.
echo [2/3] Запуск PyInstaller...
pyinstaller build.spec --clean --noconfirm

echo.
echo [3/3] Готово!
echo.
echo Результат: dist\YTMusicLocal\YTMusicLocal.exe
echo.
pause