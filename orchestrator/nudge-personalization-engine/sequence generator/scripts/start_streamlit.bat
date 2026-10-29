@echo off
cd /d "c:\Users\ASUS\Desktop\Outreach-Project\sequence generator"
call .\venv\Scripts\Activate.ps1
streamlit run app.py --server.port 8502
pause
