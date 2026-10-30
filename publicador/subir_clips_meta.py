import os # Le pedimos a Python herramientas para leer ajustes guardados fuera del código.
from pathlib import Path # Le pedimos una forma ordenada de trabajar con nombres de archivos y carpetas.
import requests # Le pedimos una herramienta para conversar con las APIs de Meta por internet.
import time # Le pedimos un reloj para esperar mientras Instagram prepara el video.
from datetime import datetime, timedelta # Leemos la fecha programada y revisamos si es futura.
from dotenv import load_dotenv # Le pedimos la herramienta que lee las opciones del archivo .env.
from firebase_hosting import publicar_video_en_firebase # Le pedimos la receta que prepara el enlace HTTPS del video en Firebase Hosting.
from typing import Callable # Permitimos guardar un punto de control antes de enviar la orden final a Facebook.
import meta_tokens # La herramienta que renueva el permiso de Meta antes de que se venza.

load_dotenv() # Cargamos los ajustes del archivo .env para que Python pueda encontrarlos.

VERSION_API = os.getenv("META_GRAPH_API_VERSION", "") # Aquí irá la versión de la API que indique Meta.
ID_PAGINA = os.getenv("META_PAGE_ID", "") # Aquí irá el número que identifica la página de Facebook.
TOKEN_PAGINA = os.getenv("META_PAGE_ACCESS_TOKEN", "") # Aquí irá el permiso secreto para publicar en la página.
ID_INSTAGRAM = os.getenv("META_INSTAGRAM_USER_ID", "") # Aquí irá el número del Instagram profesional.
HORA_PUBLICACION = 19 # Esta es la hora común que elegimos: las siete de la noche en Colombia.

def revisar_ajustes(): # Creamos una receta para revisar que estén los datos necesarios.
    if not VERSION_API: # Miramos si todavía falta la versión de la API.
        raise ValueError("Falta META_GRAPH_API_VERSION en el archivo .env.") # Avisamos qué dato debe agregarse.
    global TOKEN_PAGINA # Le decimos a Python que vamos a cambiar esta variable.
    TOKEN_PAGINA = meta_tokens.token_pagina_vigente() # Antes de publicar, nos aseguramos de que el permiso siga vivo y lo renovamos si hace falta.
    if not TOKEN_PAGINA: # Revisamos que el permiso exista.
        raise ValueError("Falta META_PAGE_ACCESS_TOKEN en el archivo .env.") # Avisamos qué dato debe agregarse.

def verificar_conexion_meta() -> dict: # Creamos una revisión segura que consulta Meta sin publicar nada.
    revisar_ajustes() # Comprobamos que tengamos versión de API y token antes de llamar a Meta.
    if not ID_PAGINA: # Miramos si conocemos el número de la página de Facebook.
        raise ValueError("Falta META_PAGE_ID en el archivo .env.") # Decimos qué dato hay que agregar.
    if not ID_INSTAGRAM: # Miramos si conocemos el número de la cuenta profesional de Instagram.
        raise ValueError("Falta META_INSTAGRAM_USER_ID en el archivo .env.") # Decimos qué dato hay que agregar.
    direccion = f"https://graph.facebook.com/{VERSION_API}/{ID_PAGINA}" # Preparamos una consulta de solo lectura para la página.
    encabezados = {"Authorization": f"Bearer {TOKEN_PAGINA}"} # Enviamos el token como autorización, no dentro de la dirección.
    parametros = {"fields": "id,name,instagram_business_account"} # Pedimos el nombre de la página y la cuenta de Instagram conectada.
    respuesta = requests.get(direccion, headers=encabezados, params=parametros, timeout=30) # Consultamos a Meta sin publicar contenido.
    respuesta.raise_for_status() # Detenemos la revisión si Meta devuelve un error de acceso o configuración.
    datos_pagina = respuesta.json() # Convertimos la respuesta de Meta en datos que Python puede leer.
    cuenta_instagram = datos_pagina.get("instagram_business_account", {}) # Sacamos de la página la cuenta de Instagram conectada.
    if cuenta_instagram.get("id") != ID_INSTAGRAM: # Comparamos el Instagram recibido con el que guardamos en .env.
        raise ValueError("El Instagram del .env no coincide con el vinculado a la página de Facebook.") # Evitamos publicar en una cuenta equivocada.
    return {"pagina": datos_pagina.get("name"), "instagram_id": cuenta_instagram["id"]} # Devolvemos solo nombres e identificadores, nunca el token.

def crear_caption(titulo: str, descripcion: str, hashtags: str) -> str: # Creamos el texto que acompañará el video.
    partes = [titulo.strip(), descripcion.strip(), hashtags.strip()] # Limpiamos y ordenamos título, descripción y etiquetas.
    return "\n\n".join(parte for parte in partes if parte) # Juntamos las partes con espacios y omitimos las que estén vacías.

