import argparse  # Leemos la acción que se escribe después del nombre del programa.
import json  # Abrimos y guardamos el lote pendiente y el historial de Facebook.
import os  # Leemos las carpetas configuradas de forma privada.
from datetime import datetime, time, timedelta, timezone  # Calculamos una hora diaria de Colombia.
from pathlib import Path  # Construimos rutas para videos y archivos del proyecto.

from dotenv import load_dotenv  # Leemos los ajustes guardados en el archivo .env.

load_dotenv(Path(__file__).with_name(".env"))  # Buscamos .env junto a este programa.

from subir_clips_meta import programar_reel_facebook, revisar_ajustes  # Reutilizamos la subida y programación real de Facebook.

CARPETA_VIDEOS = Path(os.getenv("META_VIDEO_DIR", "videos"))  # Aquí están los videos.
CARPETA_TEXTOS = Path(os.getenv("META_TEXT_DIR", "textos"))  # Aquí están títulos, descripciones y hashtags.
ARCHIVO_REGISTRO = Path(__file__).with_name("registro_meta.json")  # Este archivo recuerda qué publicó Facebook.
ARCHIVO_REGISTRO_YOUTUBE = Path(__file__).with_name("registro_youtube.json")  # Fechas que YouTube ya reservó, para no repetir día.
ARCHIVO_LOTE = Path(__file__).with_name("lote_meta_pendiente.json")  # Este archivo conserva el lote si el proceso se interrumpe.
ARCHIVO_RESUMEN = Path(__file__).with_name("lote_meta_pendiente.txt")  # Este resumen permite revisar los clips seleccionados.
ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))  # Colombia usa UTC-5 todo el año.
HORA_PREFERIDA = time(hour=19, minute=0)  # Programamos cada Reel para las siete de la noche.


def cargar_json(archivo: Path, inicial: dict | None = None) -> dict:  # Leemos un archivo JSON o empezamos con un diccionario vacío.
    if not archivo.exists():  # Miramos si el archivo todavía no existe.
        return inicial if inicial is not None else {}  # Devolvemos la forma vacía que necesita quien llamó.
    try:  # Intentamos convertir el texto del archivo en datos.
        datos = json.loads(archivo.read_text(encoding="utf-8"))  # Leemos el contenido sin perder tildes.
    except json.JSONDecodeError as error:  # Detectamos un archivo con formato JSON incorrecto.
        raise RuntimeError(f"{archivo.name} está dañado; no sigo para evitar duplicados.") from error  # Paramos antes de arriesgar el historial.
    if not isinstance(datos, dict):  # Comprobamos que el archivo tenga un objeto en su parte principal.
        raise RuntimeError(f"{archivo.name} debe contener un objeto JSON.")  # Indicamos el formato necesario.
    return datos  # Entregamos los datos leídos.


def guardar_json(archivo: Path, datos: dict) -> None:  # Guardamos un JSON de forma que no quede escrito a medias.
    temporal = archivo.with_suffix(archivo.suffix + ".tmp")  # Preparamos un archivo temporal al lado del original.
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")  # Escribimos datos con tildes legibles.
    temporal.replace(archivo)  # Reemplazamos el original solo después de terminar la escritura.


def clip_ya_programado(estado: dict) -> bool:  # Revisamos si Facebook ya publicó o programó este clip.
    return bool(estado.get("facebook_id") or estado.get("facebook_scheduled_at") or estado.get("facebook_schedule_attempt_id"))  # Evitamos repetir clips o intentos inciertos.


def caption_de(titulo: str, descripcion: str, hashtags: str) -> str:  # Juntamos el texto que acompañará al Reel.
    return "\n\n".join(parte.strip() for parte in (titulo, descripcion, hashtags) if parte.strip())  # Separamos título, descripción y etiquetas.


