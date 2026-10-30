"""Conecta TikTok con tu cuenta y guarda el token de acceso local.

Se llama desde el panel (botón «Conectar TikTok»). Abre el navegador en
127.0.0.1:8766 y, tras tu autorización, guarda el token en token_tiktok.json
para que subir_clips_tiktok.py pueda publicar los clips.

Necesitas una app en developers.tiktok.com con la Content Posting API
habilitada y sus credenciales (TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET) en
el .env del publicador.
"""

import json
import os
import random
import string
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests  # Esta es la herramienta que habla con TikTok por internet.
from dotenv import load_dotenv  # Nos sirve para leer el archivo secreto .env.

CARPETA = Path(__file__).parent  # Guardamos dónde está este módulo.
load_dotenv(CARPETA / ".env")  # Leemos el .env, sin pisar lo ya cargado.

TOKEN_RUTA = CARPETA / "token_tiktok.json"  # Aquí guardamos el token de acceso.
PUERTO = 8766  # Puerto local donde TikTok manda el código de autorización.
REDIRECT_URI = f"http://127.0.0.1:{PUERTO}/callback"  # Debe estar dado de alta en tu app de TikTok.
TIEMPO_MAXIMO = int(os.getenv("TIKTOK_AUTH_TIMEOUT", "300"))  # Máximo de espera para que autorices (segundos).

_client_key = ""  # Lo leemos del .env en main().
_client_secret = ""  # Lo leemos del .env en main().


class _Captura(BaseHTTPRequestHandler):
    """Servidor local mínimo: espera el código del navegador y se apaga."""

    code = None  # El código de autorización que TikTok nos manda.
    error = None  # Si TikTok contesta con un error, lo anotamos aquí.

    def log_message(self, *args) -> None:  # Ocultamos los ruidos del servidor.
        pass

    def do_GET(self) -> None:
        consulta = parse_qs(urlparse(self.path).query)  # Leemos lo que trae la URL.
        if "code" in consulta:  # Si llegó el código que esperábamos...
            _Captura.code = consulta["code"][0]  # ...lo guardamos.
            html = "<h2>Conectado. Ya puedes cerrar esta pestaña.</h2><p>Vuelve al panel de clips.</p>"
        elif "error" in consulta:  # Si TikTok avisa que algo salió mal...
            _Captura.error = (
                consulta.get("error_description") or consulta.get("error") or ["error desconocido"]
            )[0]
            html = f"<h2>Hubo un problema:</h2><p>{_Captura.error}</p>"
        else:  # Cualquier otra visita no sirve.
            html = "<h2>Falta el código. Cierra y vuelve a intentarlo desde el panel.</h2>"
        self.send_response(200)  # Contestamos con HTTP 200 para que el navegador no se queje.
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
        threading.Thread(target=self.server.shutdown, daemon=True).start()  # Apagamos el servidor.


def canjear_codigo(codigo: str) -> dict:
    """Cambia el código de autorización por un token de acceso de TikTok."""
    respuesta = requests.post(  # Le pedimos a TikTok el token a cambio del código.
        "https://open.tiktokapis.com/v2/oauth/token/",
        data={
            "client_key": _client_key,
            "client_secret": _client_secret,
            "code": codigo,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    cuerpo = respuesta.json() if respuesta.content else {}  # Leemos lo que nos contestó.
    if respuesta.status_code != 200 or "access_token" not in cuerpo:  # Si no hay token...
        mensaje = cuerpo.get("error") or cuerpo.get("message") or "TikTok no devolvió un token."
        raise RuntimeError(f"No pude obtener el token de TikTok: {mensaje}")
    cuerpo["obtenido_en"] = datetime.now().isoformat(timespec="seconds")  # Anotamos cuándo lo sacamos.
    return cuerpo  # Devolvemos el token y sus datos.


def main() -> None:
    global _client_key, _client_secret
    _client_key = (os.getenv("TIKTOK_CLIENT_KEY") or "").strip()  # Sacamos la app del .env.
    _client_secret = (os.getenv("TIKTOK_CLIENT_SECRET") or "").strip()  # Y su secreto.
    if not _client_key or not _client_secret:  # Sin esos dos no hay forma de conectarse.
        raise SystemExit(
            "Faltan TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET en el .env del publicador.\n"
            "Sácalos de developers.tiktok.com → tu app → Content Posting API."
        )

    try:
        servidor = HTTPServer(("127.0.0.1", PUERTO), _Captura)  # Servidor local de una sola visita.
    except OSError as error:
        raise SystemExit(
            f"No pude abrir el puerto {PUERTO}: {error}\n"
            "Puede que haya una autorización de TikTok esperando desde antes. "
            "Cierra esa ventana, espera unos segundos y vuelve a intentarlo."
        )
    estado = "".join(random.choices(string.ascii_letters + string.digits, k=12))  # Clave para no mezclar peticiones.
    alcance = "user.info.basic,video.publish"  # Permisos mínimos para publicar videos.

    url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={_client_key}&scope={alcance}&response_type=code"
        f"&redirect_uri={REDIRECT_URI}&state={estado}"
    )
    print("Abriendo el navegador para autorizar TikTok...")
    webbrowser.open(url)  # Abrimos la página de autorización en el navegador.
    print(f"Si no se abre solo, copia esta URL: {url}")
    print(f"Esperando a que autorices en TikTok (hasta {TIEMPO_MAXIMO} segundos; {REDIRECT_URI})...")

    inicio = time.monotonic()
    try:
        # Esperamos el callback, con tope de tiempo: si no autorizas, esto termina
        # solo para que el panel no se quede «Trabajando» para siempre.
        while time.monotonic() - inicio < TIEMPO_MAXIMO:
            servidor.handle_request()
            if _Captura.code is not None or _Captura.error is not None:
                break
        else:
            raise SystemExit(
                "Se agotó el tiempo esperando la autorización (5 minutos). "
                "Vuelve a pulsar «Conectar TikTok» cuando estés listo."
            )
    except KeyboardInterrupt:  # Si el usuario corta con Ctrl+C...
        raise SystemExit("Cancelado por el usuario.")  # ...salimos sin guardar nada.
    finally:
        servidor.server_close()

    if _Captura.error:  # Si TikTok mandó un error...
        raise SystemExit(f"TikTok devolvió un error: {_Captura.error}")
    if not _Captura.code:  # Si nunca llegó el código...
        raise SystemExit("No llegó el código. Cierra el navegador y vuelve a intentarlo desde el panel.")

    token = canjear_codigo(_Captura.code)  # Cambiamos el código por el token de acceso.
    TOKEN_RUTA.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")  # Lo guardamos en disco.
    print(f"TOKEN_GUARDADO:{TOKEN_RUTA}")  # Avisamos al panel de que ya quedó.


if __name__ == "__main__":
    main()  # Empezamos conectando.