def publicar_reel_instagram(url_video: str, caption: str) -> str: # Creamos la receta para publicar un Reel en Instagram.
    revisar_ajustes() # Antes de empezar, comprobamos que estén los ajustes básicos.
    if not ID_INSTAGRAM: # Revisamos que sepamos cuál cuenta de Instagram recibirá el Reel.
        raise ValueError("Falta META_INSTAGRAM_USER_ID en el archivo .env.") # Avisamos que ese dato todavía no está configurado.
    if not url_video.startswith("https://"): # Revisamos que el video tenga una dirección segura y pública.
        raise ValueError("Instagram necesita una URL HTTPS pública para descargar el video.") # Explicamos por qué no sirve una ruta local.
    direccion = f"https://graph.facebook.com/{VERSION_API}/{ID_INSTAGRAM}/media" # Armamos la dirección oficial para preparar un Reel.
    datos = {"media_type": "REELS", "video_url": url_video, "caption": caption, "share_to_feed": "true", "access_token": TOKEN_PAGINA} # Empacamos el Reel, su texto y el permiso.
    respuesta = requests.post(direccion, data=datos, timeout=60) # Enviamos a Meta la solicitud para preparar el Reel.
    respuesta.raise_for_status() # Si Meta responde con error, Python lo mostrará en vez de seguir como si funcionara.
    id_contenedor = respuesta.json()["id"] # Guardamos el número temporal del Reel que Meta está preparando.
    direccion_estado = f"https://graph.facebook.com/{VERSION_API}/{id_contenedor}" # Armamos la dirección para preguntar si el video ya está listo.
    for intento in range(60): # Revisamos el estado hasta 60 veces, como máximo.
        encabezados = {"Authorization": f"Bearer {TOKEN_PAGINA}"} # Guardamos el permiso en el encabezado para no ponerlo en la URL.
        estado = requests.get(direccion_estado, headers=encabezados, params={"fields": "status_code"}, timeout=60) # Preguntamos a Meta cómo va el procesamiento.
        estado.raise_for_status() # Si Meta devuelve un error, lo mostramos y detenemos la publicación.
        codigo_estado = estado.json().get("status_code") # Leemos si el video está procesándose o ya terminó.
        if codigo_estado == "FINISHED": # Revisamos si Instagram terminó de preparar el Reel.
            break # Cuando esté listo, podemos pedir que lo publique.
        if codigo_estado in {"ERROR", "EXPIRED"}: # Revisamos si Meta reportó un error o dejó vencer el contenedor.
            raise RuntimeError(f"Instagram no pudo preparar el video: {codigo_estado}.") # Avisamos que no se puede publicar este contenedor.
        time.sleep(5) # Esperamos cinco segundos antes de volver a preguntar.
    else: # Si las 60 revisiones terminaron sin que estuviera listo...
        raise TimeoutError("Instagram tardó más de cinco minutos en preparar el video.") # ...paramos para que se pueda volver a intentar después.
    direccion_publicar = f"https://graph.facebook.com/{VERSION_API}/{ID_INSTAGRAM}/media_publish" # Armamos la dirección oficial para publicar el Reel.
    datos_publicar = {"creation_id": id_contenedor, "access_token": TOKEN_PAGINA} # Indicamos cuál Reel preparado queremos publicar.
    respuesta_publicacion = requests.post(direccion_publicar, data=datos_publicar, timeout=60) # Le pedimos a Meta que publique el Reel.
    respuesta_publicacion.raise_for_status() # Detenemos el proceso si Meta devuelve un error.
    return respuesta_publicacion.json()["id"] # Devolvemos el número del Reel que quedó publicado.

