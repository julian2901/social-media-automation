"""Rutas y comandos de las dos herramientas que el panel coordina.

Este módulo no importa nada de FastAPI ni ejecuta procesos: solo describe DÓNDE
está cada cosa. Así se puede leer de un vistazo qué toca el panel y qué no.
"""

import os
import sys
import time
import json as _json
import urllib.parse as _urlparse
import urllib.request as _urllib
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
from pathlib import Path

# Las rutas se pueden sobrescribir en un archivo .env (panel/.env o el de la raíz
# del repositorio). Si no existe python-dotenv, se usan los valores por defecto.
try:
    from dotenv import load_dotenv

    PANEL_DIR = Path(__file__).parent
    load_dotenv(PANEL_DIR.parent / ".env")  # raíz del repositorio
    load_dotenv(PANEL_DIR / ".env")  # carpeta del panel: manda sobre la raíz
except ImportError:  # pragma: no cover - dotenv es opcional
    PANEL_DIR = Path(__file__).parent

RAIZ_REPO = PANEL_DIR.parent


def _ruta_de_entorno(nombre: str, por_defecto: Path) -> Path:
    """Lee una ruta de una variable de entorno o devuelve la de por defecto.

    Sirve para que el mismo código funcione en cualquier equipo sin editarlo: en
    vez de una ruta fija como C:\\Users\\tu-usuario\\..., se toma de .env.
    """
    valor = (os.environ.get(nombre) or "").strip().strip('"').strip("'")
    if not valor:
        return por_defecto
    return Path(os.path.expandvars(os.path.expanduser(valor)))


# Ruta del intérprete dentro de un entorno virtual, según el sistema operativo.
_VENV_BIN = Path("Scripts" if sys.platform == "win32" else "bin")
_VENV_EXE = "python.exe" if sys.platform == "win32" else "python"

# --- Generador de clips (venv con torch/whisperx/mediapipe, ~6 GB) ---
# Es un proyecto aparte y no se versiona aquí por su tamaño; se apunta con
# GENERADOR_DIR en el .env. Por defecto se busca en <repo>/generador.
GENERADOR_DIR = _ruta_de_entorno("GENERADOR_DIR", RAIZ_REPO / "generador")
GENERADOR_PY = _ruta_de_entorno("GENERADOR_PY", GENERADOR_DIR / "venv" / _VENV_BIN / _VENV_EXE)
GENERADOR_SCRIPT = _ruta_de_entorno("GENERADOR_SCRIPT", GENERADOR_DIR / "generador_clips.py")
# El generador escribe aquí su avance (porcentaje + etapa) en cada etapa.
PROGRESO_GENERADOR = GENERADOR_DIR / "progreso_generador.json"

# --- Publicador (venv con requests/google-api, ~50 MB) ---
# Por defecto es la carpeta hermana <repo>/publicador.
PUBLICADOR_DIR = _ruta_de_entorno("PUBLICADOR_DIR", RAIZ_REPO / "publicador")
PUBLICADOR_PY = _ruta_de_entorno("PUBLICADOR_PY", PUBLICADOR_DIR / ".venv" / _VENV_BIN / _VENV_EXE)
TEXTOS_SCRIPT = PUBLICADOR_DIR / "prueba.py"
PUBLICAR_SCRIPT = PUBLICADOR_DIR / "publicar_clips_meta.py"
YOUTUBE_SCRIPT = PUBLICADOR_DIR / "subir_clips_yt.py"
INSTAGRAM_SCRIPT = PUBLICADOR_DIR / "subir_instagram.py"
TIKTOK_SCRIPT = PUBLICADOR_DIR / "subir_clips_tiktok.py"
META_CHECK_SCRIPT = PUBLICADOR_DIR / "subir_clips_meta.py"
AUTH_YOUTUBE_SCRIPT = PUBLICADOR_DIR / "auth_youtube.py"
AUTH_TIKTOK_SCRIPT = PUBLICADOR_DIR / "auth_tiktok.py"

# --- Red de seguridad: tope de tiempo por etapa (segundos) ---
# Si una etapa que depende de un servicio externo se queda colgada, el panel la
# detiene solo y sigue funcionando, en vez de quedarse «Trabajando» para siempre.
# Las etapas que no aparecen aquí (como «generar») no tienen tope: tardan lo que tengan que tardar.
TIEMPO_MAXIMO_ETAPA = {
    "auth_tiktok": 420,   # 7 min: si no autorizas en el navegador, se cancela solo.
    "auth_youtube": 420,  # 7 min para autorizar Google.
    "instagram": 1200,    # 20 min: subida + espera de procesado en Meta.
    "tiktok": 900,        # 15 min: subida y confirmación de TikTok.
    "youtube": 3600,      # 60 min por si suben varios clips pesados.
}

