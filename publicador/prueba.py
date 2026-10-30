"""Genera título, descripción, hashtags y calificación para cada clip con Gemini.

El problema que resuelve este archivo: antes el prompt solo recibía el NOMBRE del
archivo del clip y le decía a Gemini que se basara "solo en ese nombre". Como los
clips de un mismo video se llaman casi igual (``VIDEO_clip_0_final.mp4``,
``VIDEO_clip_1_final.mp4``...), Gemini no tenía con qué diferenciarlos y devolvía
los mismos títulos y descripciones para varios clips.

Ahora el prompt recibe el contenido real del clip: el momento elegido en
``momentos_clave/<video>.json`` y el texto hablado de ese rango, recortado de
``transcripciones/<video>.txt``. También recibe la lista de títulos ya usados para
no repetirlos, y la descripción se pide sin fórmulas fijas.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

MAX_INTENTOS_GEMINI = 10  # Intentos por clip antes de darlo por fallido.
ESPERA_INICIAL_SEGUNDOS = 10  # Pausa del primer reintento.
INCREMENTO_ESPERA_SEGUNDOS = 10  # Cuánto crece cada pausa.
MODELO = "gemini-3.5-flash-lite"
TEMPERATURA = 0.9  # Alta a propósito: queremos redacciones distintas entre clips.
TEXTO_MAXIMO_CARACTERES = 1800  # Tope de transcripción que enviamos a Gemini.
TITULOS_RECORDADOS = 8  # Cuántos títulos ya usados le mostramos en el prompt.

# "[0.23 - 1.69] es pareja a la medida." -> inicio, fin, texto
LINEA_TRANSCRIPCION = re.compile(r"^\[([\d.]+)\s*-\s*([\d.]+)\]\s*(.*)$")
# "4aJiImdC628_clip_3_final" -> índice 3
INDICE_CLIP = re.compile(r"_clip_(\d+)_final$")

_cliente = None


def conexion():
    """Crea el cliente de Gemini la primera vez que hace falta."""
    global _cliente
    if _cliente is None:
        _cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _cliente


def _carpeta_hermana(carpeta_clips: Path, variable: str, nombre: str) -> Path:
    """Carpeta de transcripciones/momentos: por .env o hermana de la de clips."""
    valor = (os.getenv(variable) or "").strip().strip('"').strip("'")
    if valor:
        return Path(os.path.expandvars(os.path.expanduser(valor)))
    return carpeta_clips.parent / nombre


def indice_del_clip(clip: Path) -> int | None:
    """De ``VIDEO_clip_3_final.mp4`` saca 3. Devuelve None si no sigue el patrón."""
    coincide = INDICE_CLIP.search(clip.stem)
    return int(coincide.group(1)) if coincide else None


def cargar_contexto(clip: Path, carpeta_clips: Path) -> dict:
    """Texto hablado dentro del clip y la razón por la que se eligió ese momento.

    Devuelve ``{"momento": str, "texto": str}``; ambos vacíos si no hay
    transcripción. Nunca lanza error: sin contexto el clip se genera igual, pero
    con menos información.
    """
    vacio = {"momento": "", "texto": ""}
    indice = indice_del_clip(clip)
    if indice is None:
        return vacio

    video_id = clip.stem.split("_clip_")[0]
    try:
        momentos_dir = _carpeta_hermana(carpeta_clips, "MOMENTOS_CLAVE_DIR", "momentos_clave")
        transcripciones_dir = _carpeta_hermana(carpeta_clips, "TRANSCRIPCIONES_DIR", "transcripciones")

        momentos = json.loads((momentos_dir / f"{video_id}.json").read_text(encoding="utf-8"))
        if not isinstance(momentos, list) or indice >= len(momentos):
            return vacio
        momento = momentos[indice]
        inicio = float(momento["inicio"])
        fin = float(momento["fin"])

        lineas = []
        for linea in (transcripciones_dir / f"{video_id}.txt").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            coincide = LINEA_TRANSCRIPCION.match(linea.strip())
            if not coincide:
                continue
            desde, hasta = float(coincide.group(1)), float(coincide.group(2))
            texto = coincide.group(3).strip()
            if texto and hasta >= inicio and desde <= fin:  # Solapamiento con el clip.
                lineas.append(texto)

        cuerpo = " ".join(lineas).strip()
        if len(cuerpo) > TEXTO_MAXIMO_CARACTERES:
            cuerpo = cuerpo[:TEXTO_MAXIMO_CARACTERES] + "..."
        return {"momento": str(momento.get("razon") or "").strip(), "texto": cuerpo}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return vacio


def construir_prompt(clip: Path, contexto: dict, titulos_usados: list[str]) -> str:
    """Arma el mensaje para Gemini con el contenido real del clip."""
    marca = os.getenv("MARCA_NOMBRE", "").strip()
    tono = os.getenv("MARCA_TONO", "").strip()
    texto = contexto.get("texto", "")
    razon = contexto.get("momento", "")

    if marca and tono:
        identidad = f"{marca} es una marca {tono}. "
    elif marca:
        identidad = f"{marca} es la marca de este contenido. "
    elif tono:
        identidad = f"Esta marca tiene un tono {tono}. "
    else:
        identidad = "Usa un tono cercano, profesional y educativo. "

    partes = [
        "Eres experto en marketing de salud mental y bienestar emocional. ",
        identidad,
        f"El clip se llama: {clip.name}. ",
    ]
    if razon:
        partes.append(f"Por qué se eligió este momento del video: {razon} ")
    if texto:
        partes.append(f'Lo que se dice realmente en el clip: "{texto}". ')
        partes.append("Usa ese contenido como fuente principal y no inventes datos que no aparezcan ahí. ")
    else:
        partes.append("No hay transcripción disponible: básate solo en el nombre del archivo. ")
    partes.append(
        "Crea un título llamativo y específico al contenido de ESTE clip, una descripción de "
        "máximo 150 palabras, 10 hashtags y una calificación de relevancia del 1 al 10. "
    )
    partes.append(
        "Cada clip debe sonar distinto: no empieces la descripción con 'En ... sabemos', "
        "'En ... creemos' ni con ninguna fórmula fija, y no reutilices el título de otro clip. "
    )
    recientes = titulos_usados[-TITULOS_RECORDADOS:]  # Los últimos de verdad, no un set desordenado.
    if recientes:
        partes.append("No repitas ninguno de estos títulos ya usados: " + " | ".join(recientes) + ". ")
    partes.append(
        "Responde exactamente en cuatro líneas, una por campo:\n"
        "TÍTULO: texto del título\n"
        "DESCRIPCIÓN: texto de la descripción\n"
        "HASHTAGS: #etiqueta1 #etiqueta2\n"
        "CALIFICACION: número del 1 al 10"
    )
    return "".join(partes)


def generar_texto_con_reintentos(clip: Path, contexto: dict = None, titulos_usados: list[str] = None):
    """Pide a Gemini los textos del clip, reintentando si falla o si repite un título."""
    contexto = contexto or {"momento": "", "texto": ""}
    titulos_usados = titulos_usados if titulos_usados is not None else []

    for intento in range(1, MAX_INTENTOS_GEMINI + 1):
        try:
            respuesta = conexion().models.generate_content(
                model=MODELO,
                config=types.GenerateContentConfig(temperature=TEMPERATURA, top_p=0.95),
                contents=construir_prompt(clip, contexto, titulos_usados),
            )
            campos = {}
            for linea in respuesta.text.splitlines():
                if ":" in linea:
                    etiqueta, contenido = linea.split(":", 1)
                    campos[etiqueta.strip().upper()] = contenido.strip()

            titulo = campos.get("TÍTULO", "")
            descripcion = campos.get("DESCRIPCIÓN", "")
            hashtags = campos.get("HASHTAGS", "")
            if not titulo or not descripcion or not hashtags:
                raise ValueError("Gemini devolvió un campo vacío.")
            if any(titulo.casefold() == usado.casefold() for usado in titulos_usados):
                raise ValueError(f"Título repetido: {titulo}")

            try:
                calificacion = int(campos.get("CALIFICACION", "5"))
            except ValueError:
                calificacion = 5
            # Un modelo a veces devuelve 0, 11 o hasta texto: lo dejamos dentro del rango.
            calificacion = max(1, min(10, calificacion))
            return titulo, descripcion, hashtags, calificacion
        except Exception as error:
            print(f"Intento {intento}/{MAX_INTENTOS_GEMINI} falló para {clip.name}: {error}")
            if intento < MAX_INTENTOS_GEMINI:
                espera = ESPERA_INICIAL_SEGUNDOS + (intento - 1) * INCREMENTO_ESPERA_SEGUNDOS
                print(f"Volveré a intentar en {espera} segundos.")
                time.sleep(espera)

    raise RuntimeError(f"Gemini falló después de {MAX_INTENTOS_GEMINI} intentos.")


def titulos_existentes(carpeta_descripcion: Path) -> list[str]:
    """Títulos ya escritos, en su orden original, para no volver a usarlos."""
    salida = []
    vistos = set()
    for archivo in carpeta_descripcion.glob("titulo_*.txt"):
        try:
            titulo = archivo.read_text(encoding="utf-8").strip()
        except OSError:
            continue  # Un archivo ilegible no debe frenar al resto.
        if titulo and titulo.casefold() not in vistos:
            vistos.add(titulo.casefold())
            salida.append(titulo)
    return salida


def generar_textos(carpeta_clips: Path, carpeta_descripcion: Path, forzar: bool = False) -> int:
    """Genera los textos de cada MP4 pendiente. Devuelve cuántos procesó.

    ``forzar=True`` rehace también los clips que ya estaban en registro.txt, para
    corregir textos generados antes de este arreglo.
    """
    carpeta_clips.mkdir(parents=True, exist_ok=True)
    carpeta_descripcion.mkdir(parents=True, exist_ok=True)
    archivo_registro = carpeta_clips / "registro.txt"

    procesados = []
    if archivo_registro.exists() and not forzar:
        procesados = archivo_registro.read_text(encoding="utf-8").splitlines()

    clips = sorted(carpeta_clips.glob("*.mp4"))
    videos_nuevos = clips if forzar else [clip for clip in clips if clip.name not in procesados]

    if not videos_nuevos:
        print("No hay videos nuevos")
        return 0

    usados = titulos_existentes(carpeta_descripcion)
    sin_transcripcion = 0

    for clip in videos_nuevos:
        print("Nuevo video encontrado ", clip.name)
        contexto = cargar_contexto(clip, carpeta_clips)
        if not contexto["texto"]:
            sin_transcripcion += 1
            print("  (sin transcripción para este clip: se usará solo el nombre)")
        try:
            titulo, descripcion, hashtags, calificacion = generar_texto_con_reintentos(
                clip, contexto, usados
            )
            base = clip.stem
            for nombre, contenido in (
                (f"titulo_{base}.txt", titulo),
                (f"descripcion_{base}.txt", descripcion),
                (f"hashtags_{base}.txt", hashtags),
                (f"calificacion_{base}.txt", str(calificacion)),
            ):
                (carpeta_descripcion / nombre).write_text(contenido, encoding="utf-8")
            usados.append(titulo)
            if not forzar:
                with archivo_registro.open("a", encoding="utf-8") as registro:
                    registro.write(clip.name + "\n")
        except Exception as error:
            print("Error al generar la descripcion del clip", clip.name, error)

    if sin_transcripcion:
        print(f"Aviso: {sin_transcripcion} clip(s) sin transcripción; sus textos pueden parecerse a otros.")
    return len(videos_nuevos)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera título, descripción y hashtags para los clips con Gemini.")
    parser.add_argument("--videos", help="carpeta con los MP4")
    parser.add_argument("--textos", help="carpeta donde se guardan los tres .txt")
    parser.add_argument("--forzar", action="store_true", help="rehace los textos de clips ya procesados")
    args = parser.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))

    carpeta_clips = Path(args.videos) if args.videos else Path(os.getenv("META_VIDEO_DIR", "videos"))
    carpeta_descripcion = Path(args.textos) if args.textos else Path(os.getenv("META_TEXT_DIR", "textos"))

    print(f"Clips:  {carpeta_clips}")
    print(f"Textos: {carpeta_descripcion}")
    total = generar_textos(carpeta_clips, carpeta_descripcion, forzar=args.forzar)
    print(f"Listo. {total} clip(s) con textos generados.")