def _a_hora_colombia(valor: str) -> datetime | None:  # Convertimos un texto de fecha guardado a la hora de Colombia.
    try:  # Intentamos entender la fecha tal como quedó escrita.
        momento = datetime.fromisoformat(valor)  # Leemos el instante guardado en el historial.
    except (TypeError, ValueError):  # Si el texto no es una fecha válida...
        return None  # ...descartamos ese valor sin romper el programa.
    if momento.tzinfo is None:  # Si la fecha no trae zona horaria...
        momento = momento.replace(tzinfo=ZONA_HORARIA_COLOMBIA)  # ...la tratamos como hora colombiana.
    return momento.astimezone(ZONA_HORARIA_COLOMBIA)  # La dejamos siempre en hora de Colombia.


def fechas_ocupadas() -> set:  # Reunimos los días que ya tienen un video agendado.
    ocupadas = set()  # Empezamos con un calendario vacío.
    for estado in cargar_json(ARCHIVO_REGISTRO).values():  # Recorremos el historial de Facebook.
        if not isinstance(estado, dict):  # Saltamos filas que no tengan el formato correcto.
            continue  # Pasamos a la siguiente.
        momento = _a_hora_colombia(estado.get("facebook_scheduled_at", ""))  # La fecha confirmada de ese clip.
        if momento is not None:  # Si el clip quedó programado...
            ocupadas.add(momento.date())  # ...marcamos su día como ocupado.
    if ARCHIVO_REGISTRO_YOUTUBE.is_file():  # Miramos también lo que ya reservó YouTube.
        try:  # Intentamos leer su historial.
            youtube = json.loads(ARCHIVO_REGISTRO_YOUTUBE.read_text(encoding="utf-8"))  # Leemos el archivo.
        except (json.JSONDecodeError, OSError):  # Si está dañado o no se puede leer...
            youtube = {}  # ...no lo tomamos en cuenta.
        for datos in youtube.values():  # Recorremos cada video anotado en YouTube.
            if not isinstance(datos, dict):  # Saltamos filas con formato raro.
                continue  # Seguimos con la siguiente.
            momento = _a_hora_colombia(datos.get("publish_at", ""))  # La fecha de publicación del video.
            if momento is not None:  # Si tiene fecha...
                ocupadas.add(momento.date())  # ...marcamos ese día como ocupado.
    return ocupadas  # Entregamos los días que ya no pueden repetirse.


def siguientes_fechas(cantidad: int) -> list:  # Calculamos los próximos turnos libres a las 7 de la noche.
    ocupadas = fechas_ocupadas()  # Preguntamos qué días ya tienen video (Facebook o YouTube).
    dia = datetime.now(ZONA_HORARIA_COLOMBIA).date() + timedelta(days=1)  # El primer turno posible es mañana.
    fechas = []  # Aquí juntamos los días disponibles.
    while len(fechas) < cantidad:  # Seguimos hasta reunir los turnos pedidos.
        if dia not in ocupadas:  # Si ese día todavía no tiene video...
            fechas.append(datetime.combine(dia, HORA_PREFERIDA, tzinfo=ZONA_HORARIA_COLOMBIA))  # ...reservamos las 7:00 p. m.
        dia += timedelta(days=1)  # Probamos el día siguiente (si estaba ocupado, se salta solo).
    return fechas  # Devolvemos la lista de turnos libres, uno por día.


def leer_clip(video: Path) -> dict | None:  # Buscamos los tres textos que deben acompañar cada MP4.
    rutas = {"titulo": CARPETA_TEXTOS / f"titulo_{video.stem}.txt", "descripcion": CARPETA_TEXTOS / f"descripcion_{video.stem}.txt", "hashtags": CARPETA_TEXTOS / f"hashtags_{video.stem}.txt"}  # Armamos las rutas con el mismo nombre base.
    faltantes = [clave for clave, ruta in rutas.items() if not ruta.is_file()]  # Encontramos los textos que no existen.
    if faltantes:  # Comprobamos si falta algún texto.
        print(f"Salto {video.name}: faltan {', '.join(faltantes)}.")  # Avisamos por qué no elegimos el video.
        return None  # Dejamos ese clip para corregirlo después.
    textos = {clave: ruta.read_text(encoding="utf-8").strip() for clave, ruta in rutas.items()}  # Leemos y limpiamos cada texto.
    vacios = [clave for clave, valor in textos.items() if not valor]  # Detectamos archivos existentes pero vacíos.
    if vacios:  # Comprobamos si hay un texto sin contenido.
        print(f"Salto {video.name}: están vacíos {', '.join(vacios)}.")  # Indicamos cuáles archivos completar.
        return None  # No programamos un Reel incompleto.
    return {"video": video.name, "ruta_video": str(video), **textos}  # Devolvemos el video y sus textos.


