pyinstaller.exe -F -w src/windows_main.py
mv "./dist/windows_main.exe" .
rm -rf windows_main.spec
rm -rf build
rm -rf dist