# --- El puente: dos carpetas que conectan las dos herramientas ---
CLIPES_DIR = GENERADOR_DIR / "clips_finales"
TEXTOS_DIR = GENERADOR_DIR / "textos_clips"
MINIATURAS_DIR = GENERADOR_DIR / "miniaturas"
# El generador descarga aquí el audio completo de cada video (MP3 + JSON con
# título y descripción). El panel lo reutiliza para preparar Spotify.
AUDIO_DIR = GENERADOR_DIR / "audio_temporal"

# --- Estado propio del panel (no toca las herramientas) ---
HISTORIAL_JSON = PANEL_DIR / "historial.json"
COLA_JSON = PANEL_DIR / "cola.json"
CALENDARIO_JSON = PANEL_DIR / "calendario.json"
# Paquetes de audio para Spotify: audio, título y descripción listos para
# descargar/subir a mano. No se publica nada desde aquí.
SPOTIFY_DIR = PANEL_DIR / "spotify"

# El registro de clips ya publicados vive en la carpeta del publicador; el panel
# solo lo lee para mostrar el estado, nunca lo escribe (salvo el calendario
# pendiente, que sí administra el propio publicador).
REGISTRO_META = PUBLICADOR_DIR / "registro_meta.json"
REGISTRO_YOUTUBE = PUBLICADOR_DIR / "registro_youtube.json"
LOTE_PENDIENTE = PUBLICADOR_DIR / "lote_meta_pendiente.json"
LOTE_RESUMEN = PUBLICADOR_DIR / "lote_meta_pendiente.txt"

# Credenciales / tokens que el panel solo INSPECTIONA (no secreta, solo existencia).
CREDENCIALES_YOUTUBE = PUBLICADOR_DIR / "credenciales_youtube.json"
TOKEN_YOUTUBE = PUBLICADOR_DIR / "token_credencial.json"
TOKEN_TIKTOK = PUBLICADOR_DIR / "token_tiktok.json"
REGISTRO_TIKTOK = PUBLICADOR_DIR / "registro_tiktok.json"
REGISTRO_INSTAGRAM = PUBLICADOR_DIR / "registro_instagram.json"
# En el escritorio a veces quedó un token suelto; lo miramos también.
TOKEN_YOUTUBE_ALT = PANEL_DIR.parent / "token_credencial.json"
ENV_PUBLICADOR = PUBLICADOR_DIR / ".env"

# Patrón de los clips listos para publicar. El nombre lo pone el generador con
# el ID del video delante justamente para que no se pisen entre corridas.
PATRON_CLIP = f"{CLIPES_DIR}/*_clip_*_final.mp4"


def entorno_publicador() -> dict:
    """Variables de entorno para el publicador: le reorganiza las carpetas del panel."""
    entorno = dict(os.environ)
    entorno["META_VIDEO_DIR"] = str(CLIPES_DIR)
    entorno["META_TEXT_DIR"] = str(TEXTOS_DIR)
    # Sin esto los acentos y emojis del log llegan rotos: Python escribe en
    # cp1252 en Windows por defecto y el panel los lee como UTF-8.
    entorno["PYTHONIOENCODING"] = "utf-8"
    return entorno


def entorno_generador() -> dict:
    """Entorno para el generador: solo codificación, el resto ya está en su .env."""
    entorno = dict(os.environ)
    entorno["PYTHONIOENCODING"] = "utf-8"
    return entorno


def verificar_instalacion() -> list[str]:
    """Devuelve la lista de problemas que impedirían trabajar. Vacía = todo bien."""
    problemas = []
    if not GENERADOR_PY.is_file():
        problemas.append(f"No existe el intérprete del generador: {GENERADOR_PY}")
    if not GENERADOR_SCRIPT.is_file():
        problemas.append(f"No existe el generador: {GENERADOR_SCRIPT}")
    if not PUBLICADOR_PY.is_file():
        problemas.append(f"No existe el intérprete del publicador: {PUBLICADOR_PY}")
    for script in (TEXTOS_SCRIPT, PUBLICAR_SCRIPT, YOUTUBE_SCRIPT, INSTAGRAM_SCRIPT, TIKTOK_SCRIPT, AUTH_TIKTOK_SCRIPT):
        if not script.is_file():
            problemas.append(f"No existe el script: {script}")
    return problemas