def crear_lote(cantidad: int) -> dict:  # Elegimos clips no usados y guardamos el calendario pendiente.
    if not CARPETA_VIDEOS.is_dir():  # Revisamos que exista la carpeta de videos.
        raise FileNotFoundError(f"No encuentro la carpeta de videos: {CARPETA_VIDEOS}")  # Mostramos la ruta que falta.
    if not CARPETA_TEXTOS.is_dir():  # Revisamos que exista la carpeta con los textos.
        raise FileNotFoundError(f"No encuentro la carpeta de textos: {CARPETA_TEXTOS}")  # Mostramos la ruta que falta.
    registro = cargar_json(ARCHIVO_REGISTRO)  # Abrimos el historial para evitar publicar de nuevo.
    seleccionados = []  # Empezamos una lista vacía para los videos listos.
    turnos = siguientes_fechas(cantidad)  # Preparamos los turnos libres (7 p. m., saltando días ocupados).
    videos = sorted(CARPETA_VIDEOS.glob("*.mp4"), key=lambda ruta: ruta.name.casefold())  # Revisamos los MP4 por orden de nombre.
    for video in videos:  # Miramos cada video de la carpeta.
        estado = registro.get(video.name, {})  # Buscamos su historial.
        if not isinstance(estado, dict):  # Comprobamos que ese historial tenga el formato correcto.
            raise RuntimeError(f"El historial de {video.name} no es válido.")  # Paramos para no sobrescribir datos malos.
        if clip_ya_programado(estado):  # Revisamos si el clip ya fue usado o tiene un intento incierto.
            continue  # Pasamos al siguiente video.
        clip = leer_clip(video)  # Buscamos los textos del video.
        if clip is None:  # Revisamos si el video no está listo.
            continue  # Buscamos otro clip que sí tenga sus textos.
        clip["programar_para"] = turnos[len(seleccionados)].isoformat(timespec="minutes")  # Le damos el próximo turno libre a las siete.
        clip["caption"] = caption_de(clip["titulo"], clip["descripcion"], clip["hashtags"])  # Preparamos el texto para Facebook.
        seleccionados.append(clip)  # Añadimos el clip al lote.
        if len(seleccionados) == cantidad:  # Revisamos si ya reunimos la cantidad solicitada.
            break  # Terminamos la búsqueda.
    if not seleccionados:  # Comprobamos si encontramos videos listos.
        print("No hay clips pendientes para Facebook: todos los que hay ya están agendados o no tienen textos completos. No se publicó nada.")  # Decimos con claridad por qué no hay lote.
        raise SystemExit(0)  # Salimos sin error: no es una falla, es que no hay trabajo pendiente.
    lote = {"creado": datetime.now(ZONA_HORARIA_COLOMBIA).isoformat(timespec="minutes"), "cantidad": len(seleccionados), "clips": seleccionados}  # Empacamos selección y fechas.
    guardar_json(ARCHIVO_LOTE, lote)  # Guardamos el lote para poder reanudarlo.
    escribir_resumen(lote)  # Creamos también una vista sencilla para el usuario.
    return lote  # Entregamos el lote listo para programar.


