from google_auth_oauthlib.flow import InstalledAppFlow  # este sirve para la autenticacion, siempre sea excelente que las cookies se actualicen siempre y no tenga uno que siempre iniciar sesion
from googleapiclient.discovery import build  # este para hacer a conexion a la api de youtube
from googleapiclient.http import MediaFileUpload  # este sirve para subir el video
from dotenv import load_dotenv  # para leer las carpetas guardadas en el archivo secreto .env
from pathlib import Path
import argparse  # para que el panel pueda decirnos que carpetas usar
import json
import os  # para leer las carpetas privadas del archivo .env
from datetime import datetime, timedelta, timezone  # Estas herramientas sirven para calcular dias, horas y la zona horaria.
from google.oauth2.credentials import Credentials  # esto es para despues importar las credenciales para no tener que siempre hacer el login de google

CARPETA_PROYECTO = Path(__file__).parent  # Guardamos donde esta este programa, para encontrar sus propios archivos.
load_dotenv(CARPETA_PROYECTO / ".env")  # Leemos el archivo secreto aunque el programa se abra desde otra carpeta.

HORA_PUBLICACION = 19  # Esta es la hora fija de publicacion: las siete de la noche.
ZONA_HORARIA = timezone(timedelta(hours=-5))  # Colombia usa UTC-5 todo el ano y asi no dependemos de archivos de zonas horarias.
archivo_programacion = Path(__file__).with_name("registro_youtube.json")  # Este archivo recuerda que videos ya se subieron, junto al programa.

permiso = ["https://www.googleapis.com/auth/youtube.upload"]  # esto hace la autenticacion parte 1 que es entrar al yoututbe para subir el video esto le indica a youtube que vamos a hacer en este caso solo subr videos
credenciales = CARPETA_PROYECTO / "credenciales_youtube.json"  # esto coge la autenticacion que me dio youtube api para no ingresar siempre mi correo y contrasena
archivo_token = CARPETA_PROYECTO / "token_credencial.json"  # El token se guarda junto al programa, para no depender de una ruta escrita a mano.

if archivo_token.exists():
    token = Credentials.from_authorized_user_file(archivo_token, permiso)  # vamos a coger el token que ya habiamos creado previamente para que lo utilice y no volvernos a registrar
else:
    autenticacion = InstalledAppFlow.from_client_secrets_file(credenciales, permiso)  # aqui se hace la parte 2 que es instalarlas en mi pc cogiendo las 2 credenciales y permisos
    token = autenticacion.run_local_server(port=0)  # aqui con la instalacion de la autenticacion lo va a correr localmente y lo del port se le esa diciendo a youtube donde le manda la confirmacion que puede seguir adelante
    archivo_token.write_text(token.to_json())  # esto es para escribir el token y no se pase a texto plano sino que directamente a archivo .json

youtube = build("youtube", "v3", credentials=token)  # esto va a coger y a cargar con todo o qe vamos a hacer a youtube y lo arma con el token que ya nos dio youtube, o sea es el mensajero de mis videos