def asegurar_carpetas() -> None:
    """Crea las carpetas del puente y del panel si no están. No hace falta configurar nada."""
    CLIPES_DIR.mkdir(parents=True, exist_ok=True)
    TEXTOS_DIR.mkdir(parents=True, exist_ok=True)
    MINIATURAS_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    SPOTIFY_DIR.mkdir(parents=True, exist_ok=True)
    for archivo in (HISTORIAL_JSON, COLA_JSON, CALENDARIO_JSON):
        if not archivo.is_file():
            archivo.write_text("[]", encoding="utf-8")


# --- Utilidades de texto por clip ---
# Los archivos se llaman titulo_{stem}.txt / descripcion_{stem}.txt / hashtags_{stem}.txt
# donde stem es el nombre del MP4 sin extensión (p. ej. videoID_clip_0_final).

CAMPOS_TEXTO = ("titulo", "descripcion", "hashtags")


def ruta_texto(clip: str, campo: str) -> Path:
    """Ruta absoluta del .txt de un campo para un clip dado (nombre de archivo o stem)."""
    if campo not in CAMPOS_TEXTO:
        raise ValueError(f"Campo desconocido: {campo}")
    stem = clip[:-4] if clip.lower().endswith(".mp4") else clip
    return TEXTOS_DIR / f"{campo}_{stem}.txt"


def leer_textos(clip: str) -> dict:
    """Lee los tres textos de un clip. Campos vacíos si no existen todavía."""
    salida = {}
    for campo in CAMPOS_TEXTO:
        ruta = ruta_texto(clip, campo)
        salida[campo] = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
    return salida


def guardar_textos(clip: str, datos: dict) -> None:
    """Guarda título / descripción / hashtags de un clip."""
    TEXTOS_DIR.mkdir(parents=True, exist_ok=True)
    stem = clip[:-4] if clip.lower().endswith(".mp4") else clip
    for campo in CAMPOS_TEXTO:
        valor = str(datos.get(campo) or "").strip()
        (TEXTOS_DIR / f"{campo}_{stem}.txt").write_text(valor, encoding="utf-8")


def clip_tiene_textos(clip: str) -> bool:
    """True si el clip tiene título, descripción y hashtags no vacíos."""
    return all(
        ruta_texto(clip, campo).is_file()
        and ruta_texto(clip, campo).read_text(encoding="utf-8").strip()
        for campo in CAMPOS_TEXTO
    )


def leer_calificacion(clip: str) -> int:
    """Lee la calificación de relevancia (1-10) de un clip. Devuelve 0 si no existe."""
    stem = clip[:-4] if clip.lower().endswith(".mp4") else clip
    ruta = TEXTOS_DIR / f"calificacion_{stem}.txt"
    if not ruta.is_file():
        return 0
    try:
        return max(0, min(10, int(ruta.read_text(encoding="utf-8").strip())))
    except ValueError:
        return 0


def hay_clips_publicables() -> tuple[bool, int, int]:
    """(hay_alguno_con_textos, total_clips, cuantos_con_textos)."""
    clips = sorted(CLIPES_DIR.glob("*_clip_*_final.mp4")) if CLIPES_DIR.is_dir() else []
    con = sum(1 for c in clips if clip_tiene_textos(c.name))
    return con > 0, len(clips), con


def estado_auth() -> dict:
    """Qué plataformas tienen credenciales listas. No imprime secretos, solo estado."""
    env_meta = ""
    if ENV_PUBLICADOR.is_file():
        env_meta = ENV_PUBLICADOR.read_text(encoding="utf-8", errors="replace")

    def _tiene(clave: str) -> bool:
        for linea in env_meta.splitlines():
            if linea.startswith(clave + "=") and linea.split("=", 1)[1].strip():
                return True
        return False

    def _leer(clave: str) -> str:
        for linea in env_meta.splitlines():
            if linea.startswith(clave + "="):
                return linea.split("=", 1)[1].strip()
        return ""

    token_yt = TOKEN_YOUTUBE.is_file() or TOKEN_YOUTUBE_ALT.is_file()

    # Estado de Facebook: verificamos el token en vivo contra Meta (con caché
    # de 5 minutos) para que el aviso de "vencido" aparezca de verdad.
    info_fb = _revisar_token_facebook(_leer("META_PAGE_ACCESS_TOKEN"), _leer("META_GRAPH_API_VERSION"))
    return {
        "facebook": {
            "estado": info_fb["estado"],
            "detalle": info_fb["detalle"],
            "listo": info_fb["listo"],
        },
        "instagram": {
            "estado": "listo" if _tiene("META_INSTAGRAM_USER_ID") else "falta",
            "detalle": "Listo: subes el Reel del día desde el panel con «Subir video de hoy» (uno por día)"
            if _tiene("META_INSTAGRAM_USER_ID")
            else "Falta META_INSTAGRAM_USER_ID en el .env",
            "listo": _tiene("META_INSTAGRAM_USER_ID"),
        },
        "youtube": {
            "estado": "listo" if token_yt else "falta",
            "detalle": "Token OAuth de YouTube presente"
            if token_yt
            else "Ejecuta «Conectar YouTube» para autorizar con tu cuenta de Google",
            "listo": token_yt,
        },
        "tiktok": {
            "estado": "listo" if TOKEN_TIKTOK.is_file() else "falta",
            "detalle": "Token de TikTok guardado (listo para publicar clips)"
            if TOKEN_TIKTOK.is_file()
            else "Conecta TikTok con tu cuenta. Necesita TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET en el .env del publicador (app de developers.tiktok.com) y luego «Conectar TikTok» aquí.",
            "listo": TOKEN_TIKTOK.is_file(),
        },
    }


