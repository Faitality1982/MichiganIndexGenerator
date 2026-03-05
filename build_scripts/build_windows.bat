@echo off
echo Installing dependencies...
pip install pdfplumber python-docx docx2pdf pyinstaller

echo Building Windows executable...
pyinstaller michigan_index.spec --distpath dist --workpath build --noconfirm

echo.
echo Build complete! Executable is in: dist\MichiganIndexGenerator.exe
pause
