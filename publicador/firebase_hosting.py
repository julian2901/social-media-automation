import json  # Le damos a Python una herramienta para preparar la configuración que Firebase entiende.
import os  # Le damos a Python una herramienta para leer el ID del proyecto guardado en .env.
import shutil  # Le damos a Python una herramienta para encontrar Firebase CLI y copiar el video.
import subprocess  # Le damos a Python una herramienta para pedirle a Firebase que publique los archivos.
import tempfile  # Le damos a Python una herramienta para crear una carpeta temporal de trabajo.
from pathlib import Path  # Le damos a Python una herramienta para ordenar rutas de carpetas y archivos.
from urllib.parse import quote  # Le damos a Python una herramienta para poner nombres de archivo en una URL con seguridad.

from dotenv import load_dotenv  # Le damos a Python una herramienta para leer las opciones privadas del archivo .env.

load_dotenv(Path(__file__).with_name(".env"))  # Cargamos las opciones del proyecto aunque el programa se ejecute desde otra carpeta.

ID_PROYECTO_FIREBASE = os.getenv("FIREBASE_PROJECT_ID", "").strip()  # Aquí leemos el nombre único del proyecto Firebase.
URL_PUBLICA_VIDEOS = os.getenv("META_PUBLIC_VIDEO_BASE_URL", "").strip()  # Aquí leemos la dirección HTTPS donde Instagram buscará el video.
PLAN_SPARK_CONFIRMADO = os.getenv("FIREBASE_SPARK_CONFIRMED", "false").strip().lower() == "true"  # Revisamos si el dueño confirmó que el proyecto usa el plan gratuito Spark.
TAMANO_MAXIMO_MB = 300  # Ponemos un límite prudente para dejar espacio bajo la cuota diaria gratuita de 360 MB.


def publicar_video_en_firebase(ruta_video: Path) -> str:  # Creamos la receta para alojar un video y devolver su enlace público.
    ruta_video = Path(ruta_video)  # Convertimos el nombre recibido en una ruta que Python pueda revisar.
    if not ruta_video.is_file():  # Revisamos si el archivo del video existe de verdad.
        raise FileNotFoundError(f"No encuentro el video: {ruta_video}")  # Avisamos cuál video hace falta.
    if ruta_video.suffix.lower() != ".mp4":  # Revisamos que Firebase reciba un video MP4.
        raise ValueError("El alojamiento de Instagram solo acepta archivos .mp4 en este flujo.")  # Explicamos el tipo de video esperado.
    if ruta_video.stat().st_size > TAMANO_MAXIMO_MB * 1024 * 1024:  # Comparamos el tamaño del video con nuestro límite prudente.
        raise ValueError(f"El video supera {TAMANO_MAXIMO_MB} MB; no lo subo para cuidar la cuota diaria gratuita.")  # Evitamos desplegar un video muy grande.
    if not ID_PROYECTO_FIREBASE:  # Revisamos si ya sabemos a qué proyecto de Firebase enviar el video.
        raise ValueError("Falta FIREBASE_PROJECT_ID en .env; primero configura Firebase Hosting.")  # Explicamos qué dato de configuración hace falta.
    if not PLAN_SPARK_CONFIRMADO:  # Revisamos si el dueño confirmó en Firebase que el proyecto está en Spark.
        raise ValueError("Confirma el plan Spark en Firebase y escribe FIREBASE_SPARK_CONFIRMED=true en .env antes de subir videos.")  # Evitamos desplegar hasta que se confirme el plan gratuito.
    if not URL_PUBLICA_VIDEOS.startswith("https://"):  # Revisamos que el enlace use HTTPS, como requiere Instagram.
        raise ValueError("Falta configurar META_PUBLIC_VIDEO_BASE_URL con la dirección HTTPS de Firebase Hosting.")  # Avisamos qué enlace falta.
    ejecutable_firebase = shutil.which("firebase")  # Buscamos Firebase CLI, el programa que realiza los despliegues.
    if ejecutable_firebase is None:  # Revisamos si encontramos Firebase CLI en Windows.
        raise RuntimeError("No encuentro Firebase CLI; instálalo y ejecuta firebase login antes de publicar.")  # Indicamos el requisito que falta.
    with tempfile.TemporaryDirectory(prefix="clips_firebase_") as carpeta_temporal:  # Creamos una carpeta que se borrará al terminar.
        ruta_temporal = Path(carpeta_temporal)  # Convertimos la carpeta temporal en una ruta fácil de usar.
        carpeta_publica = ruta_temporal / "public"  # Creamos el lugar que Firebase servirá desde internet.
        carpeta_publica.mkdir()  # Hacemos la carpeta para el video.
        shutil.copy2(ruta_video, carpeta_publica / ruta_video.name)  # Copiamos solo este clip y dejamos intacto el original.
        configuracion = {"hosting": {"public": "public", "ignore": ["firebase.json", "**/.*", "**/node_modules/**"]}}  # Decimos a Firebase qué carpeta publicar y cuáles ignorar.
        archivo_configuracion = ruta_temporal / "firebase.json"  # Creamos la ruta para las instrucciones temporales de Firebase.
        archivo_configuracion.write_text(json.dumps(configuracion, indent=2), encoding="utf-8")  # Guardamos las instrucciones sin cambiar archivos del proyecto.
        comando = [ejecutable_firebase, "deploy", "--only", "hosting", "--project", ID_PROYECTO_FIREBASE, "--non-interactive"]  # Preparamos una orden que publica solo Hosting.
        subprocess.run(comando, cwd=ruta_temporal, check=True, timeout=600)  # Publicamos el clip y paramos si Firebase reporta un error.
    return f"{URL_PUBLICA_VIDEOS.rstrip('/')}/{quote(ruta_video.name)}"  # Devolvemos el enlace HTTPS del video ya alojado.
