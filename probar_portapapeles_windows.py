# -*- coding: utf-8 -*-
import platform
from hod_controller import HODController

if platform.system() != 'Windows':
    raise SystemExit('Esta prueba es solo para Windows.')

texto = 'DESCARGO_HOD1108_CLIPBOARD_TEST_áéíóú_12345'
print('Probando escritura del portapapeles...')
HODController._set_clipboard(texto)
print('Probando lectura del portapapeles...')
leido = HODController._get_clipboard()
if leido != texto:
    print('ERROR: el texto leído no coincide.')
    print('Esperado:', repr(texto))
    print('Leído   :', repr(leido))
    raise SystemExit(1)
print('OK: portapapeles Windows funcionando correctamente.')
print('Ahora puedes ejecutar INICIAR_WINDOWS.bat.')
