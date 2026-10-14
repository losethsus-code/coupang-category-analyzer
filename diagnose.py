"""로컬 실행 진단: 외부 쇼핑몰 요청은 실행하지 않음."""
import importlib.util
import os
import socket
import sys
from pathlib import Path
from urllib.request import urlopen

root=Path(__file__).resolve().parent
print('=== Coupang Sourcing Explorer v0.4 Local Diagnosis ===')
print('Python:',sys.version.split()[0]);print('Executable:',sys.executable)
print('App folder:',root)
print('Files:')
for fname in ('app.py','core.py','search_1p.py','launcher.ps1','requirements.txt'):
    print(' ',fname, 'OK' if (root/fname).is_file() else 'MISSING')
print('Modules:')
for module in ('streamlit','pandas','openpyxl'):
    print(' ',module,'OK' if importlib.util.find_spec(module) else 'MISSING')
print('DB exists:',(root/'app_data'/'sourcing.db').exists())
print('Port 8789:')
try:
    with socket.create_connection(('127.0.0.1',8789),timeout=2):
        print('  TCP OPEN')
        try:
            with urlopen('http://127.0.0.1:8789/_stcore/health',timeout=3) as r:
                print('  Streamlit health:',r.status)
        except Exception as e: print('  Health failed:',str(e)[:240])
except Exception as e:
    print('  Server not listening:',str(e)[:240])
print('No Coupang requests were made by this diagnostic.')
