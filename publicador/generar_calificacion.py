"""Genera solo la calificación (1-10) para clips que ya tienen textos pero no calificación."""
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).with_name(".env"))
conexion = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

CARPETA_CLIPS = Path("videos")
CARPETA_TEXTOS = Path("textos")

for titulo_file in sorted(CARPETA_TEXTOS.glob("titulo_*.txt")):
    stem = titulo_file.stem.replace("titulo_", "")
    calif_file = CARPETA_TEXTOS / f"calificacion_{stem}.txt"
    if calif_file.exists():
        print(f"Ya tiene calificación: {stem}")
        continue
    titulo = titulo_file.read_text(encoding="utf-8").strip()
    try:
        respuesta = conexion.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=(
                "Eres experto en marketing de redes sociales para salud mental. "
                f"Este es el título de un clip de {os.getenv('MARCA_NOMBRE', 'La marca')}: \"{titulo}\". "
                "Del 1 al 10, ¿qué tan relevante/viral es este clip para TikTok, Reels y Shorts? "
                "Responde SOLO con el número, sin texto adicional."
            ),
        )
        calificacion = max(1, min(10, int(respuesta.text.strip())))
        calif_file.write_text(str(calificacion), encoding="utf-8")
        print(f"{stem}: {calificacion}/10")
    except Exception as e:
        print(f"Error con {stem}: {e}")
        calif_file.write_text("5", encoding="utf-8")