def programar_pendientes(carpeta_clips: Path, carpeta_descripcion: Path) -> int:
    """Sube a YouTube los clips que aun no esten programados. Devuelve cuantos se agendaron."""
    if not carpeta_descripcion.exists():  # Revisamos que exista la carpeta donde estan los textos.
        print(f"No encuentro la carpeta de textos: {carpeta_descripcion}")
        return 0
    if archivo_programacion.exists():  # Preguntamos si ya hay una lista de videos subidos.
        programados = json.loads(archivo_programacion.read_text(encoding="UTF-8"))  # Leemos la lista guardada.
    else:  # Si es la primera ejecucion, creamos una lista vacia.
        programados = {}  # Aqui anotaremos cada clip que YouTube acepte.

    contenido_titulo = sorted(carpeta_descripcion.glob("titulo_*.txt"))  # Encontramos y ordenamos los titulos.
    ahora = datetime.now(ZONA_HORARIA)  # Leemos la hora actual de Colombia.
    proximo_turno = ahora.replace(hour=HORA_PUBLICACION, minute=0, second=0, microsecond=0)  # Preparamos las 19:00 de hoy.
    if proximo_turno <= ahora:  # Si las 19:00 ya pasaron...
        proximo_turno += timedelta(days=1)  # ...el primer turno sera manana.
    ocupados = set()  # Dias que ya tienen un video agendado (YouTube o Facebook), para no repetirlos.
    for datos in programados.values():  # Miramos los turnos que ya reservo YouTube.
        try:
            momento = datetime.fromisoformat(datos["publish_at"])  # Leemos la fecha guardada de ese video.
            if momento.tzinfo is None:  # Si no trae zona horaria...
                momento = momento.replace(tzinfo=ZONA_HORARIA)  # ...la tratamos como colombiana.
            ocupados.add(momento.astimezone(ZONA_HORARIA).date())  # Marcamos ese dia como ocupado.
        except (TypeError, ValueError, KeyError):  # Si una fila no tiene fecha valida...
            continue  # ...la ignoramos y seguimos.
    archivo_facebook = CARPETA_PROYECTO / "registro_meta.json"  # Fechas que ya reservo Facebook.
    if archivo_facebook.exists():  # Si existe el historial de Meta...
        try:
            registro_meta = json.loads(archivo_facebook.read_text(encoding="UTF-8"))  # Lo leemos.
        except json.JSONDecodeError:  # Si esta danado...
            registro_meta = {}  # ...no lo usamos.
        for datos in registro_meta.values():  # Recorremos el historial de clips de Facebook.
            if not isinstance(datos, dict):  # Saltamos filas con formato raro.
                continue  # Seguimos con la siguiente.
            valor = datos.get("facebook_scheduled_at")  # La fecha confirmada en Facebook.
            if not valor:  # Si ese clip no tiene fecha...
                continue  # ...no aporta un dia ocupado.
            try:
                momento = datetime.fromisoformat(valor)  # Leemos la fecha.
                if momento.tzinfo is None:  # Si no trae zona horaria...
                    momento = momento.replace(tzinfo=ZONA_HORARIA)  # ...la tomamos como colombiana.
                ocupados.add(momento.astimezone(ZONA_HORARIA).date())  # Marcamos ese dia como ocupado.
            except (TypeError, ValueError):  # Si la fecha no sirve...
                continue  # ...la ignoramos.
    while proximo_turno.date() in ocupados:  # Si el dia que tocaba ya tiene video en otra red...
        proximo_turno += timedelta(days=1)  # ...reservamos el siguiente dia a las 19:00.

    nuevos = 0  # Contamos cuantos clips se agendaron en esta ejecucion.
    for texto_ia in contenido_titulo:  # Recorremos los titulos en orden, uno por uno.
        nombre_clip = texto_ia.stem.replace("titulo_", "")  # Sacamos el nombre del clip del nombre del titulo.
        if nombre_clip in programados:  # Miramos si ya subimos este clip anteriormente.
            print(f"{nombre_clip} ya esta programado; se omite.")  # Avisamos que no haremos una copia.
            continue  # Saltamos al proximo clip.
        ruta_descripcion = carpeta_descripcion / f"descripcion_{nombre_clip}.txt"  # Armamos la ruta de su descripcion.
        ruta_hashtags = carpeta_descripcion / f"hashtags_{nombre_clip}.txt"  # Armamos la ruta de sus hashtags.
        videos_ruta = carpeta_clips / f"{nombre_clip}.mp4"  # Armamos la ruta del video.
        if not ruta_descripcion.exists() or not ruta_hashtags.exists() or not videos_ruta.exists():  # Comprobamos que esten los cuatro archivos.
            print(f"Faltan archivos para {nombre_clip}; se omitira por ahora.")  # Decimos cual clip tiene algo pendiente.
            continue  # Dejamos ese clip para otra ejecucion.
        titulo_procesado = texto_ia.read_text(encoding="UTF-8").strip()  # Leemos el titulo y limpiamos espacios externos.
        descripcion_procesado = ruta_descripcion.read_text(encoding="UTF-8").strip()  # Leemos la descripcion.
        hashtags_procesado = ruta_hashtags.read_text(encoding="UTF-8").strip()  # Leemos los hashtags.
        descripcion_completa = f"{descripcion_procesado}\n\n{hashtags_procesado}"  # Ponemos hashtags al final de la descripcion.
        hora_publicacion = proximo_turno.isoformat(timespec="seconds")  # Escribimos fecha, hora y zona para YouTube.
        body = {  # Preparamos la informacion que recibira YouTube.
            "snippet": {  # Esta parte contiene el texto que vera la gente.
                "title": titulo_procesado,  # Ponemos el titulo del video.
                "description": descripcion_completa,  # Ponemos descripcion y hashtags.
            },  # Aqui termina el texto del video.
            "status": {  # Esta parte controla quien lo ve y cuando.
                "privacyStatus": "private",  # YouTube exige que este privado mientras espera su fecha.
                "publishAt": hora_publicacion,  # YouTube lo hara publico en el turno indicado.
                "selfDeclaredMadeForKids": False,  # Indicamos que no fue creado especificamente para ninos.
            },  # Aqui terminan las opciones de publicacion.
        }  # Aqui termina el paquete de datos.
        try:
            solicitud = youtube.videos().insert(  # Preparamos la subida del video.
                part="snippet,status",  # Enviamos los textos y las opciones de publicacion.
                body=body,  # Entregamos el paquete que preparamos arriba.
                media_body=MediaFileUpload(str(videos_ruta), resumable=True),  # Enviamos el video y permitimos continuar si se interrumpe.
            )  # Aqui termina la preparacion de la subida.
            respuesta = solicitud.execute()  # Enviamos el video y esperamos confirmacion de YouTube.
        except Exception as error:  # Si YouTube rechaza este clip, paramos para no saltarnos la lista de fechas.
            print(f"Error subiendo {nombre_clip}: {error}")  # Avisamos que clip fallo y por que.
            break  # Detenemos el envio aqui; el clip no se anota y se repite otro dia.
        programados[nombre_clip] = {"video_id": respuesta["id"], "publish_at": hora_publicacion}  # Anotamos el video para evitar subirlo dos veces.
        archivo_programacion.write_text(json.dumps(programados, ensure_ascii=False, indent=2), encoding="UTF-8")  # Guardamos la lista en la carpeta del proyecto.
        print(f"{nombre_clip} quedo programado para {hora_publicacion}.")  # Mostramos la fecha y hora de publicacion.
        proximo_turno += timedelta(days=1)  # Damos al siguiente video el turno del dia siguiente.
        while proximo_turno.date() in ocupados:  # Si ese dia ya tiene video en otra red...
            proximo_turno += timedelta(days=1)  # ...reservamos el proximo dia libre.
        nuevos += 1  # Sumamos un clip agendado en esta vuelta.
    return nuevos  # Devolvemos cuantos se agendaron para que el programa lo anuncie al final.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Programa en YouTube los clips que todavia no tengan fecha.")
    parser.add_argument("--videos", help="carpeta con los MP4")
    parser.add_argument("--textos", help="carpeta donde estan los tres .txt de cada clip")
    args = parser.parse_args()

    clips = Path(args.videos) if args.videos else Path(os.getenv("META_VIDEO_DIR", "videos"))
    textos = Path(args.textos) if args.textos else Path(os.getenv("META_TEXT_DIR", "textos"))

    print(f"Clips:  {clips}")
    print(f"Textos: {textos}")
    total = programar_pendientes(clips, textos)
    print(f"Listo. {total} clip(s) programados en YouTube.")