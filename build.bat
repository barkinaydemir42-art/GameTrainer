@echo off
REM Bu dosyayi kendi Windows bilgisayaninda calistir (kaynak koddan, .exe icinden degil).
REM Once: pip install -r requirements.txt

pyinstaller --onefile --noconsole --name LocalTrainerStudio ^
    --uac-admin ^
    main.py

echo.
echo Bitti. Cikti: dist\LocalTrainerStudio.exe
pause
