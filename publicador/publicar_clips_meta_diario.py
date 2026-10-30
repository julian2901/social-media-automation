import json  # Le damos a Python una herramienta para guardar el registro de publicaciones.
import os  # Le damos a Python una herramienta para leer las carpetas configuradas en .env.
from pathlib import Path  # Le damos a Python una herramienta para recorrer carpetas y formar rutas.

from dotenv import load_dotenv  # Le damos a Python una herramienta para leer las opciones privadas de .env.

load_dotenv(Path(__file__).with_name(".env"))  # Cargamos los ajustes del proyecto incluso si la tarea empieza en otra carpeta.

from firebase_hosting import publicar_video_en_firebase  # Traemos la receta que aloja el video para que Instagram pueda descargarlo.
from subir_clips_meta import publicar_reel_facebook, publicar_reel_instagram, verificar_conexion_meta, crear_caption  # Traemos las recetas que publican y comprueban Meta.

CARPETA_VIDEOS = Path(os.getenv("META_VIDEO_DIR", "videos"))  # Elegimos dónde buscar los videos listos.
CARPETA_TEXTOS = Path(os.getenv("META_TEXT_DIR", "textos"))  # Elegimos dónde buscar los títulos y descripciones.
ARCHIVO_REGISTRO = Path(__file__).with_name("registro_meta.json")  # Guardamos aquí qué clips ya se publicaron en cada red.
ARCHIVO_LOTE_PENDIENTE = Path(__file__).with_name("lote_meta_pendiente.json")  # Revisamos si hay clips apartados para programarlos en Meta Business Suite.


def cargar_registro() -> dict:  # Creamos una receta para recordar las publicaciones anteriores.
    if not ARCHIVO_REGISTRO.exists():  # Revisamos si todavía no existe el cuaderno de publicaciones.
        return {}  # Empezamos con un cuaderno vacío.
    try:  # Intentamos abrir y leer el cuaderno guardado.
        registro = json.loads(ARCHIVO_REGISTRO.read_text(encoding="utf-8"))  # Convertimos el archivo JSON en datos que Python entiende.
    except json.JSONDecodeError as error:  # Detectamos si el cuaderno quedó escrito con un formato dañado.
        raise RuntimeError("registro_meta.json está dañado; no publico para evitar repetir un Reel.") from error  # Paramos para prevenir publicaciones duplicadas.
    if not isinstance(registro, dict):  # Revisamos que el cuaderno tenga la forma esperada.
        raise RuntimeError("registro_meta.json debe guardar una lista organizada por nombre de clip.")  # Explicamos qué problema tiene el archivo.
    return registro  # Devolvemos el cuaderno listo para consultar.


def guardar_registro(registro: dict) -> None:  # Creamos una receta para guardar el resultado de cada publicación.
    archivo_temporal = ARCHIVO_REGISTRO.with_suffix(".tmp")  # Preparamos un archivo de repuesto para no dañar el cuaderno original.
    contenido = json.dumps(registro, ensure_ascii=False, indent=2)  # Convertimos las publicaciones en texto fácil de leer.
    archivo_temporal.write_text(contenido, encoding="utf-8")  # Escribimos primero la copia temporal.
    archivo_temporal.replace(ARCHIVO_REGISTRO)  # Cambiamos la copia por el cuaderno cuando quedó escrita correctamente.