_CACHE_FB_VENCIMIENTO = {"momento": 0.0, "datos": None}
_TTL_FB_CHECK = 300  # segundos que confiamos en una verificación de Meta.


def _revisar_token_facebook(token: str, version: str) -> dict:
    """Le pregunta a Meta si el token de la página sirve, con caché de 5 minutos."""
    global _CACHE_FB_VENCIMIENTO
    ahora = time.monotonic()
    if _CACHE_FB_VENCIMIENTO["datos"] and ahora - _CACHE_FB_VENCIMIENTO["momento"] < _TTL_FB_CHECK:
        return _CACHE_FB_VENCIMIENTO["datos"]
    if not token:
        resultado = {"estado": "falta", "detalle": "Falta META_PAGE_ACCESS_TOKEN en el .env del publicador. Genera uno en el Graph API Explorer.", "listo": False}
        _CACHE_FB_VENCIMIENTO = {"momento": ahora, "datos": resultado}
        return resultado
    version = version or "v26.0"
    parametros = _urlparse.urlencode({"input_token": token, "access_token": token})
    cuerpo = {}
    try:
        with _urllib.urlopen(f"https://graph.facebook.com/{version}/debug_token?{parametros}", timeout=10) as r:
            cuerpo = _json.loads(r.read().decode("utf-8", errors="replace"))
    except _urllib.HTTPError as error:
        try:
            cuerpo = _json.loads(error.read().decode("utf-8", errors="replace"))
        except Exception:
            cuerpo = {"error": {"message": f"HTTP {error.code}"}}
    except Exception as error:
        resultado = {"estado": "sin_conexion", "detalle": f"No pude verificar con Meta: {error}", "listo": False}
        _CACHE_FB_VENCIMIENTO = {"momento": ahora, "datos": resultado}
        return resultado
    datos = cuerpo.get("data") or {}
    error_meta = (cuerpo.get("error") or {}).get("message") or (datos.get("error") or {}).get("message")
    if not datos.get("is_valid") or error_meta:
        resultado = {"estado": "vencido", "detalle": f"Token de Facebook vencido o inválido: {error_meta or 'Meta no lo acepta.'} Renueva META_PAGE_ACCESS_TOKEN en el .env del publicador.", "listo": False}
        _CACHE_FB_VENCIMIENTO = {"momento": ahora, "datos": resultado}
        return resultado
    expira = datos.get("expires_at")
    if not expira:
        resultado = {"estado": "listo", "detalle": "Token de página válido (sin fecha de vencimiento).", "listo": True}
        _CACHE_FB_VENCIMIENTO = {"momento": ahora, "datos": resultado}
        return resultado
    fecha = _dt.fromtimestamp(expira, tz=_tz.utc).astimezone(_tz(_td(hours=-5)))
    dias = (fecha - _dt.now(_tz(_td(hours=-5)))).days
    resultado = {
        "estado": "listo" if dias > 0 else "vencido",
        "detalle": f"Token de página válido hasta el {fecha.strftime('%d/%m/%Y')} (faltan {dias} días)." if dias > 0 else "Token de Facebook vencido. Genera uno nuevo en el Graph API Explorer y pégalo en META_PAGE_ACCESS_TOKEN del .env.",
        "listo": dias > 0,
    }
    _CACHE_FB_VENCIMIENTO = {"momento": ahora, "datos": resultado}
    return resultado