def escribir_resumen(lote: dict) -> None:  # Escribimos una lista que se pueda revisar antes de programar.
    lineas = ["REELS QUE SE PROGRAMARÁN EN FACEBOOK", "", "Instagram queda fuera de este programa; puedes publicarlo por separado.", ""]  # Aclaramos qué hará el lote.
    for numero, clip in enumerate(lote.get("clips", []), start=1):  # Recorremos los videos guardados.
        fecha = datetime.fromisoformat(clip["programar_para"]).strftime("%Y-%m-%d %I:%M %p")  # Mostramos la fecha de forma familiar.
        lineas.extend([f"{numero}. {clip['video']}", f"   Facebook: {fecha} (hora de Colombia)", f"   Archivo: {clip['ruta_video']}", "   Texto:", clip["caption"], ""])  # Añadimos datos y texto del Reel.
    ARCHIVO_RESUMEN.write_text("\n".join(lineas), encoding="utf-8")  # Guardamos el resumen en un archivo de texto.


def corregir_fechas_vencidas(lote: dict) -> bool:  # Reacomodamos el lote si una o más fechas ya pasaron.
    clips = lote.get("clips", [])  # Leemos los clips que todavía no se han resuelto.
    ahora = datetime.now(ZONA_HORARIA_COLOMBIA)  # Consultamos la hora local actual.

    def _a_aware(dt: datetime) -> datetime:  # Convertimos a hora de Colombia si viene sin zona.
        if dt.tzinfo is None:  # Si la fecha no trae zona horaria...
            return dt.replace(tzinfo=ZONA_HORARIA_COLOMBIA)  # ...la tratamos como hora colombiana.
        return dt  # Si ya trae zona, la dejamos igual.

    vencido = any(_a_aware(datetime.fromisoformat(clip["programar_para"])) <= ahora + timedelta(minutes=10) for clip in clips)  # Buscamos fechas pasadas o demasiado cercanas.
    if not vencido:  # Si todos los horarios todavía sirven...
        return False  # ...no cambiamos nada.
    print("El lote tenía fechas vencidas; muevo los clips pendientes a los próximos días libres, a las 7:00 p. m.")  # Explicamos el ajuste antes de subir.
    nuevas = siguientes_fechas(len(clips))  # Buscamos turnos libres sin chocar con días ya ocupados.
    for clip, turno in zip(clips, nuevas):  # Repartimos los días libres entre los clips pendientes.
        clip["programar_para"] = turno.isoformat(timespec="minutes")  # Ponemos la fecha y hora nuevas.
    guardar_json(ARCHIVO_LOTE, lote)  # Guardamos los nuevos horarios para poder reanudar.
    escribir_resumen(lote)  # Actualizamos la guía que puede revisar el usuario.
    return True  # Indicamos que las fechas fueron cambiadas.


