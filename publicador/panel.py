import json  # Le pedimos a Python una cajita donde guardar y leer json, que es un texto con datos ordenados.
import os  # Le pedimos a Python la llave que abre cosas ya guardadas, como el archivo secreto .env.
import subprocess  # Le pedimos a Python un mensajero que puede abrir otros programas y escuchar lo que dicen.
import sys  # Le pedimos a Python la dirección donde vive el intérprete, para poder abrir otros archivos .py.
import threading  # Le pedimos a Python un hilo, que es un dibujante que trabaja al mismo tiempo que el jefe.
from datetime import datetime, timedelta, timezone  # Le pedimos a Python el calendario, el reloj y la hora de Colombia.
from pathlib import Path  # Le pedimos a Python una forma ordenada de decir dónde está cada archivo.

from dotenv import load_dotenv  # Le pedimos a Python que lea el archivo .env, donde viven las contraseñas y las carpetas.
from flask import Flask, jsonify, render_template  # Le pedimos a Flask las piezas para hacer una página web y sus botones.

import meta_tokens  # La herramienta que revisa y renueva el permiso de Meta sin que tengas que hacerlo cada vez.

CARPETA_PROYECTO = Path(__file__).parent  # Guardamos dónde está esta misma página, para encontrar los demás archivos del proyecto.
load_dotenv(CARPETA_PROYECTO / ".env")  # Leemos el archivo secreto .env aunque la página se abra desde otra carpeta.

CARPETA_VIDEOS = Path(os.getenv("META_VIDEO_DIR", "videos"))  # Esta es la caja donde el usuario guarda sus videos.
CARPETA_TEXTOS = Path(os.getenv("META_TEXT_DIR", "textos"))  # Esta es la caja donde viven los tres textos de cada video.

ARCHIVO_REGISTRO_YOUTUBE = CARPETA_PROYECTO / "registro_youtube.json"  # Este papelito recuerda qué videos ya se programaron en YouTube.
ARCHIVO_REGISTRO_FACEBOOK = CARPETA_PROYECTO / "registro_meta.json"  # Este papelito recuerda qué videos ya se programaron en Facebook.

ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))  # Colombia siempre está cinco horas atrás del reloj de Greenwich, sin horario de verano.

aplicacion = Flask(__name__)  # Creamos la página web y le ponemos nombre, como un cartel con el nombre del negocio.

TRABAJOS = {}  # Esta cajita guarda los trabajos que están corriendo, cada uno con su nombre y sus últimas palabras.
CERROJO_TRABAJOS = threading.Lock()  # Este candado impide que dos dibujantes toquen la misma cajita al mismo tiempo y la arruinen.

PROGRAMAS = {  # Esta cajita es el menú: cada botón del menú apunta a un programa y a un nombre para el usuario.
    "textos": ([sys.executable, "prueba.py"], "Generando textos con Gemini"),  # Este botón abre prueba.py, que escribe título, descripción y hashtags.
    "youtube": ([sys.executable, "subir_clips_yt.py"], "Subiendo a YouTube"),  # Este botón abre subir_clips_yt.py, que programa los videos en YouTube.
    "facebook": ([sys.executable, "publicar_clips_meta.py", "programar"], "Programando en Facebook"),  # Este botón abre el programa de Facebook para agendar el lote de cinco.
    "token": ([sys.executable, "meta_tokens.py", "renovar"], "Renovando el permiso de Facebook"),  # Este botón pide un token nuevo para que no caduque cada dos meses.
}  # Aquí termina el menú con los cuatro botones de la página.


def leer_json(ruta: Path) -> dict:  # Esta receta abre un archivo json y te devuelve lo que tiene adentro, o una cajita vacía si algo falla.
    if not ruta.exists():  # Primero preguntamos si el archivo existe de verdad en el computador.
        return {}  # Si no existe todavía, devolvemos una cajita vacía para no romper la página.
    try:  # Ahora vamos a intentar leer el archivo, pero preparados por si algo sale mal.
        return json.loads(ruta.read_text(encoding="utf-8"))  # Leemos el texto del archivo y lo convertimos en datos de python.
    except (json.JSONDecodeError, OSError):  # Si el archivo está rayado, dañado o no se puede abrir, atrapamos el problema.
        return {}  # Devolvemos una cajita vacía para que la página siga viva y muestre cero en vez de romperse.


def revisar_token_meta() -> dict:  # Esta receta le pregunta a Meta si nuestro permiso todavía sirve, sin publicar nada.
    try:
        return meta_tokens.renovar_antes_de_vencer()  # Le preguntamos a Meta y, si el token está por vencerse, lo renovamos solos.
    except Exception as error:  # Si algo sale mal al renovar, atrapamos el problema para que la página siga mostrando el tablero.
        return {"estado": "sin_conexion", "detalle": f"No pude revisar el permiso: {error}"}  # Avisamos qué pasó, sin mostrar credenciales.


