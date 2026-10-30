import hashlib  # Nos sirve para firmar las peticiones con el secreto de la app.
import hmac  # Nos sirve para comparar firmas sin guardar nada nuevo.
import os  # Leemos las variables de entorno ya cargadas.
from datetime import datetime, timedelta, timezone  # Calculamos cuántos días le quedan al token.
from pathlib import Path  # Armamos las rutas de forma ordenada.

import requests  # Esta es la herramienta que habla con la API de Meta por internet.
from dotenv import load_dotenv  # Nos sirve para leer el archivo secreto .env.

CARPETA_PROYECTO = Path(__file__).parent  # Guardamos dónde está este módulo, para encontrar el .env aunque lo llamen desde otro lado.
load_dotenv(CARPETA_PROYECTO / ".env")  # Leemos el archivo secreto, pero sin pisar lo que ya esté en las variables de entorno.

VERSION_API = os.getenv("META_GRAPH_API_VERSION", "v26.0")  # Esta es la versión de la API con la que hablamos.
DIAS_PARA_RENOVAR = 7  # Si al token le quedan siete días o menos, lo renovamos antes de que caduque.
ALCANCE = "pages_manage_posts,pages_read_engagement,pages_show_list"  # Estos son los permisos que el usuario sistema necesita para publicar Reels en Facebook.
ALCANCE_INSTAGRAM = "instagram_basic,instagram_content_publish,pages_read_engagement,pages_show_list,ads_read"  # Para publicar Reels en Instagram. ads_read va porque el usuario sistema tiene el rol sobre la pagina dentro de Business Manager, y Meta lo pide en esa combinacion.


def leer_valores() -> dict:
    """Lee el archivo .env como cajita de textos, saltándose los comentarios."""
    valores: dict = {}  # Empezamos con la cajita vacía.
    ruta = CARPETA_PROYECTO / ".env"  # Esta es la ruta del archivo secreto.
    if not ruta.is_file():  # Si el archivo no existe todavía...
        return valores  # ...no hay nada que leer, así que devolvemos la cajita vacía.
    for linea in ruta.read_text(encoding="utf-8").splitlines():  # Leemos el archivo línea por línea.
        limpia = linea.strip()  # Quitamos los espacios que sobran al principio y al final.
        if not limpia or limpia.startswith("#") or "=" not in limpia:  # Las líneas vacías, los comentarios y las que no tienen igual se saltan.
            continue  # Pasamos a la siguiente línea.
        clave, valor = limpia.split("=", 1)  # Partimos la línea en dos donde está el primer igual.
        valores[clave.strip()] = valor.strip()  # Guardamos el texto con su nombre, sin espacios.
    return valores  # Devolvemos todo lo que había escrito en el archivo.


def guardar_valor(clave: str, valor: str) -> None:
    """Escribe una clave en el .env y deja el resto del archivo como estaba."""
    ruta = CARPETA_PROYECTO / ".env"  # Esta es la ruta del archivo secreto.
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.is_file() else []  # Leemos el archivo, o empezamos con una lista vacía si no está.
    nueva = f"{clave}={valor}"  # Esta es la línea que queremos dejar escrita.
    for indice, linea in enumerate(lineas):  # Buscamos si esa clave ya existe para no duplicarla.
        limpia = linea.strip()  # Quitamos los espacios que sobran.
        if limpia.startswith(f"{clave}="):  # Si esta línea empieza con el nombre de la clave...
            lineas[indice] = nueva  # ...la reemplazamos por la nueva, y si hadía algo escrito detrás se pierde a propósito.
            break  # Dejamos de buscar porque ya la encontramos.
    else:  # Si el bucle terminó sin encontrar la clave...
        lineas.append(nueva)  # ...la agregamos al final del archivo.
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")  # Guardamos el archivo con salto de línea al final para que quede bien en Windows.