def programar_lote(cantidad: int = 999) -> None:  # Sube los videos directamente a Facebook y agenda uno por día.
    revisar_ajustes()  # Comprobamos que estén configurados la versión de API y el token.
    registro = cargar_json(ARCHIVO_REGISTRO)  # Abrimos el historial de Facebook.
    if ARCHIVO_LOTE.exists():  # Reutilizamos el lote anterior si había quedado a medias.
        lote = cargar_json(ARCHIVO_LOTE)  # Leemos la selección sin cambiar los clips.
        print(f"Voy a continuar el lote guardado en {ARCHIVO_RESUMEN}.")  # Indicamos qué selección se usará.
    else:  # Si no hay lote guardado...
        lote = crear_lote(cantidad)  # ...elegimos automáticamente todos los clip pendientes.
        print(f"Elegí {len(lote['clips'])} clips. Revisa el resumen: {ARCHIVO_RESUMEN}")  # Permitimos revisar la selección.
    clips = lote.get("clips", [])  # Sacamos la lista de videos del paquete.
    if not clips:  # Comprobamos que el lote contenga videos.
        raise RuntimeError("El lote guardado no tiene clips; revisa o cancela el archivo pendiente.")  # Paramos ante un lote vacío.
    for clip in clips:  # Revisamos todos los clips antes de cambiar fechas o subir archivos.
        estado = registro.get(clip["video"], {})  # Buscamos el historial guardado de este video.
        if estado.get("facebook_schedule_attempt_id"):  # Detectamos si una petición anterior pudo llegar a Facebook.
            raise RuntimeError(f"No reintento {clip['video']}: Meta pudo haberlo programado. Revisa Facebook > Contenido > Programadas antes de continuar.")  # Evitamos duplicar una programación incierta.
    corregir_fechas_vencidas(lote)  # Corregimos el calendario vencido antes de iniciar cualquier subida.
    clips = lote.get("clips", [])  # Tomamos de nuevo la lista por si el calendario se acaba de guardar.
    for clip in clips[:]:  # Recorremos una copia para poder quitar clips resueltos de la lista original.
        nombre = clip["video"]  # Guardamos el nombre para identificar el resultado.
        estado = registro.setdefault(nombre, {})  # Abrimos o creamos el historial del clip.
        if not isinstance(estado, dict):  # Revisamos la forma del historial.
            raise RuntimeError(f"El historial de {nombre} no es válido.")  # Paramos para proteger la información.
        if estado.get("facebook_scheduled_at") or estado.get("facebook_id"):  # Evitamos repetir un clip ya confirmado.
            lote["clips"].remove(clip)  # Quitamos del lote un clip que ya consta como publicado.
            guardar_json(ARCHIVO_LOTE, lote)  # Conservamos el lote restante.
            continue  # Seguimos con el siguiente clip.
        if estado.get("facebook_schedule_attempt_id"):  # Buscamos una orden previa cuyo resultado no se pudo confirmar.
            raise RuntimeError(f"No reintento {nombre}: Meta pudo haberlo programado. Revisa Facebook > Contenido > Programadas y avísame antes de continuar.")  # Evitamos crear un duplicado.
        fecha = datetime.fromisoformat(clip["programar_para"])  # Convertimos la fecha guardada en una fecha de Python.
        if fecha.tzinfo is None:  # Si la fecha no trae zona horaria...
            fecha = fecha.replace(tzinfo=ZONA_HORARIA_COLOMBIA)  # ...la tratamos como hora colombiana.
        ruta = Path(clip["ruta_video"])  # Recuperamos la ruta local del MP4.
        print(f"Subiendo {nombre}; fecha propuesta: {clip['programar_para']} (Colombia).")  # Mostramos qué está pasando.

        def guardar_intento(id_video: str) -> None:  # Guardamos el intento antes de pedir a Facebook que lo agende.
            estado["facebook_schedule_attempt_id"] = id_video  # Anotamos el ID que Meta asignó al video.
            estado["facebook_schedule_attempt_at"] = datetime.now(ZONA_HORARIA_COLOMBIA).isoformat(timespec="seconds")  # Anotamos cuándo comenzó la orden final.
            guardar_json(ARCHIVO_REGISTRO, registro)  # Protegemos el historial antes de enviar la petición final.

        try:  # Intentamos subir y programar este único Reel.
            id_video = programar_reel_facebook(ruta, clip["titulo"], clip["caption"], fecha, guardar_intento)  # Enviamos el MP4 a Facebook y pedimos publicarlo en esa fecha.
        except Exception as error:  # Capturamos errores para conservar el lote y poder revisar sin duplicar.
            guardar_json(ARCHIVO_REGISTRO, registro)  # Conservamos cualquier marca de intento que ya se hubiera escrito.
            guardar_json(ARCHIVO_LOTE, lote)  # Mantenemos la lista para resolver después el problema.
            raise RuntimeError(f"Falló {nombre}: {error}. El lote sigue guardado; no vuelvas a lanzarlo sin revisar si Facebook lo dejó en Programadas.") from error  # Mostramos el paso seguro siguiente.
        estado["facebook_id"] = id_video  # Guardamos el ID confirmado por Facebook.
        estado["facebook_scheduled_video_id"] = id_video  # Guardamos el ID también con un nombre explícito.
        estado["facebook_scheduled_at"] = fecha.isoformat(timespec="minutes")  # Anotamos cuándo debe publicarse.
        estado["facebook_status"] = "scheduled"  # Dejamos claro que Facebook confirmó la programación.
        estado["lote_meta_id"] = lote.get("creado", "")  # Relacionamos este clip con su lote.
        estado.pop("facebook_schedule_attempt_id", None)  # Quitamos la marca de intento que ya se resolvió.
        estado.pop("facebook_schedule_attempt_at", None)  # Quitamos la hora provisional del intento.
        guardar_json(ARCHIVO_REGISTRO, registro)  # Escribimos el resultado antes de pasar al siguiente video.
        lote["clips"].remove(clip)  # Quitamos del pendiente el video que quedó programado.
        guardar_json(ARCHIVO_LOTE, lote)  # Guardamos inmediatamente lo que aún falta.
        print(f"Facebook confirmó {nombre} para {fecha.strftime('%Y-%m-%d %H:%M')} (Colombia). ID: {id_video}")  # Mostramos la confirmación recibida.
    ARCHIVO_LOTE.unlink(missing_ok=True)  # Borramos el lote temporal cuando todos quedaron resueltos.
    ARCHIVO_RESUMEN.unlink(missing_ok=True)  # Borramos su resumen temporal.
    print("Lote terminado. Los Reels están programados en Facebook; Instagram se publica por separado.")  # Resumimos el resultado.


