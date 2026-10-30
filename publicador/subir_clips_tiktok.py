"""Sube un clip a TikTok usando la Content Posting API (Direct Post).

Se llama desde el panel (botón «TikTok» de cada clip).
Flujo: inicia la publicación → sube el MP4 → confirma el estado → historial.
"""

import argparse  # Leemos el nombre del clip que se pide publicar.
import json  # Guardamos el historial en registro_tiktok.json.
import os  # Leemos las carpetas y variables de entorno.
import sys  # Para salir con código de error.
import time  # Para esperar mientras TikTok procesa el video.
from datetime import datetime, timezone
from pathlib import Path

import requests  # La herramienta que habla con TikTok por internet.
from dotenv import load_dotenv  # Lee el archivo secreto .env.

load_dotenv(Path(__file__).with_name(".env"))  # Cargamos el .env sin pisar lo ya cargado.

CARPETA = Path(__file__).parent  # Carpeta de este módulo.
TOKEN_RUTA = CARPETA / "token_tiktok.json"  # Token que deja auth_tiktok.py.
REGISTRO_RUTA = CARPETA / "registro_tiktok.json"  # Historial de clips ya publicados.

CARPETA_CLIPS = Path(os.getenv("META_VIDEO_DIR", "videos"))
CARPETA_TEXTOS = Path(os.getenv("META_TEXT_DIR", "textos"))

API_BASE = "https://open.tiktokapis.com/v2/post/publish"  # Endpoints de la Content Posting API.
PRIVACIDAD = (os.getenv("TIKTOK_PRIVACY_LEVEL") or "SELF_ONLY").strip().upper()  # Privado por defecto.
MAX_ESPERA = 180  # Segundos que esperamos a que TikTok confirme la publicación.


def leer_campo(nombre_clip: str, campo: str) -> str:
    """Lee un campo de texto de un clip (titulo_ / descripcion_ / hashtags_)."""
    stem = nombre_clip[:-4] if nombre_clip.lower().endswith(".mp4") else nombre_clip
    ruta = CARPETA_TEXTOS / f"{campo}_{stem}.txt"
    return ruta.read_text(encoding="utf-8").strip() if ruta.is_file() else ""


def cargar_token() -> dict:
    """Devuelve el token guardado por auth_tiktok.py."""
    if not TOKEN_RUTA.is_file():  # Sin token no hay publicación.
        raise RuntimeError("Primero conecta TikTok desde el panel (sección Credenciales → Conectar TikTok).")
    return json.loads(TOKEN_RUTA.read_text(encoding="utf-8"))


def cliente_key() -> str:
    """La clave de la app en el .env; la pide TikTok en cada llamada."""
    clave = (os.getenv("TIKTOK_CLIENT_KEY") or "").strip()
    if not clave:
        raise RuntimeError("Falta TIKTOK_CLIENT_KEY en el .env del publicador.")
    return clave


def iniciar_publicacion(token: dict, ruta_video: Path, titulo: str) -> dict:
    """Pide a TikTok que prepare la subida y devuelve publish_id + upload_url."""
    tamano = ruta_video.stat().st_size  # Cuánto pesa el MP4, en bytes.
    cuerpo = {
        "source_info": {
            "source": "FILE_UPLOAD",  # Subimos el archivo directamente.
            "video_size": tamano,  # Tamaño total del archivo.
            "chunk_size": tamano,  # Un solo bloque (subida simple).
            "total_chunk_count": 1,
        },
        "post_info": {
            "title": titulo,  # Título + descripción + hashtags.
            "privacy_level": PRIVACIDAD,  # SELF_ONLY por defecto; revisa el .env.
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 0,
        },
    }
    respuesta = requests.post(
        f"{API_BASE}/video/init/",
        params={"client_key": cliente_key()},
        headers={
            "Authorization": f"Bearer {token['access_token']}",  # Token de la cuenta.
            "Content-Type": "application/json; charset=UTF-8",
        },
        json=cuerpo,
        timeout=60,
    )
    cuerpo_r = respuesta.json() if respuesta.content else {}
    error = (cuerpo_r.get("error") or {}).get("message")
    datos = cuerpo_r.get("data") or {}
    if respuesta.status_code != 200 or not datos.get("publish_id"):  # Si TikTok no acepto...
        raise RuntimeError(f"TikTok rechazó iniciar la publicación: {error or respuesta.status_code}")
    return datos  # publish_id + upload_url.


