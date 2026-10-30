import os
import time # Traemos el reloj para esperar entre una solicitud fallida y el siguiente intento.
import argparse # para que otro programa (el panel) nos diga qué carpetas usar.
from dotenv import load_dotenv #para esta automatizacion de clips lo que mejor viene es dotenv y con esto primero es de donde viene y segundo es lo que se va a importar
from pathlib import Path #para esta automatizacion de clips lo que mejor viene es pathlib y con esto primero es de donde viene y segundo es lo que se va a importar 
from google import genai # el de google y el genai es para que se alla le den la descripcion de los clips   
MAX_INTENTOS_GEMINI = 10 # Permitimos hasta diez intentos para darle tiempo a Gemini de recuperarse.
ESPERA_INICIAL_SEGUNDOS = 10 # Esperamos diez segundos antes del primer reintento.
INCREMENTO_ESPERA_SEGUNDOS = 10 # Aumentamos cada pausa diez segundos respecto a la anterior.

def generar_texto_con_reintentos(video_clips): # Pedimos los textos y volvemos a probar si algo falla.
    for intento in range(1, MAX_INTENTOS_GEMINI + 1): # Contamos intentos del uno al diez.
        try: # Intentamos que Gemini responda correctamente.
            respuesta = conexion.models.generate_content( # Enviamos una petición a Gemini.
                model="gemini-3.5-flash-lite", # Conservamos el modelo que ya estaba configurado.
                contents=( # Juntamos las instrucciones para Gemini.
                    "Eres experto en marketing de salud mental y bienestar emocional. " # Le damos el rol que debe seguir.
                    f"{os.getenv('MARCA_NOMBRE', 'La marca')} es una marca {os.getenv('MARCA_TONO', 'cercana, profesional y educativa')}. " # Le explicamos el tono de la marca.
                    f"El video se llama: {video_clips.name}. " # Le damos el nombre del clip.
                    "Basándote solo en ese nombre, crea un título llamativo, una descripción de máximo 150 palabras, " # Le pedimos textos cortos.
                    "10 hashtags y una calificación de relevancia del 1 al 10 (10 = clip viral potencial, 1 = poco relevante). " # Pedimos la calificación.
                    "Responde exactamente en cuatro líneas, una por campo:\n" # Pedimos cada dato en su propia línea.
                    "TÍTULO: texto del título\nDESCRIPCIÓN: texto de la descripción\nHASHTAGS: #etiqueta1 #etiqueta2\nCALIFICACION: número del 1 al 10" # Damos el formato para reconocer cada dato.
                ), # Aquí termina el mensaje que enviamos.
            ) # Aquí termina la llamada a Gemini.
            lineas = respuesta.text.splitlines() # Separamos la respuesta usando sus saltos de línea.
            campos = {} # Creamos una cajita vacía para guardar título, descripción y hashtags.
            for linea in lineas: # Miramos cada línea que devolvió Gemini.
                if ":" in linea: # Revisamos que la línea tenga etiqueta y contenido.
                    etiqueta, contenido = linea.split(":", 1) # Separamos la etiqueta del texto sin cortar otros dos puntos.
                    campos[etiqueta.strip().upper()] = contenido.strip() # Guardamos el texto bajo la etiqueta en mayúsculas.
            titulo = campos.get("TÍTULO", "") # Buscamos el título.
            descripcion = campos.get("DESCRIPCIÓN", "") # Buscamos la descripción.
            hashtags = campos.get("HASHTAGS", "") # Buscamos los hashtags.
            calificacion_txt = campos.get("CALIFICACION", "5") # Buscamos la calificación; si falta, usamos 5.
            if not titulo or not descripcion or not hashtags: # Revisamos que los tres textos tengan contenido.
                raise ValueError("Gemini devolvió un campo vacío.") # Un campo vacío cuenta como una respuesta fallida.
            try: # Intentamos convertir la calificación a número.
                calificacion = max(1, min(10, int(calificacion_txt))) # Aseguramos que esté entre 1 y 10.
            except ValueError: # Si no es un número válido...
                calificacion = 5 # ...usamos un valor neutro.
            return titulo, descripcion, hashtags, calificacion # Devolvemos los cuatro datos porque todo salió bien.
        except Exception as error: # Capturamos un fallo para poder volver a intentar.
            print(f"Intento {intento}/{MAX_INTENTOS_GEMINI} falló para {video_clips.name}: {error}") # Mostramos el error y el número de intento.
            if intento < MAX_INTENTOS_GEMINI: # Solo esperamos si todavía quedan intentos.
                espera = ESPERA_INICIAL_SEGUNDOS + (intento - 1) * INCREMENTO_ESPERA_SEGUNDOS # Calculamos pausas de 10, 20, 30... segundos.
                print(f"Volveré a intentar en {espera} segundos.") # Contamos cuánto durará la pausa.
                time.sleep(espera) # Pausamos antes de volver a llamar a Gemini.
    raise RuntimeError(f"Gemini falló después de {MAX_INTENTOS_GEMINI} intentos.") # Avisamos que ya no quedan intentos.