def cancelar_lote() -> None:  # Borramos únicamente la selección pendiente, sin tocar los videos ni el historial.
    if not ARCHIVO_LOTE.exists():  # Comprobamos si hay un lote guardado.
        print("No hay un lote pendiente para cancelar.")  # Explicamos que no hay cambios que hacer.
        return  # Terminamos sin tocar nada.
    lote = cargar_json(ARCHIVO_LOTE)  # Leemos los clips que se borrarían del lote temporal.
    registro = cargar_json(ARCHIVO_REGISTRO)  # Revisamos si alguno pudo llegar a Facebook.
    dudosos = [clip["video"] for clip in lote.get("clips", []) if registro.get(clip["video"], {}).get("facebook_schedule_attempt_id") or registro.get(clip["video"], {}).get("facebook_scheduled_at")]  # Protegemos clips con programación confirmada o incierta.
    if dudosos:  # Comprobamos si cancelar podría ocultar una programación existente.
        raise RuntimeError(f"No borro este lote porque hay clips con programación confirmada o incierta: {', '.join(dudosos)}. Revisa Facebook > Contenido > Programadas.")  # Pedimos reconciliar antes de eliminar.
    if input("Escribe CANCELAR para borrar solo el lote pendiente: ").strip() != "CANCELAR":  # Pedimos confirmación exacta.
        print("No cancelé el lote; sigue guardado.")  # Conservamos la selección.
        return  # Salimos sin borrar archivos.
    ARCHIVO_LOTE.unlink(missing_ok=True)  # Eliminamos la lista de trabajo.
    ARCHIVO_RESUMEN.unlink(missing_ok=True)  # Eliminamos su resumen.
    print("Lote cancelado. El historial de publicaciones permanece intacto.")  # Aclaramos qué se eliminó.

def recrear_lote(cantidad: int = 5) -> None:  # Reemplazamos un lote no enviado por uno nuevo con fechas actualizadas.
    lote_anterior = cargar_json(ARCHIVO_LOTE) if ARCHIVO_LOTE.exists() else {"clips": []}  # Leemos el lote viejo si lo hay.
    registro = cargar_json(ARCHIVO_REGISTRO)  # Revisamos el historial antes de reemplazarlo.
    dudosos = [clip["video"] for clip in lote_anterior.get("clips", []) if registro.get(clip["video"], {}).get("facebook_schedule_attempt_id") or registro.get(clip["video"], {}).get("facebook_scheduled_at")]  # Buscamos intentos inciertos o programaciones ya confirmadas.
    if dudosos:  # Revisamos si hay publicaciones cuya situación falta confirmar.
        raise RuntimeError(f"No reemplazo el lote porque Facebook pudo aceptar estos clips: {', '.join(dudosos)}. Revisa Contenido > Programadas primero.")  # Evitamos perder un registro necesario.
    if ARCHIVO_LOTE.exists():  # Preguntamos antes de reemplazar una selección existente.
        respuesta = input("Escribe RECREAR para reemplazar el lote pendiente por una selección nueva: ").strip()  # Exigimos una confirmación clara.
        if respuesta != "RECREAR":  # Comprobamos que el usuario confirmó el reemplazo.
            print("No reemplacé el lote; sigue guardado sin cambios.")  # Dejamos intacta la selección anterior.
            return  # Terminamos sin crear otra.
    lote_nuevo = crear_lote(cantidad)  # Elegimos clips que no consten como publicados y ponemos fechas nuevas.
    print(f"Lote nuevo preparado con {len(lote_nuevo['clips'])} clip(s): {ARCHIVO_RESUMEN}")  # Mostramos dónde revisar la nueva selección.
    print("Todavía no se ha subido ningún video; usa 'programar' cuando el token de Meta esté vigente.")  # Separamos preparar del acto de subir.