def estado_de_un_clip(nombre: str) -> dict:  # Esta receta pregunta qué le falta a este video y contesta con su estado.
    sin_extension = Path(nombre).stem  # Quitamos el .mp4 del final, porque los textos se llaman sin esa terminación.
    titulo = (CARPETA_TEXTOS / f"titulo_{sin_extension}.txt").is_file()  # Preguntamos si ya existe el archivo del título.
    descripcion = (CARPETA_TEXTOS / f"descripcion_{sin_extension}.txt").is_file()  # Preguntamos si ya existe el archivo de la descripción.
    hashtags = (CARPETA_TEXTOS / f"hashtags_{sin_extension}.txt").is_file()  # Preguntamos si ya existe el archivo de los hashtags.
    registro_youtube = leer_json(ARCHIVO_REGISTRO_YOUTUBE)  # Abrimos la lista que recuerda qué se subió a YouTube.
    registro_facebook = leer_json(ARCHIVO_REGISTRO_FACEBOOK)  # Abrimos la lista que recuerda qué se subió a Facebook.
    return {  # Armamos una cajita con toda la información de este video.
        "video": nombre,  # Guardamos el nombre del archivo, para que la página lo muestre.
        "tiene_textos": titulo and descripcion and hashtags,  # Guardamos si el video ya tiene sus tres textos.
        "titulo": titulo,  # Guardamos si el título existe, para poner una lucecita verde o roja.
        "descripcion": descripcion,  # Guardamos lo mismo para la descripción.
        "hashtags": hashtags,  # Guardamos lo mismo para los hashtags.
        "youtube": registro_youtube.get(sin_extension),  # Guardamos los datos de YouTube, o nada si no está ahí.
        "facebook": registro_facebook.get(nombre),  # Guardamos los datos de Facebook, o nada si no está ahí.
    }  # Devolvemos la cajita completa para que la página la pinte.


def leer_estado_general() -> dict:  # Esta receta junta todo lo que la página necesita saber para dibujar el tablero.
    if not CARPETA_VIDEOS.is_dir():  # Revisamos que la carpeta de videos exista, porque sin ella no hay nada que hacer.
        return {"error": f"No encuentro la carpeta de videos: {CARPETA_VIDEOS}"}  # Avisamos cuál carpeta falta para corregirla en el .env.
    videos = sorted(CARPETA_VIDEOS.glob("*.mp4"), key=lambda ruta: ruta.name.casefold())  # Buscamos todos los mp4 y los ponemos en orden alfabético.
    clips = [estado_de_un_clip(video.name) for video in videos]  # Le preguntamos a cada video cómo está, uno por uno.
    return {  # Juntamos todo en una sola cajita para mandársela a la página.
        "clips": clips,  # Mandamos la lista con el estado de cada video.
        "total": len(clips),  # Mandamos cuántos videos hay en total.
        "listos": sum(1 for clip in clips if clip["tiene_textos"]),  # Mandamos cuántos ya tienen sus tres textos.
        "en_youtube": sum(1 for clip in clips if clip["youtube"]),  # Mandamos cuántos ya están en YouTube.
        "en_facebook": sum(1 for clip in clips if clip["facebook"]),  # Mandamos cuántos ya están en Facebook.
        "carpeta_videos": str(CARPETA_VIDEOS),  # Mandamos la ruta de los videos para que el usuario la vea y la entienda.
        "carpeta_textos": str(CARPETA_TEXTOS),  # Mandamos la ruta de los textos para lo mismo.
    }  # Devolvemos la cajita grande con todo el tablero.


def registrar_trabajo(clave: str, comando: list, titulo: str) -> None:  # Esta receta arranca un programa largo en segundo plano y guarda lo que va diciendo.
    def dibujante() -> None:  # Aquí empieza el dibujante que trabaja mientras la página sigue respondiendo.
        with CERROJO_TRABAJOS:  # Tomamos el candado para escribir en la cajita de trabajos sin pisar a otro dibujante.
            TRABAJOS[clave] = {"estado": "corriendo", "titulo": titulo, "lineas": []}  # Dejamos el trabajo anotado como en marcha y con su lista de palabras vacía.
        proceso = subprocess.Popen(  # Abrimos el programa de verdad, como si le diéramos play a un video.
            comando,  # Le decimos qué programa queremos abrir.
            cwd=CARPETA_PROYECTO,  # Le decimos que lo abra desde esta carpeta, para que encuentre sus propios archivos.
            stdout=subprocess.PIPE,  # Le decimos que nos preste un tubito por donde contarnos lo que dice.
            stderr=subprocess.STDOUT,  # Le decimos que junte los errores con las frases normales, para no perder nada.
            bufsize=1,  # Le decimos que nos muestre las frases de una en una, para verlas aparecer en vivo.
            text=True,  # Le decimos que nos lo cuente con letras normales y no con números raros.
            encoding="utf-8",  # Le decimos que use las letras con tilde y la eñe, para no mostrarlas rareas.
            errors="replace",  # Si hay una letra que no entiende, la cambiamos por un signo en vez de romper todo.
        )  # Aquí ya estamos esperando a que el programa empiece a hablar.
        for linea in proceso.stdout:  # Leemos cada frase que el programa va soltando, una por una.
            with CERROJO_TRABAJOS:  # Volvemos a tomar el candado para escribir sin pisar a nadie.
                TRABAJOS[clave]["lineas"].append(linea.rstrip())  # Guardamos la frase en la lista, sin el salto de línea final.
                TRABAJOS[clave]["lineas"] = TRABAJOS[clave]["lineas"][-300:]  # Si la lista crece mucho, nos quedamos con las últimas 300 frases para no llenar la memoria.
        codigo = proceso.wait()  # Esperamos a que el programa termine y preguntamos si terminó bien o con error.
        with CERROJO_TRABAJOS:  # Tomamos el candado una última vez para anotar el resultado final.
            TRABAJOS[clave]["estado"] = "termino_ok" if codigo == 0 else "termino_error"  # Si el código es cero, todo bien; si no, hubo un error.
            TRABAJOS[clave]["codigo"] = codigo  # Guardamos el número que nos dice cómo terminó, por si lo necesitamos.

    hilo = threading.Thread(target=dibujante, daemon=True)  # Creamos el dibujante y le decimos que no lo detengamos al cerrar la página.
    hilo.start()  # ¡Suelta! Que empiece a trabajar desde ya.


