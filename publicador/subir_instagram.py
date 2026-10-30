"""Sube un clip a Instagram: lo aloja en Firebase Hosting y publica el Reel vía Graph API."""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from firebase_hosting import publicar_video_en_firebase
from subir_clips_meta import publicar_reel_instagram, crear_caption

CARPETA_CLIPS = Path(os.getenv("META_VIDEO_DIR", "videos"))
CARPETA_TEXTOS = Path(os.getenv("META_TEXT_DIR", "textos"))
REGISTRO_RUTA = Path(__file__).with_name("registro_instagram.json")  # Historial de Reels ya publicados.


def _cargar_registro() -> dict:  # Leemos qué clips ya se publicaron en Instagram.
    if not REGISTRO_RUTA.is_file():
        return {}
    try:
        datos = json.loads(REGISTRO_RUTA.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _guardar_registro(registro: dict) -> None:  # Guardamos sin dejar el archivo a medias.
    temporal = REGISTRO_RUTA.with_suffix(".tmp")
    temporal.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(REGISTRO_RUTA)


def clip_ya_publicado(nombre_clip: str, registro: dict) -> bool:  # Evitamos duplicados.
    return bool(registro.get(nombre_clip))


def leer_campo(nombre_clip: str, campo: str) -> str:
    stem = nombre_clip[:-4] if nombre_clip.lower().endswith(".mp4") else nombre_clip
    ruta = CARPETA_TEXTOS / f"{campo}_{stem}.txt"
    return ruta.read_text(encoding="utf-8").strip() if ruta.is_file() else ""


def subir_un_clip(nombre_clip: str, titulo: str = "", descripcion: str = "", hashtags: str = "") -> str:
    """Sube un clip a Instagram. Devuelve el ID del Reel publicado."""
    registro = _cargar_registro()
    if clip_ya_publicado(nombre_clip, registro):
        print(f"{nombre_clip} ya está publicado en Instagram; se omite.")
        return registro[nombre_clip].get("instagram_id", "")
    ruta_video = CARPETA_CLIPS / nombre_clip
    if not ruta_video.is_file():
        raise FileNotFoundError(f"No encuentro el video: {ruta_video}")
    if not titulo:
        titulo = leer_campo(nombre_clip, "titulo")
    if not descripcion:
        descripcion = leer_campo(nombre_clip, "descripcion")
    if not hashtags:
        hashtags = leer_campo(nombre_clip, "hashtags")
    if not titulo or not descripcion:
        raise ValueError(f"Faltan textos para {nombre_clip}. Genera los textos primero.")
    print(f"Subiendo a Firebase Hosting: {nombre_clip}")
    url_publica = publicar_video_en_firebase(ruta_video)
    print(f"URL pública: {url_publica}")
    caption = crear_caption(titulo, descripcion, hashtags)
    print(f"Publicando en Instagram con caption de {len(caption)} caracteres...")
    reel_id = publicar_reel_instagram(url_publica, caption)
    registro[nombre_clip] = {"instagram_id": reel_id, "publicado_en": datetime.now(timezone(timedelta(hours=-5))).isoformat(timespec="seconds")}
    _guardar_registro(registro)
    print(f"Instagram confirmó el Reel. ID: {reel_id}")
    return reel_id


def subir_todos() -> tuple[int, int]:
    """Sube en orden todos los clips pendientes (con textos y sin publicar). Devuelve (subidos, omitidos)."""
    if not CARPETA_CLIPS.is_dir():
        raise FileNotFoundError(f"No encuentro la carpeta de clips: {CARPETA_CLIPS}")
    registro = _cargar_registro()
    videos = sorted(CARPETA_CLIPS.glob("*_clip_*_final.mp4"), key=lambda r: r.name.casefold())
    subidos = 0
    omitidos = 0
    for video in videos:
        nombre = video.name
        if clip_ya_publicado(nombre, registro):
            print(f"{nombre} ya está publicado; se omite.")
            omitidos += 1
            continue
        if not (CARPETA_TEXTOS / f"titulo_{video.stem}.txt").is_file() or not (CARPETA_TEXTOS / f"descripcion_{video.stem}.txt").is_file():
            print(f"{nombre} no tiene textos completos; se omite.")
            omitidos += 1
            continue
        reel_id = subir_un_clip(nombre)
        print(f"Listo. Reel ID: {reel_id}")
        subidos += 1
    print(f"Terminado: {subidos} subido(s), {omitidos} omitido(s).")
    return subidos, omitidos


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publica clips en Instagram como Reels.")
    parser.add_argument("--clip", help="Nombre del archivo MP4 (ej: videoID_clip_0_final.mp4)")
    parser.add_argument("--todos", action="store_true", help="Sube todos los clips pendientes en orden")
    parser.add_argument("--titulo", default="", help="Título (opcional; si falta se lee del .txt)")
    parser.add_argument("--descripcion", default="", help="Descripción (opcional)")
    parser.add_argument("--hashtags", default="", help="Hashtags (opcional)")
    args = parser.parse_args()

    try:
        if args.todos:
            subir_todos()
        else:
            if not args.clip:
                parser.error("Indica --clip o --todos.")
            reel_id = subir_un_clip(args.clip, args.titulo, args.descripcion, args.hashtags)
            print(f"Listo. Reel ID: {reel_id}")
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