def publicar_reel_facebook(ruta_video: Path, titulo: str, caption: str) -> str: # Creamos la receta para publicar un Reel en la página.
    revisar_ajustes() # Antes de empezar, comprobamos que estén los ajustes básicos.
    if not ID_PAGINA: # Miramos si sabemos cuál página de Facebook recibirá el Reel.
        raise ValueError("Falta META_PAGE_ID en el archivo .env.") # Avisamos que ese dato todavía no está configurado.
    if not ruta_video.is_file(): # Comprobamos que el video exista en el disco.
        raise FileNotFoundError(f"No encuentro el video: {ruta_video}") # Indicamos el archivo que falta.
    direccion_inicio = f"https://graph.facebook.com/{VERSION_API}/{ID_PAGINA}/video_reels" # Armamos la dirección oficial para iniciar la subida.
    datos_inicio = {"upload_phase": "start", "access_token": TOKEN_PAGINA} # Pedimos a Meta que abra un espacio para el video.
    inicio = requests.post(direccion_inicio, data=datos_inicio, timeout=60) # Enviamos la petición para crear el espacio de subida.
    inicio.raise_for_status() # Si Meta no crea el espacio, paramos y mostramos el error.
    datos_sesion = inicio.json() # Leemos la respuesta con los datos de la subida.
    id_video = datos_sesion["video_id"] # Guardamos el número temporal de este Reel.
    tamano_video = ruta_video.stat().st_size # Averiguamos cuántos bytes ocupa el video.
    encabezados = {"Authorization": f"OAuth {TOKEN_PAGINA}", "offset": "0", "file_size": str(tamano_video), "Content-Type": "application/octet-stream"} # Preparamos los datos necesarios para mandar el archivo.
    with ruta_video.open("rb") as archivo: # Abrimos el video en modo lectura de bytes, como se leen fotos o música.
        subida = requests.post(datos_sesion["upload_url"], data=archivo, headers=encabezados, timeout=600) # Mandamos el archivo a Meta.
    subida.raise_for_status() # Si la subida falla, paramos antes de pedir que se publique.
    datos_finales = {"upload_phase": "finish", "video_id": id_video, "video_state": "PUBLISHED", "description": caption, "title": titulo, "access_token": TOKEN_PAGINA} # Pedimos publicar el Reel ya subido.
    finalizacion = requests.post(direccion_inicio, data=datos_finales, timeout=60) # Enviamos la orden final a Facebook.
    finalizacion.raise_for_status() # Si Facebook responde con error, lo mostramos.
    return id_video # Devolvemos el número del Reel que Facebook recibió.

def programar_reel_facebook(ruta_video: Path, titulo: str, caption: str, fecha_programada: datetime, antes_de_confirmar: Callable[[str], None] | None = None) -> str: # Subimos un Reel local y pedimos a Facebook que lo publique en el futuro.
    revisar_ajustes() # Comprobamos que la versión y el token estén configurados.
    if not ID_PAGINA: # Revisamos que sepamos qué página recibirá el Reel.
        raise ValueError("Falta META_PAGE_ID en el archivo .env.") # Avisamos qué valor debe configurarse.
    if not ruta_video.is_file(): # Revisamos que el MP4 exista antes de iniciar una subida.
        raise FileNotFoundError(f"No encuentro el video: {ruta_video}") # Indicamos qué video falta.
    if fecha_programada.tzinfo is None: # Comprobamos que la fecha tenga zona horaria para no equivocarnos de hora.
        raise ValueError("La fecha programada debe incluir una zona horaria.") # Explicamos el formato seguro requerido.
    ahora = datetime.now(fecha_programada.tzinfo) # Leemos la hora actual usando la misma zona horaria de la fecha.
    if fecha_programada < ahora + timedelta(minutes=10): # Revisamos que la hora esté al menos diez minutos en el futuro.
        raise ValueError("Facebook necesita que el Reel quede programado al menos diez minutos en el futuro.") # Evitamos pedir una programación vencida o inmediata.
    direccion = f"https://graph.facebook.com/{VERSION_API}/{ID_PAGINA}/video_reels" # Preparamos la dirección oficial de Reels de la página.
    inicio = requests.post(direccion, data={"upload_phase": "start", "access_token": TOKEN_PAGINA}, timeout=60) # Pedimos a Facebook una sesión nueva para este Reel.
    comprobar_respuesta_meta(inicio, "iniciar la subida") # Mostramos el motivo que Meta devuelve si rechaza abrir la sesión.
    datos_sesion = inicio.json() # Leemos el número temporal y la dirección para subir el video.
    id_video = datos_sesion["video_id"] # Guardamos el ID para completar y registrar este Reel.
    tamano_video = ruta_video.stat().st_size # Averiguamos el tamaño exacto del MP4 en bytes.
    encabezados = {"Authorization": f"OAuth {TOKEN_PAGINA}", "offset": "0", "file_size": str(tamano_video), "Content-Type": "application/octet-stream"} # Preparamos el envío binario que pide Facebook.
    with ruta_video.open("rb") as archivo: # Abrimos el MP4 para leer sus bytes sin modificarlo.
        subida = requests.post(datos_sesion["upload_url"], data=archivo, headers=encabezados, timeout=600) # Subimos el archivo directamente a Facebook, sin pasar por Firebase.
    comprobar_respuesta_meta(subida, "transferir el video") # Revisamos que Meta haya recibido los bytes del archivo.
    if antes_de_confirmar is not None: # Revisamos si el programa principal pidió guardar un punto de control.
        antes_de_confirmar(id_video) # Guardamos el ID antes de la orden final por si la respuesta de Facebook se pierde.
    marca_de_tiempo = int(fecha_programada.timestamp()) # Convertimos la fecha local a segundos Unix como espera la API.
    datos_finales = {"upload_phase": "finish", "video_id": id_video, "video_state": "SCHEDULED", "scheduled_publish_time": marca_de_tiempo, "description": caption, "title": titulo, "access_token": TOKEN_PAGINA} # Solicitamos guardar el Reel para la fecha y hora asignadas.
    finalizacion = requests.post(direccion, data=datos_finales, timeout=60) # Enviamos a Facebook la orden de terminar y programar el Reel.
    comprobar_respuesta_meta(finalizacion, "confirmar la programación") # Mostramos el motivo si Meta no acepta el horario.
    if finalizacion.json().get("success") is not True: # Comprobamos que Facebook confirme el guardado de la programación.
        raise RuntimeError(f"Facebook no confirmó la programación de {ruta_video.name}; revisa la pestaña Programadas antes de reintentar.") # Evitamos asumir que quedó programado.
    return id_video # Devolvemos el ID de Facebook para guardarlo en el registro.

