import json
import sys
from pathlib import Path
from yt_dlp import YoutubeDL

if len(sys.argv) < 3:
    raise SystemExit("Uso: info_video.py VIDEO_ID SALIDA_JSON")

video_id = sys.argv[1]
salida = Path(sys.argv[2])
salida.parent.mkdir(parents=True, exist_ok=True)

opciones = {
    "quiet": True,
    "skip_download": True,
    "extract_flat": False,
    "noplaylist": True,
}

try:
    with YoutubeDL(opciones) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    datos = {
        "video_id": video_id,
        "titulo": str(info.get("title") or ""),
        "descripcion": str(info.get("description") or ""),
        "duracion_segundos": int(info.get("duration") or 0),
        "url": str(info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
        "canal": str(info.get("uploader") or info.get("channel") or ""),
        "fecha_subida": str(info.get("upload_date") or ""),
        "miniatura": str(info.get("thumbnail") or ""),
    }
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as error:
    print(error, file=sys.stderr)
    raise
