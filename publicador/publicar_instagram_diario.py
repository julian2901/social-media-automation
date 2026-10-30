"""Publica UN Reel pendiente por día en Instagram.

Lo lanza el panel cuando pulsas «Subir video de hoy» (subida manual, no hay
tareas automáticas en el PC). Hace la menor cantidad de trabajo posible:

- Si ya se publicó un Reel HOY -> sale sin hacer nada.
- Si no hay clips pendientes (todo lo publicado) -> sale sin hacer nada.
- Si hay un clip pendiente y hoy aún no se publicó -> sube solo ese clip y lo
  anota en registro_instagram.json (para que no se repita).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from subir_instagram import CARPETA_CLIPS, CARPETA_TEXTOS, _cargar_registro, subir_un_clip

ZONA = timezone(timedelta(hours=-5))  # Colombia, todo el año.


def _pub_fecha(datos) -> datetime | None:
    try:
        momento = datetime.fromisoformat(datos.get("publicado_en", ""))
    except (TypeError, ValueError):
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZONA)
    return momento.astimezone(ZONA)


def main() -> int:
    if not CARPETA_CLIPS.is_dir():
        print(f"No encuentro la carpeta de clips: {CARPETA_CLIPS}")
        return 1
    if not CARPETA_TEXTOS.is_dir():
        print(f"No encuentro la carpeta de textos: {CARPETA_TEXTOS}")
        return 1

    registro = _cargar_registro()
    ahora = datetime.now(ZONA)

    # Protección: si el Reel más reciente es de hoy, ya cumplimos el cupo del día.
    fechas = [_pub_fecha(d) for d in registro.values() if isinstance(d, dict)]
    fechas = [f for f in fechas if f is not None]
    if fechas and max(fechas).date() == ahora.date():
        print("Ya publiqué un Reel hoy; no subo más.")
        return 0

    # Buscamos el primer clip pendiente (con textos) en orden de nombre.
    pendientes = []
    for video in sorted(CARPETA_CLIPS.glob("*_clip_*_final.mp4"), key=lambda r: r.name.casefold()):
        nombre = video.name
        if nombre in registro:
            continue
        mask_meta = [
            (CARPETA_TEXTOS / f"titulo_{video.stem}.txt").is_file(),
            (CARPETA_TEXTOS / f"descripcion_{video.stem}.txt").is_file(),
        ]
        if all(mask_meta):
            pendientes.append(nombre)
    if not pendientes:
        print("No hay clips pendientes con textos para publicar en Instagram.")
        return 0

    elegido = pendientes[0]
    print(f"Publicando el Reel del día: {elegido}")
    reel_id = subir_un_clip(elegido)
    print(f"Reel publicado. ID: {reel_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)