def main() -> None:  # Conectamos los comandos que puede escribir el usuario.
    parser = argparse.ArgumentParser(description="Programa automáticamente un lote diario de Reels en Facebook.")  # Ponemos una explicación en la ayuda.
    acciones = parser.add_subparsers(dest="accion", required=True)  # Permitimos elegir programar, preparar o cancelar.
    programar = acciones.add_parser("programar", help="sube y programa los clips pendientes en Facebook")  # Creamos el comando que hace el trabajo real.
    programar.add_argument("--cantidad", type=int, default=999, help="cuántos clips programar si no hay lote guardado (por defecto: todos)")  # Permitimos cambiar el tamaño si hace falta.
    preparar = acciones.add_parser("preparar", help="prepara y muestra el lote sin subir videos")  # Dejamos una vista previa opcional.
    preparar.add_argument("--cantidad", type=int, default=5, help="cantidad de clips de la vista previa")  # Permitimos cambiar el tamaño de la vista previa.
    acciones.add_parser("cancelar", help="descarta el lote pendiente sin cambiar el historial")  # Dejamos cancelar una selección guardada.
    recrear = acciones.add_parser("recrear", help="reemplaza un lote no enviado y propone fechas nuevas")  # Agregamos la opción segura para rehacer el lote.
    recrear.add_argument("--cantidad", type=int, default=5, help="cantidad de clips para el lote nuevo")  # Permitimos escoger cuántos clips tendrá.
    argumentos = parser.parse_args()  # Leemos el comando escrito en la terminal.
    if argumentos.accion == "programar":  # Revisamos si se pidió subir y agendar el lote.
        programar_lote(argumentos.cantidad)  # Ejecutamos la programación de Facebook.
    elif argumentos.accion == "preparar":  # Revisamos si se pidió solo revisar la selección.
        if argumentos.cantidad < 1:  # Comprobamos que la cantidad tenga sentido.
            parser.error("--cantidad debe ser al menos 1.")  # Explicamos el error de cantidad.
        if ARCHIVO_LOTE.exists():  # Evitamos reemplazar un lote existente.
            print(f"Ya hay un lote guardado; revísalo en {ARCHIVO_RESUMEN} o usa programar/cancelar.")  # Indicamos cómo continuar.
        else:  # Si no hay lote guardado...
            lote = crear_lote(argumentos.cantidad)  # ...lo creamos para revisión sin subir nada.
            print(f"Vista previa lista: {ARCHIVO_RESUMEN}. Todavía no se subió ningún video.")  # Indicamos que solo fue una vista previa.
    elif argumentos.accion == "recrear":  # Revisamos si se pidió reemplazar el lote que quedó pendiente.
        if argumentos.cantidad < 1:  # Comprobamos que la cantidad tenga sentido.
            parser.error("--cantidad debe ser al menos 1.")  # Explicamos el error de cantidad.
        recrear_lote(argumentos.cantidad)  # Creamos una nueva selección sin subir nada.
    else:  # Si no eligió programar ni preparar, pidió cancelar.
        cancelar_lote()  # Borramos el lote solo si confirma.


if __name__ == "__main__":  # Detectamos que el programa fue ejecutado desde la terminal.
    main()  # Empezamos con la acción seleccionada.
