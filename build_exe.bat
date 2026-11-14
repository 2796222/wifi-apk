@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  1/3 安装/更新 PyInstaller
echo ============================================
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err

echo ============================================
echo  2/3 打包图形版 netctl-gui.exe
echo ============================================
python -m PyInstaller --noconfirm --clean --onedir --windowed --name netctl-gui netctl_gui.py
if errorlevel 1 goto :err

echo ============================================
echo  3/3 打包命令行版 netctl.exe
echo ============================================
python -m PyInstaller --noconfirm --clean --onedir --console --name netctl netctl_cli.py
if errorlevel 1 goto :err

copy /y netctl.json "dist\netctl-gui\netctl.json" >nul
copy /y netctl.json "dist\netctl\netctl.json" >nul

echo.
echo 打包完成：
echo   图形版：dist\netctl-gui\netctl-gui.exe
echo   命令版：dist\netctl\netctl.exe
echo.
echo 分发时把整个文件夹打包成 zip（exe 不能单独拷走，要带 _internal）。
echo 可以先自检：
echo   dist\netctl\netctl.exe ont
pause
exit /b 0

:err
echo.
echo 打包失败，看上面的报错信息。
pause
exit /b 1
