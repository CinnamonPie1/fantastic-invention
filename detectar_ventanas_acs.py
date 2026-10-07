# -*- coding: utf-8 -*-
import os, sys
if os.name != 'nt':
    print('Este diagnóstico debe ejecutarse en Windows.')
    raise SystemExit(1)
from hod_controller import HODController
print('='*78)
print('VENTANAS VISIBLES DETECTADAS')
print('Busca la ventana donde realmente se ve la sesión 5250.')
print("NO elijas 'IBM i Access Client Solutions' a secas: ese es el lanzador.")
print('='*78)
for i, title in enumerate(HODController.windows_debug_titles(), 1):
    print(f'{i:02d}. {title}')
print('\nCopia o toma captura de esta lista si necesitas ayuda para identificarla.')
input('\nPresiona ENTER para cerrar...')