load_dotenv()# esto lee el archivo .env y trae lo que haya esto carga el .env
key_gemini=os.getenv("GEMINI_API_KEY") # ya habiendo traido todo ahora con esto  lo que hacemos es decirle al programa cual es la que necesitamos directamente y esto trae lo que se cargo anteriormente el getenv
conexion=genai.Client(api_key=key_gemini) #aqui se esta llamando a google a gemini en este caso  con el genai.Client 


def generar_textos(carpeta_clips: Path, carpeta_descripcion: Path) -> int:
    """Genera título, descripción, hashtags y calificación para cada MP4 que aún no tenga textos. Devuelve cuántos procesó."""
    carpeta_clips.mkdir(parents=True, exist_ok=True)
    carpeta_descripcion.mkdir(parents=True, exist_ok=True)
    archivo_registro = carpeta_clips / "registro.txt" # este archivo recuerda qué clips ya tienen textos

    if archivo_registro.exists(): # con esto lo que hacemos es verificar si el archivo de registro.txt ya existe
        procesados = archivo_registro.read_text(encoding="UTF-8").splitlines() # leemos el archivo y separamos cada linea
    else:
        procesados = []

    clips = list(carpeta_clips.glob("*.mp4")) # guardamos en una variable todos los clips que tengan la extension mp4
    videos_nuevos = [clip for clip in clips if clip.name not in procesados] # colamos los procesados y nos quedamos con los que no

    if not videos_nuevos: # con esto lo que hacemos es verificar si hay clips nuevos
        print("No hay videos nuevos")
        return 0

    for video_clips in videos_nuevos: # con esto lo que hacemos es recorrer todos los clips que se encuentran en la carpeta
        print("Nuevo video encontrado ", video_clips.name) # con esto lo que hacemos es imprimir el nombre de cada clip nuevo que se encuentra en la carpeta
        try:
            titulo, descripcion, hashtags, calificacion = generar_texto_con_reintentos(video_clips) # Pedimos los textos y la calificación.
            no_mp4 = video_clips.name.replace(".mp4", "") # quitamos el .mp4 para armar el nombre de los .txt
            titulo_texto = carpeta_descripcion / f"titulo_{no_mp4}.txt"
            with titulo_texto.open("w",encoding="UTF-8") as f: # con w se reescribe el archivo simpre desde 0
                f.write(titulo)
            descripcion_texto = carpeta_descripcion / f"descripcion_{no_mp4}.txt"
            with descripcion_texto.open("w",encoding="UTF-8") as f:
                f.write(descripcion)
            hashtags_texto = carpeta_descripcion / f"hashtags_{no_mp4}.txt"
            with hashtags_texto.open("w",encoding="UTF-8") as f:
                f.write(hashtags)
            calificacion_texto = carpeta_descripcion / f"calificacion_{no_mp4}.txt"
            with calificacion_texto.open("w",encoding="UTF-8") as f:
                f.write(str(calificacion))
            with archivo_registro.open("a", encoding="UTF-8") as registro: # Solo anotamos el clip cuando ya guardamos los textos.
                registro.write(video_clips.name + "\n") # Si Gemini falla, el clip queda pendiente para otro día.
        except Exception as e: # con esto lo que hacemos es capturar cualquier error al generar la descripcion
            print("Error al generar la descripcion del clip", video_clips.name, e) # mostramos un mensaje de error
    return len(videos_nuevos)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera título, descripción y hashtags para los clips con Gemini.")
    parser.add_argument("--videos", help="carpeta con los MP4")
    parser.add_argument("--textos", help="carpeta donde se guardan los tres .txt")
    args = parser.parse_args()

    carpeta_clips = Path(args.videos) if args.videos else Path(os.getenv("META_VIDEO_DIR", "videos"))
    carpeta_descripcion = Path(args.textos) if args.textos else Path(os.getenv("META_TEXT_DIR", "textos"))

    print(f"Clips:  {carpeta_clips}")
    print(f"Textos: {carpeta_descripcion}")
    total = generar_textos(carpeta_clips, carpeta_descripcion)
    print(f"Listo. {total} clip(s) con textos generados.")