def buscar_siguiente_clip() -> tuple[Path, str, str, str] | None:  # Creamos una receta para elegir un clip que ya tenga sus textos.
    if not CARPETA_VIDEOS.is_dir():  # Revisamos si la carpeta de videos realmente existe.
        raise FileNotFoundError(f"No encuentro la carpeta de videos: {CARPETA_VIDEOS}")  # Avisamos la ruta que está fallando.
    if not CARPETA_TEXTOS.is_dir():  # Revisamos si la carpeta de textos realmente existe.
        raise FileNotFoundError(f"No encuentro la carpeta de textos: {CARPETA_TEXTOS}")  # Avisamos la ruta que está fallando.
    registro = cargar_registro()  # Abrimos el cuaderno para saber qué red ya recibió cada clip.
    clips_del_lote = set()  # Preparamos una lista para no publicar directamente clips que ya se están programando.
    if ARCHIVO_LOTE_PENDIENTE.exists():  # Revisamos si hay un lote manual de Meta todavía sin confirmar.
        try:  # Intentamos leer esa selección temporal.
            lote_pendiente = json.loads(ARCHIVO_LOTE_PENDIENTE.read_text(encoding="utf-8"))  # Convertimos el JSON temporal en datos de Python.
        except json.JSONDecodeError as error:  # Detectamos si el lote temporal quedó dañado.
            raise RuntimeError("lote_meta_pendiente.json está dañado; no publico para evitar duplicados.") from error  # Paramos para proteger los clips apartados.
        clips_del_lote = {clip.get("video") for clip in lote_pendiente.get("clips", []) if isinstance(clip, dict)}  # Guardamos los nombres de los videos del lote.
    videos = sorted(CARPETA_VIDEOS.glob("*.mp4"), key=lambda ruta: ruta.name.casefold())  # Ordenamos los videos por nombre para seguir siempre la misma fila.
    for video in videos:  # Revisamos los videos uno por uno.
        nombre = video.name  # Guardamos el nombre exacto para encontrar sus textos y su registro.
        if nombre in clips_del_lote:  # Revisamos si este clip ya está apartado para programarlo manualmente.
            continue  # No permitimos que la tarea automática lo publique al mismo tiempo.
        resultado_anterior = registro.get(nombre, {})  # Buscamos si ya publicamos este video alguna vez.
        if not isinstance(resultado_anterior, dict):  # Revisamos que la fila del cuaderno tenga el formato esperado.
            raise RuntimeError(f"El registro de {nombre} está dañado; no publico para evitar duplicados.")  # Paramos si el cuaderno no permite comprobar publicaciones previas.
        if resultado_anterior.get("instagram_scheduled_at") or resultado_anterior.get("facebook_scheduled_at"):  # Revisamos si Meta ya tiene una fecha futura para este clip.
            continue  # No publicamos inmediatamente un clip que ya esté programado en alguna red.
        if resultado_anterior.get("instagram_id") and resultado_anterior.get("facebook_id"):  # Miramos si las dos redes ya lo recibieron.
            continue  # Si ambas redes ya lo tienen, pasamos al siguiente clip.
        titulo_ruta = CARPETA_TEXTOS / f"titulo_{video.stem}.txt"  # Buscamos el archivo que guarda el título de este clip.
        descripcion_ruta = CARPETA_TEXTOS / f"descripcion_{video.stem}.txt"  # Buscamos el archivo que guarda su descripción.
        hashtags_ruta = CARPETA_TEXTOS / f"hashtags_{video.stem}.txt"  # Buscamos el archivo que guarda sus etiquetas.
        archivos_texto = (titulo_ruta, descripcion_ruta, hashtags_ruta)  # Ponemos juntos los tres archivos necesarios.
        if not all(ruta.is_file() for ruta in archivos_texto):  # Revisamos que los tres archivos estén en la carpeta.
            print(f"Faltan título, descripción o hashtags para {nombre}; lo dejo pendiente.")  # Avisamos por qué todavía no se publica.
            continue  # Pasamos al siguiente clip que sí tenga todo listo.
        titulo = titulo_ruta.read_text(encoding="utf-8").strip()  # Leemos el título y quitamos espacios sobrantes.
        descripcion = descripcion_ruta.read_text(encoding="utf-8").strip()  # Leemos la descripción y quitamos espacios sobrantes.
        hashtags = hashtags_ruta.read_text(encoding="utf-8").strip()  # Leemos las etiquetas y quitamos espacios sobrantes.
        if not titulo or not descripcion or not hashtags:  # Revisamos que ningún texto esté vacío.
            print(f"Hay un texto vacío para {nombre}; lo dejo pendiente.")  # Avisamos que el clip necesita completar su texto.
            continue  # Evitamos publicar con contenido incompleto.
        return video, titulo, descripcion, hashtags  # Entregamos el primer clip que está listo para publicar.
    return None  # Decimos que hoy no encontramos otro clip completo que falte por publicar.


def publicar_un_clip() -> None:  # Creamos la acción diaria que publica como máximo un video.
    clip_listo = buscar_siguiente_clip()  # Buscamos el primer clip que tenga todo y todavía esté pendiente.
    if clip_listo is None:  # Revisamos si encontramos un video listo para hoy.
        print("No hay clips con textos completos pendientes; hoy no se publica nada.")  # Confirmamos que la tarea terminó sin publicar.
        return  # Cerramos la tarea de hoy sin llamar a Meta.
    video, titulo, descripcion, hashtags = clip_listo  # Separamos el video y sus textos para usarlos.
    conexion = verificar_conexion_meta()  # Confirmamos que el token siga conectado antes de subir cualquier cosa.
    print(f"Conexión correcta con {conexion['pagina']}; preparo {video.name}.")  # Mostramos qué página y clip se procesarán.
    registro = cargar_registro()  # Volvemos a leer el cuaderno antes de guardar los resultados.
    estado = registro.setdefault(video.name, {})  # Creamos una fila para este clip si todavía no existía.
    caption = crear_caption(titulo, descripcion, hashtags)  # Juntamos los tres textos para Instagram.
    if not estado.get("instagram_id"):  # Revisamos si Instagram todavía no recibió este clip.
        url_publica = publicar_video_en_firebase(video)  # Subimos el video a Firebase y obtenemos su enlace HTTPS público.
        identificador_instagram = publicar_reel_instagram(url_publica, caption)  # Publicamos el Reel y guardamos su número.
        estado["instagram_id"] = identificador_instagram  # Anotamos que Instagram ya recibió el clip.
        guardar_registro(registro)  # Guardamos el avance antes de intentar la siguiente red.
        print(f"Instagram publicó {video.name}.")  # Avisamos que Instagram terminó correctamente.
    if not estado.get("facebook_id"):  # Revisamos si Facebook todavía no recibió este clip.
        identificador_facebook = publicar_reel_facebook(video, titulo, caption)  # Subimos el video local y publicamos el Reel de Facebook.
        estado["facebook_id"] = identificador_facebook  # Anotamos que Facebook ya recibió el clip.
        guardar_registro(registro)  # Guardamos el avance para no repetir Facebook mañana.
        print(f"Facebook publicó {video.name}.")  # Avisamos que Facebook terminó correctamente.


if __name__ == "__main__":  # Revisamos si alguien ejecutó el publicador inmediato antiguo directamente.
    print("Este publicador inmediato quedó desactivado para evitar duplicados. Usa publicar_clips_meta.py para preparar el lote.")  # Guiamos al usuario al único flujo Meta que debe ejecutar.