def estado_del_trabajo(clave: str) -> dict:  # Esta receta le pregunta al dibujante cómo vas y devuelve su respuesta.
    with CERROJO_TRABAJOS:  # Tomamos el candado para leer la cajita sin que otro dibujante la esté moviendo.
        trabajo = TRABAJOS.get(clave)  # Buscamos si existe ese trabajo; puede que nunca se haya iniciado.
    if trabajo is None:  # Si no encontramos el trabajo, es que nadie lo ha pedido todavía.
        return {"existe": False}  # Avisamos que todavía no hay nada corriendo con ese nombre.
    return {"existe": True, **trabajo}  # Si existe, le entregamos a la página toda la información del trabajo, con un existe sí adelante.


aplicacion.config["JSON_AS_ASCII"] = False  # Le decimos a Flask que muestre las tildes y la eñe bien, no con códigos raros.


@aplicacion.route("/")  # Esta línea dice: cuando alguien abra la página principal, haz esto.
def mostrar_panel() -> str:  # Esta es la receta que dibuja la página principal.
    return render_template("panel.html")  # Le entregamos el archivo de texto de la página para que lo convierta en pantalla.


@aplicacion.route("/api/estado")  # Esta línea dice: cuando alguien pregunte cómo van las cosas, haz esto.
def api_estado():  # Esta receta junta el tablero de los videos con la revisión del permiso de Meta.
    informacion = leer_estado_general()  # Primero preguntamos cómo está cada video.
    if "error" in informacion:  # Si ya sabíamos que falta una carpeta, no gastamos internet revisando el permiso.
        return jsonify(informacion), 500  # Devolvemos el error con el código 500, que significa que algo salió mal.
    informacion["token_meta"] = revisar_token_meta()  # Le pegamos al tablero lo que nos dijo Meta sobre nuestro permiso.
    return jsonify(informacion)  # Devolvemos la cajita completa para que la página la pinte.


@aplicacion.route("/api/trabajo/<clave>", methods=["POST"])  # Esta línea dice: cuando alguien apriete un botón de esta página, haz esto.
def api_trabajo(clave: str):  # Esta receta decide qué programa abrir según el botón que se apretó.
    if clave not in PROGRAMAS:  # Revisamos que el nombre del botón sea uno de los que conocemos.
        return jsonify({"error": f"No conozco la acción '{clave}'."}), 400  # Si es un nombre inventado, decimos que no existe y paramos.
    with CERROJO_TRABAJOS:  # Tomamos el candado para mirar si ese trabajo ya está corriendo.
        if TRABAJOS.get(clave, {}).get("estado") == "corriendo":  # Revisamos si el dibujante de esa acción sigue trabajando.
            return jsonify({"error": "Ese trabajo ya está corriendo; espera a que termine."}), 409  # Avisamos que no se puede apretar dos veces, porque rompería el historial.
    comando, titulo = PROGRAMAS[clave]  # Sacamos el programa que hay que abrir y el nombre bonito que verá el usuario.
    registrar_trabajo(clave, comando, titulo)  # Soltamos al dibujante para que empiece a trabajar.
    return jsonify({"iniciado": True, "titulo": titulo})  # Le decimos a la página que ya empezó, sin esperar a que termine.


@aplicacion.route("/api/trabajo/<clave>")  # Esta línea dice: cuando la página pregunte cómo va un trabajo, haz esto.
def api_progreso(clave: str):  # Esta receta le enseña a la página lo último que dijo el dibujante.
    return jsonify(estado_del_trabajo(clave))  # Entregamos el estado del trabajo tal como está.


if __name__ == "__main__":  # Esta línea pregunta: me están abriendo a mí como programa, o me están importando como pieza.
    aplicacion.run(host="127.0.0.1", port=5000, debug=False)  # Si me están abriendo a mí, levanto un servicito en mi propio computador.
