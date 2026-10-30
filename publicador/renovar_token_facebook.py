"""Renueva el token de Facebook a uno de 60 días usando el intercambio de Meta.

Puedes correrlo de dos formas:

    python renovar_token_facebook.py
        Te pregunta en pantalla el App ID, el App Secret y el token corto de usuario.

    python renovar_token_facebook.py APP_ID APP_SECRET TOKEN_CORTO
        Haces lo mismo pero pasando los tres datos al momento de llamar.

El script guarda en el .env el token nuevo de la página (META_PAGE_ACCESS_TOKEN),
el token largo de usuario (META_SYSTEM_USER_TOKEN) y los datos de la app
(META_APP_ID y META_APP_SECRET), de modo que la próxima vez solo haya que repetir esto.
"""

import os  # Leemos y escribimos variables de entorno.
import sys  # Leemos los argumentos que el usuario pasó al llamar.

import meta_tokens  # Reutilizamos las funciones que ya hablan con Meta.

try:  # Si el usuario pasó los tres datos desde la terminal...
    app_id = sys.argv[1]  # Este es el número de la app.
    app_secret = sys.argv[2]  # Este es el secreto de la app.
    token_corto = sys.argv[3]  # Este es el token corto que generó en Graph API Explorer.
except IndexError:  # Si no los pasó, se los pedimos en pantalla.
    app_id = input("App ID: ").strip()  # Pegamos el número de la app.
    app_secret = input("App Secret: ").strip()  # Pegamos el secreto de la app.
    token_corto = input("Token corto de usuario (EAA...): ").strip()  # Pegamos el token corto.

for clave, valor in (("META_APP_ID", app_id), ("META_APP_SECRET", app_secret), ("META_SYSTEM_USER_TOKEN", token_corto)):  # Guardamos los tres datos en el .env antes de seguir.
    meta_tokens.guardar_valor(clave, valor)
    os.environ[clave] = valor

print("Intercambiando el token corto por uno de 60 días...")
token_largo = meta_tokens.renovar_token_sistema(token_corto)  # Meta nos devuelve el token de 60 días.

print("Buscando el token de tu página...")
token_pagina = meta_tokens.token_de_la_pagina(token_largo)  # Sacamos el de la página con el token largo.

meta_tokens.guardar_token(token_largo, token_pagina)  # Dejamos ambos escritos en el .env.

final = meta_tokens.revisar_token(token_pagina)  # Confirmamos que el token de la página quedó listo.
print("Estado final:", final["estado"])
print(final["detalle"])