def subir_archivo(ruta_video: Path, url_subida: str) -> None:
    """Sube el MP4 al enlace temporal que TikTok nos dio."""
    print("Subiendo el MP4 a TikTok... (puede tardar un poco)")
    with ruta_video.open("rb") as archivo:
        respuesta = requests.put(url_subida, data=archivo, headers={"Content-Type": "video/mp4"}, timeout=300)
    if respuesta.status_code not in (200, 201, 204):
        raise RuntimeError(f"La subida del video falló: {respuesta.status_code} {respuesta.text[:300]}")


def consultar_estado(token: dict, publish_id: str) -> dict:
    """Pregunta a TikTok en qué punto está la publicación."""
    respuesta = requests.post(
        f"{API_BASE}/status/fetch/",
        params={"client_key": cliente_key()},
        headers={
            "Authorization": f"Bearer {token['access_token']}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={"publish_id": publish_id},
        timeout=30,
    )
    cuerpo = respuesta.json() if respuesta.content else {}
    error = (cuerpo.get("error") or {}).get("message")
    if respuesta.status_code != 200:
        raise RuntimeError(f"TikTok dio un error al verificar: {error or respuesta.status_code}")
    return cuerpo.get("data") or {}


def subir_un_clip(nombre_clip: str, titulo: str = "", descripcion: str = "", hashtags: str = "") -> dict:
    """Publica un clip en TikTok. Devuelve el estado final confirmado."""
    ruta_video = CARPETA_CLIPS / nombre_clip
    if not ruta_video.is_file():
        raise FileNotFoundError(f"No encuentro el video: {ruta_video}")
    if not titulo:
        titulo = leer_campo(nombre_clip, "titulo")
    if not descripcion:
        descripcion = leer_campo(nombre_clip, "descripcion")
    if not hashtags:
        hashtags = leer_campo(nombre_clip, "hashtags")
    if not titulo:
        raise ValueError(f"Faltan textos de {nombre_clip}. Genera los textos primero.")

    titulo_completo = "\n".join(x for x in (titulo, descripcion, hashtags) if x.strip())
    if len(titulo_completo) > 2200:  # TikTok limita el título a 2200 caracteres.
        titulo_completo = titulo_completo[:2197] + "…"

    token = cargar_token()
    print("Pidiendo a TikTok iniciar la publicación...")
    datos = iniciar_publicacion(token, ruta_video, titulo_completo)
    print(f"Publicación admitida. publish_id={datos['publish_id']}")
    subir_archivo(ruta_video, datos["upload_url"])

    print("Video subido; esperando confirmación de TikTok...")
    inicio = time.monotonic()
    estado = {}
    while time.monotonic() - inicio < MAX_ESPERA:
        estado = consultar_estado(token, datos["publish_id"])
        estado_actual = estado.get("status")
        print(f"Estado: {estado_actual} ({int(time.monotonic() - inicio)} s)")
        if estado_actual == "PUBLISH_COMPLETE":  # Ya quedó publicado.
            break
        if estado_actual == "FAILED":  # TikTok lo rechazó.
            razon = (estado.get("fail_reason") or {}).get("message") or "motivo desconocido"
            raise RuntimeError(f"TikTok no publicó el video: {razon}")
        time.sleep(3)  # Esperamos un poco antes de preguntar otra vez.
    else:  # El while terminó sin confirmación.
        raise RuntimeError("TikTok tardó demasiado en confirmar. El video puede aparecer después en tu cuenta.")

    post_id = estado.get("post_id") or estado.get("postId") or datos["publish_id"]
    registro = {}
    if REGISTRO_RUTA.is_file():  # Cargamos el historial si ya existe.
        try:
            registro = json.loads(REGISTRO_RUTA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            registro = {}
    registro[nombre_clip] = {
        "post_id": post_id,
        "status": "published",
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "privacy_level": PRIVACIDAD,
    }
    REGISTRO_RUTA.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Listo. Publicado en TikTok. ID: {post_id}")
    print(f"Nota: el video quedó como {PRIVACIDAD}. Para público, pon TIKTOK_PRIVACY_LEVEL=PUBLIC en el .env.")
    return estado


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publica un clip en TikTok.")
    parser.add_argument("--clip", required=True, help="Nombre del archivo MP4 (ej: videoID_clip_0_final.mp4)")
    parser.add_argument("--titulo", default="", help="Título (opcional; si falta se lee del .txt)")
    parser.add_argument("--descripcion", default="", help="Descripción (opcional)")
    parser.add_argument("--hashtags", default="", help="Hashtags (opcional)")
    args = parser.parse_args()

    try:
        subir_un_clip(args.clip, args.titulo, args.descripcion, args.hashtags)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)