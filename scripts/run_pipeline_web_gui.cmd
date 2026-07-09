@echo off
cd /d "%~dp0.."
"SCI_new\Scripts\python.exe" -u -m pipeline.web_gui --host 127.0.0.1 --port 8765