def comprobar_respuesta_meta(respuesta: requests.Response, paso: str) -> None: # Leemos los errores de Meta sin imprimir el token privado.
    if respuesta.ok: # Comprobamos si Meta respondió con un código de éxito.
        return # Seguimos con el siguiente paso.
    try: # Intentamos leer el mensaje de error como JSON.
        cuerpo = respuesta.json() # Convertimos la respuesta de Meta en datos.
    except ValueError: # La respuesta puede no estar escrita en formato JSON.
        cuerpo = {} # Usamos un objeto vacío si no se pudo convertir.
    error = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {} # Sacamos solo el bloque donde Meta pone el error.
    if isinstance(error, dict): # Comprobamos que Meta haya enviado un objeto de error.
        mensaje = error.get("error_user_msg") or error.get("message") or str(error) # Elegimos una explicación legible y sin mostrar credenciales.
        codigo = error.get("code") # Leemos el código que ayuda a identificar el problema.
        subcodigo = error.get("error_subcode") # Leemos el subcódigo si Meta lo incluyó.
        referencia = error.get("fbtrace_id") # Leemos el número que soporte de Meta puede usar para buscar el error.
    else: # Si Meta devolvió otra forma de datos...
        mensaje = str(error) # ...convertimos el contenido a texto.
        codigo = None # No hay código separado disponible.
        subcodigo = None # No hay subcódigo separado disponible.
        referencia = None # No hay referencia separada disponible.
    detalles = [f"Meta respondió HTTP {respuesta.status_code} al {paso}: {mensaje}"] # Empezamos un mensaje con el paso y la explicación.
    if codigo is not None: # Añadimos el código si estaba disponible.
        detalles.append(f"código {codigo}") # Guardamos ese dato para el diagnóstico.
    if subcodigo is not None: # Añadimos el subcódigo si estaba disponible.
        detalles.append(f"subcódigo {subcodigo}") # Guardamos el detalle adicional.
    if referencia: # Añadimos la referencia técnica si estaba disponible.
        detalles.append(f"referencia {referencia}") # Este número ayuda al soporte técnico de Meta.
    raise RuntimeError("; ".join(detalles)) # Detenemos el flujo con la información útil del error.

def publicar_reel_en_ambas(redes: dict, ruta_video: Path, titulo: str, descripcion: str, hashtags: str) -> dict: # Creamos una receta que coordina las dos redes.
    resultados = {} # Preparamos una libreta vacía para anotar cada resultado.
    caption = crear_caption(titulo, descripcion, hashtags) # Juntamos el texto que acompañará el video en ambas redes.
    if redes.get("instagram", True): # Revisamos si Instagram está seleccionado para esta publicación.
        url_video_publica = publicar_video_en_firebase(ruta_video) # Publicamos el archivo en Firebase y recibimos un enlace HTTPS.
        resultados["instagram"] = publicar_reel_instagram(url_video_publica, caption) # Publicamos en Instagram y guardamos su número de publicación.
    if redes.get("facebook", True): # Revisamos si Facebook está seleccionado para esta publicación.
        resultados["facebook"] = publicar_reel_facebook(ruta_video, titulo, caption) # Publicamos en Facebook y guardamos su número de publicación.
    return resultados # Devolvemos la libreta con los resultados de cada red.

if __name__ == "__main__": # Revisamos si ejecutaron este archivo directamente, no si lo importó otro módulo.
    resultado_conexion = verificar_conexion_meta() # Consultamos la página y el Instagram sin publicar ningún video.
    print(f"Conexión correcta: página {resultado_conexion['pagina']} e Instagram ID {resultado_conexion['instagram_id']}.") # Mostramos el resultado sin revelar credenciales.