def firma_del_secreto(token: str) -> str:
    """Calcula la firma que Meta pide para saber que la petición viene de esta misma app."""
    secreto = os.getenv("META_APP_SECRET", "").strip()  # Sacamos el secreto de la app del archivo privado.
    if not secreto:  # Si no tenemos el secreto, no podemos firmar nada.
        return ""  # Devolvemos una cadena vacía para que la petición se haga igual, pero sin firma.
    return hmac.new(secreto.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()  # Devolvemos la firma en hexadecimal.


def token_de_sistema() -> str:
    """Devuelve el token del usuario sistema que está guardado ahora mismo."""
    return leer_valores().get("META_SYSTEM_USER_TOKEN", "") or os.getenv("META_SYSTEM_USER_TOKEN", "").strip()


def id_de_la_pagina() -> str:
    """Devuelve el número de la página de Facebook que está configurada."""
    return leer_valores().get("META_PAGE_ID", "") or os.getenv("META_PAGE_ID", "").strip()


def revisar_token(token: str = "") -> dict:
    """Le pregunta a Meta si el token sirve y cuándo caduca, sin publicar nada."""
    token = token or token_de_sistema()
    if not token:
        return {"estado": "sin_configurar", "detalle": "Todavía no hay un token de usuario sistema en el .env.", "expira": None, "dias": None}
    version = os.getenv("META_GRAPH_API_VERSION", "").strip() or VERSION_API
    parametros = {"input_token": token, "access_token": token}  # Mandamos el token dos veces: uno para revisarlo y otro para poder preguntar.
    try:
        respuesta = requests.get(f"https://graph.facebook.com/{version}/debug_token", params=parametros, timeout=30)  # Hacemos una pregunta de solo lectura a Meta.
        cuerpo = respuesta.json()  # Convertimos lo que nos contestó en algo que python pueda leer.
    except Exception as error:  # Si no hay internet o Meta contesta raro...
        return {"estado": "sin_conexion", "detalle": f"No pude hablar con Meta: {error}", "expira": None, "dias": None}  # Avisamos que el problema es la conexión, no el token.
    if respuesta.status_code != 200:  # Si Meta no responde con un sí, el token está malo o vencido.
        mensaje = (cuerpo.get("error") or {}).get("message", "Meta no aceptó la revisión.")  # Buscamos el texto amable que Meta explica.
        return {"estado": "vencido", "detalle": mensaje, "expira": None, "dias": None}  # Avisamos que hay que renovar.
    datos = cuerpo.get("data") or {}  # Si todo salió bien, sacamos la cajita que Meta nos regaló.
    if not datos.get("is_valid"):  # Revisamos que Meta confirme que el token sirve de verdad.
        return {"estado": "vencido", "detalle": datos.get("error", {}).get("error_user_msg") or "Meta dice que el permiso no es válido.", "expira": None, "dias": None}  # Avisamos que hay que renovarlo.
    caducidad = datos.get("expires_at")  # Buscamos el número que dice cuándo se acaba el token.
    if not caducidad or caducidad == 0:  # Si no hay número, es que el token no tiene fecha de vencimiento.
        return {"estado": "ok", "detalle": "Válido y sin fecha de vencimiento.", "expira": None, "dias": None}
    fecha = datetime.fromtimestamp(caducidad, tz=timezone.utc).astimezone(timezone(timedelta(hours=-5)))  # Convertimos ese número en una fecha de Colombia.
    dias = (fecha - datetime.now(timezone(timedelta(hours=-5)))).days  # Contamos cuántos días enteros faltan.
    return {"estado": "ok", "detalle": f"Válido hasta el {fecha.strftime('%d/%m/%Y')} (faltan {dias} días).", "expira": fecha.isoformat(timespec="minutes"), "dias": dias}


def renovar_token_sistema(token_actual: str) -> str:
    """Pide a Meta un token nuevo del mismo usuario sistema, válido por 60 días."""
    app_id = os.getenv("META_APP_ID", "").strip()  # Sacamos el número de la app.
    secreto = os.getenv("META_APP_SECRET", "").strip()  # Sacamos el secreto de la app.
    if not app_id or not secreto:  # Sin app id y secreto no hay forma de renovar.
        raise RuntimeError("Faltan META_APP_ID o META_APP_SECRET en el archivo .env.")
    if not token_actual:  # Si no tenemos un token viejo, no hay nada que renovar.
        raise RuntimeError("No hay un token de usuario sistema para renovar.")
    parametros = {
        "grant_type": "fb_exchange_token",  # Le decimos a Meta que queremos cambiar el token por uno nuevo.
        "client_id": app_id,  # Identificamos la app.
        "client_secret": secreto,  # Le damos el secreto para que confíe en la petición.
        "fb_exchange_token": token_actual,  # Le entregamos el token que ya tenemos.
        "set_token_expires_in_60_days": "true",  # Pedimos el token nuevo con 60 días de validez, como recomienda Meta.
    }
    version = os.getenv("META_GRAPH_API_VERSION", "").strip() or VERSION_API
    respuesta = requests.get(f"https://graph.facebook.com/{version}/oauth/access_token", params=parametros, timeout=30)  # Hacemos el cambio de token.
    cuerpo = respuesta.json() if respuesta.content else {}  # Leemos lo que nos contestó, aunque venga vacío.
    if respuesta.status_code != 200 or "access_token" not in cuerpo:  # Si Meta no nos devolvió un token, no seguimos.
        mensaje = (cuerpo.get("error") or {}).get("message", "Meta no devolvió un token nuevo.")  # Buscamos el motivo del rechazo.
        raise RuntimeError(f"No pude renovar el token: {mensaje}")
    return cuerpo["access_token"]


def token_de_la_pagina(token_sistema: str) -> str:
    """Saca el token de la página de Facebook a partir del token del usuario sistema."""
    if not token_sistema:
        raise RuntimeError("Necesito un token de usuario sistema para sacar el de la página.")
    version = os.getenv("META_GRAPH_API_VERSION", "").strip() or VERSION_API
    parametros = {"access_token": token_sistema, "fields": "id,name,access_token,tasks"}  # Pedimos la lista de páginas a las que tiene acceso.
    firma = firma_del_secreto(token_sistema)  # Firmamos la petición para que Meta sepa que somos la app.
    if firma:
        parametros["appsecret_proof"] = firma
    respuesta = requests.get(f"https://graph.facebook.com/{version}/me/accounts", params=parametros, timeout=30)  # Le preguntamos a Meta qué páginas administra este usuario.
    cuerpo = respuesta.json() if respuesta.content else {}  # Leemos la respuesta.
    if respuesta.status_code != 200:  # Si Meta no deja ver la lista...
        mensaje = (cuerpo.get("error") or {}).get("message", "Meta no devolvió la lista de páginas.")  # ...buscamos el motivo.
        raise RuntimeError(f"No pude leer las páginas del usuario sistema: {mensaje}")
    pagina_id = id_de_la_pagina()  # Buscamos cuál de las páginas es la que nos interesa.
    for pagina in cuerpo.get("data") or []:  # Recorremos todas las páginas que devolvió Meta.
        if pagina.get("id") == pagina_id:  # Si esta es la página que configuramos en el .env...
            token = pagina.get("access_token", "")  # ...sacamos su token de página.
            if token:
                return token  # Devolvemos ese token, que es el que sirve para publicar.
    raise RuntimeError(f"El usuario sistema no tiene acceso a la página {pagina_id}. Revisa que tenga esa página asignada en Business Manager.")


def guardar_token(token_sistema: str, token_pagina: str) -> None:
    """Deja el token nuevo escrito en el .env para que el resto de los programas lo usen."""
    guardar_valor("META_SYSTEM_USER_TOKEN", token_sistema)  # Guardamos el token del usuario sistema.
    guardar_valor("META_PAGE_ACCESS_TOKEN", token_pagina)  # Guardamos el token de la página, que es el que leen los programas.
    os.environ["META_SYSTEM_USER_TOKEN"] = token_sistema  # Lo dejamos también en la memoria de este programa.
    os.environ["META_PAGE_ACCESS_TOKEN"] = token_pagina  # Y el de la página, para que se lean de inmediato.


def renovar_antes_de_vencer(forzar: bool = False) -> dict:
    """Revisa el token y, si le queda poco o ya venció, pide uno nuevo y lo guarda."""
    token = token_de_sistema()  # Empezamos con el token que está guardado.
    if not token:  # Si todavía no hay ninguno...
        return {"estado": "sin_configurar", "detalle": "Falta META_SYSTEM_USER_TOKEN en el .env. Pega ahí el token que generaste en Business Manager.", "expira": None, "dias": None}  # Avisamos qué falta, sin adivinar nada.
    revision = revisar_token(token)  # Le preguntamos a Meta cómo está ese token.
    dias = revision.get("dias")  # Sacamos cuántos días le quedan, si Meta nos lo dijo.
    necesita = forzar or revision.get("estado") != "ok" or (dias is not None and dias <= DIAS_PARA_RENOVAR)  # Decidimos si hay que renovarlo.
    if not necesita:  # Si todavía le queda buen tiempo...
        return revision  # ...lo dejamos como está y devolvemos su estado.
    token_nuevo = renovar_token_sistema(token)  # Le pedimos a Meta un token nuevo.
    token_pagina = token_de_la_pagina(token_nuevo)  # Sacamos el token de la página con el token nuevo.
    guardar_token(token_nuevo, token_pagina)  # Dejamos los dos tokens escritos en el archivo secreto.
    revision = revisar_token(token_nuevo)  # Revisamos el token nuevo para confirmar que quedó bien.
    revision["renovado"] = True  # Dejamos anotado que esta vez sí hubo renovación.
    return revision  # Devolvemos el estado del token nuevo.


def token_pagina_vigente() -> str:
    """Devuelve el token de página que deben usar los programas, renovándolo si hace falta."""
    renovar_antes_de_vencer()  # Primero nos aseguramos de que el token esté vivo.
    return leer_valores().get("META_PAGE_ACCESS_TOKEN", "") or os.getenv("META_PAGE_ACCESS_TOKEN", "").strip()  # Devolvemos el que quedó guardado en el archivo secreto.


if __name__ == "__main__":
    import argparse  # Leemos qué acción quiere el usuario.

    parser = argparse.ArgumentParser(description="Revisa y renueva el token de Meta del usuario sistema.")
    parser.add_argument("accion", choices=["revisar", "renovar", "permisos"], help="revisar solo informa; renovar pide un token nuevo; permisos lista los que hay que marcar.")
    args = parser.parse_args()

    if args.accion == "permisos":  # Si solo quiere saber qué permisos marcar...
        print("Marca estos permisos al generar el token del usuario sistema:")
        print(f"  Facebook: {ALCANCE}")  # Le mostramos los de Facebook.
        print(f"  Instagram: {ALCANCE_INSTAGRAM}")  # Y los de Instagram, que son más.
        print("Deja el token pegado en META_SYSTEM_USER_TOKEN dentro del archivo .env.")
    elif args.accion == "revisar":  # Si solo quiere saber cómo está el token...
        informacion = revisar_token()  # ...preguntamos a Meta sin cambiar nada.
        print(f"Estado: {informacion.get('estado')}")  # Le mostramos en una palabra cómo quedó la cosa.
        print(informacion.get("detalle"))  # Y debajo el detalle con la fecha.
    else:  # Si quiere renewarlo sí o sí...
        informacion = renovar_antes_de_vencer(forzar=True)  # ...pedimos uno nuevo aunque el viejo sirva todavía.
        print(f"Estado: {informacion.get('estado')}")  # Le mostramos en una palabra cómo quedó la cosa.
        print(informacion.get("detalle"))  # Y debajo el detalle con la fecha.
        if informacion.get("renovado"):  # Si hubo renovación...
            print("Se guardó el token nuevo en el archivo .env.")  # Avisamos que ya quedó escrito.