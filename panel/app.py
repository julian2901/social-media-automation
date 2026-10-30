"""Panel local: una página para pasar de una URL a clips programados en redes.

Se ejecuta solo en esta máquina. Escucha en 127.0.0.1 a propósito: desde aquí se
manejan el token de Meta y se suben videos, no debe estar expuesto a la red.
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

import config
import puente
import zipfile

app = FastAPI(title="Panel de clips", docs_url=None, redoc_url=None)

trabajo = puente.Trabajo()  # un solo proceso a la vez: el pipeline es secuencial

# Las etapas largas se lanzan en segundo plano para que la página no se congele
# mientras WhisperX trabaja.
tareas: dict[str, asyncio.Task] = {}


def en_ejecucion() -> bool:
    return trabajo.en_ejecucion()


@app.on_event("startup")
def al_arrancar() -> None:
    config.asegurar_carpetas()


# --- página ---

@app.get("/", response_class=HTMLResponse)
def pagina() -> HTMLResponse:
    return HTMLResponse((Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8"))


# --- estado ---

@app.get("/api/estado")
def estado() -> dict:
    datos = trabajo.estado.como_dict()
    datos["ejecutando"] = en_ejecucion()
    datos["cola"] = puente.cargar_cola()
    datos["progreso_generador"] = puente.leer_progreso_generador()
    return datos


@app.get("/api/resumen")
def resumen() -> dict:
    return puente.resumen()


@app.get("/api/diagnostico")
def diagnostico() -> dict:
    """Qué falta para que todo ande bien, sin tener que adivinar."""
    return {"problemas": config.verificar_instalacion()}


@app.get("/api/auth/estado")
def auth_estado() -> dict:
    """Estado de las credenciales por plataforma (sin mostrar secretos)."""
    return config.estado_auth()


@app.get("/api/progreso")
def progreso() -> dict:
    return puente.leer_progreso_generador() or {"etapa": "", "porcentaje": 0, "mensaje": ""}


# --- log en vivo ---

@app.websocket("/ws")
async def log_en_vivo(ws: WebSocket) -> None:
    await ws.accept()
    cola = trabajo.suscribir()
    try:
        while True:
            mensaje = await cola.get()
            await ws.send_json(mensaje)
    except WebSocketDisconnect:
        pass
    finally:
        trabajo.desuscribir(cola)


# --- helpers ---

class PeticionGenerar(BaseModel):
    url: str = Field(min_length=10, description="URL del video de YouTube")


class PeticionLote(BaseModel):
    cantidad: int = Field(default=999, ge=1, le=1000, description="Cuántos clips programar (por defecto, todos)")


class PeticionTexto(BaseModel):
    titulo: str = ""
    descripcion: str = ""
    hashtags: str = ""


class PeticionCalendario(BaseModel):
    clip: str = Field(min_length=3)
    fecha: str = Field(min_length=10, description="AAAA-MM-DDTHH:MM")


class PeticionInstagram(BaseModel):
    clip: str = Field(min_length=3, description="Nombre del MP4 (ej: videoID_clip_0_final.mp4)")


class PeticionTikTok(BaseModel):
    clip: str = Field(min_length=3, description="Nombre del MP4 (ej: videoID_clip_0_final.mp4)")


class PeticionSpotify(BaseModel):
    video_id: str = Field(min_length=6, max_length=64, description="ID del video de YouTube")
    titulo: str = ""
    descripcion: str = ""


def lanzar(clave: str, coro, al_terminar=None) -> None:
    """Arranca una etapa en segundo plano, si no hay otra corriendo."""
    if en_ejecucion():
        raise HTTPException(409, "Ya hay un proceso corriendo. Espera o cancélalo.")

    tarea = asyncio.create_task(coro)
    tareas[clave] = tarea

    def _callback(t: asyncio.Task) -> None:
        tareas.pop(clave, None)
        if al_terminar is not None:
            try:
                resultado = t.result()
            except Exception as error:  # noqa: BLE001 — lo mostramos en el log
                resultado = None
                trabajo.emitir(f"❌ La etapa {clave} falló: {error}")
            try:
                al_terminar(resultado)
            except Exception as error:  # noqa: BLE001
                trabajo.emitir(f"❌ Post-proceso de {clave} falló: {error}")
        # Si había cola, soltamos el siguiente pendiente.
        asyncio.create_task(_procesar_siguiente_cola())

    tarea.add_done_callback(_callback)


async def _procesar_siguiente_cola() -> None:
    """Si no hay nada corriendo y queda algo en la cola, lo arranca."""
    if en_ejecucion():
        return
    fila = puente.cola_siguiente_pendiente()
    if not fila:
        return
    puente.cola_marcar(fila["id"], "ejecutando")
    trabajo.estado.url = fila["url"]
    trabajo.estado.video_id = fila.get("video_id", "")

    def _al_terminar(estado) -> None:
        resultado = "listo" if estado and estado.estado == "listo" else (
            "cancelado" if estado and estado.estado == "cancelado" else "error"
        )
        puente.cola_marcar(fila["id"], resultado)
        if estado:
            puente.post_proceso_generar(fila["url"], estado, trabajo)

    lanzar("cola", puente.generar_clips(trabajo, fila["url"]), al_terminar=_al_terminar)


# --- acciones ---

@app.post("/api/generar")
async def generar(peticion: PeticionGenerar) -> dict:
    url = peticion.url.strip()
    if not puente.es_url_youtube(url):
        raise HTTPException(400, "Esa URL no parece un video de YouTube válido. Pega un enlace de youtube.com o youtu.be.")
    video_id = puente.extraer_video_id(url)

    if en_ejecucion():
        # Deja la URL en cola y sigue; la interfaz lo avisa. Al terminar el
        # proceso actual, el callback vuelve a mirar la cola y solta el siguiente.
        fila = puente.cola_agregar(url)
        trabajo.emitir(f"📥 URL en cola: {url} (esperando a que termine el proceso actual)")
        return {"ok": True, "en_cola": True, "mensaje": "Hay un proceso corriendo; esta URL quedó en la cola.", "cola": puente.cargar_cola()}

    # Si había cosas en cola de antes, procesamos la primera pendiente (no esta
    # directamente) para no romper el orden. Esta URL queda al final.
    pendiente = puente.cola_siguiente_pendiente()
    if pendiente:
        puente.cola_agregar(url)
        trabajo.emitir(f"📥 URL en cola: {url} (va después de las pendientes)")
        asyncio.create_task(_procesar_siguiente_cola())
        return {"ok": True, "en_cola": True, "mensaje": "Hay URLs pendientes en la cola; esta va después.", "cola": puente.cargar_cola()}

    trabajo.estado.url = url
    trabajo.estado.video_id = video_id or ""

    def _al_terminar(estado) -> None:
        if estado:
            puente.post_proceso_generar(url, estado, trabajo)

    lanzar("generar", puente.generar_clips(trabajo, url), al_terminar=_al_terminar)
    return {"ok": True, "mensaje": "Generando. Esto puede tardar 5-15 minutos."}


@app.get("/api/cola")
def ver_cola() -> dict:
    return {"cola": puente.cargar_cola()}


@app.post("/api/cola")
async def agregar_cola(peticion: PeticionGenerar) -> dict:
    url = peticion.url.strip()
    if not puente.es_url_youtube(url):
        raise HTTPException(400, "Esa URL no parece un video de YouTube válido.")
    try:
        fila = puente.cola_agregar(url)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    trabajo.emitir(f"📥 Agregada a la cola: {url}")
    trabajo._avisar_cola()
    # A diferencia de «Generar», aquí NO soltamos el proceso: el usuario está
    # armando la cola a mano. El botón «Generar» (o el fin del proceso actual)
    # es el que arranca lo pendiente.
    return {
        "ok": True,
        "fila": fila,
        "cola": puente.cargar_cola(),
        "mensaje": "URL en cola. Se procesará cuando no haya otro proceso (o al dar «Generar»).",
    }


@app.delete("/api/cola/{id_fila}")
async def quitar_cola(id_fila: str) -> dict:
    if not puente.cola_quitar(id_fila):
        raise HTTPException(404, "No encontré esa URL en la cola.")
    trabajo._avisar_cola()
    return {"ok": True, "mensaje": "Quitada de la cola.", "cola": puente.cargar_cola()}


@app.post("/api/textos")
async def textos() -> dict:
    lanzar("textos", puente.generar_textos(trabajo))
    return {"ok": True, "mensaje": "Escribiendo textos con Gemini."}


@app.post("/api/lote")
async def lote(peticion: PeticionLote) -> dict:
    lanzar("lote", puente.preparar_lote(trabajo, peticion.cantidad))
    return {"ok": True, "mensaje": "Preparando el lote. No sube nada todavía."}


@app.post("/api/publicar")
async def publicar() -> dict:
    # Sube de verdad a Facebook. Si no hay lote preparado, lo arma solo con
    # TODOS los clips pendientes (no solo 5); si no hay nada pendiente, no publica nada.
    lanzar("publicar", puente.publicar(trabajo))
    return {"ok": True, "mensaje": "Subiendo y programando en Facebook (arma el lote solo si falta)."}


@app.post("/api/youtube")
async def subir_youtube() -> dict:
    if not config.TOKEN_YOUTUBE.is_file() and not config.TOKEN_YOUTUBE_ALT.is_file():
        raise HTTPException(400, "Primero conecta YouTube desde la sección de credenciales.")
    lanzar("youtube", puente.subir_youtube(trabajo))
    return {"ok": True, "mensaje": "Subiendo clips pendientes a YouTube."}


@app.post("/api/instagram")
async def subir_instagram(peticion: PeticionInstagram) -> dict:
    """Publica un clip en Instagram como Reel (Firebase Hosting + Graph API)."""
    nombre = peticion.clip
    if "/" in nombre or "\\" in nombre or ".." in nombre:
        raise HTTPException(400, "Nombre de archivo inválido.")
    if not nombre.lower().endswith(".mp4"):
        nombre = nombre + ".mp4"
    ruta = config.CLIPES_DIR / nombre
    if not ruta.is_file():
        raise HTTPException(404, f"No encontré el clip: {nombre}")
    if not config.clip_tiene_textos(nombre):
        raise HTTPException(400, f"El clip {nombre} no tiene textos. Genera los textos primero.")
    lanzar("instagram", puente.subir_instagram(trabajo, nombre))
    return {"ok": True, "mensaje": f"Subiendo {nombre} a Instagram."}


@app.post("/api/instagram/todos")
async def subir_instagram_todos() -> dict:
    """Publica el Reel de hoy (máximo uno por día); nada si ya se publicó o no hay pendientes."""
    lanzar("instagram", puente.subir_instagram_lote(trabajo))
    return {"ok": True, "mensaje": "Revisando Instagram: publicará un solo Reel si hoy aún no ha publicado."}


@app.post("/api/auth/youtube")
async def auth_youtube() -> dict:
    lanzar("auth_youtube", puente.conectar_youtube(trabajo))
    return {"ok": True, "mensaje": "Se abrió la autorización de Google. Entra al navegador y acepta."}


@app.post("/api/tiktok")
async def subir_tiktok(peticion: PeticionTikTok) -> dict:
    """Publica un clip en TikTok como video normal."""
    if not config.TOKEN_TIKTOK.is_file():
        raise HTTPException(400, "Primero conecta TikTok desde la sección de credenciales.")
    nombre = peticion.clip
    if "/" in nombre or "\\" in nombre or ".." in nombre:
        raise HTTPException(400, "Nombre de archivo inválido.")
    if not nombre.lower().endswith(".mp4"):
        nombre = nombre + ".mp4"
    ruta = config.CLIPES_DIR / nombre
    if not ruta.is_file():
        raise HTTPException(404, f"No encontré el clip: {nombre}")
    if not config.clip_tiene_textos(nombre):
        raise HTTPException(400, f"El clip {nombre} no tiene textos. Genera los textos primero.")
    lanzar("tiktok", puente.subir_tiktok(trabajo, nombre))
    return {"ok": True, "mensaje": f"Subiendo {nombre} a TikTok."}


@app.post("/api/auth/tiktok")
async def auth_tiktok() -> dict:
    lanzar("auth_tiktok", puente.conectar_tiktok(trabajo))
    return {"ok": True, "mensaje": "Se abrió la autorización de TikTok. Autoriza en el navegador y vuelve."}


# --- Spotify (audio completo) ---
# Spotify no permite subir episodios/audio a través de una API pública sencilla.
# El panel solo guarda el MP3 + título + descripción en una carpeta para
# descargarlos y subirlos a mano desde Spotify for Artists / Podcasters.
# El botón se añade apartado de los demás para hacerlo visible.


@app.get("/api/spotify")
def spotify_lista() -> dict:
    return puente.listar_audios()


@app.get("/api/spotify/audio/{video_id}")
def spotify_audio(video_id: str) -> FileResponse:
    ruta = puente.ruta_audio(video_id)
    if ruta is None or not ruta.is_file():
        raise HTTPException(404, "No encontré el audio de ese video.")
    return FileResponse(ruta, media_type="audio/mpeg", filename=f"{video_id}.mp3")


@app.get("/api/spotify/info/{video_id}")
def spotify_info(video_id: str) -> dict:
    try:
        return puente.buscar_info_video(video_id)
    except Exception as error:
        raise HTTPException(500, str(error)) from error


@app.post("/api/spotify/preparar")
async def spotify_preparar(peticion: PeticionSpotify) -> dict:
    try:
        datos = puente.preparar_spotify(peticion.video_id, peticion.titulo, peticion.descripcion)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except Exception as error:
        raise HTTPException(500, str(error)) from error
    return {"ok": True, "mensaje": "Audio listo para descargar y subir a Spotify.", **datos}


@app.get("/api/spotify/paquete/{video_id}/audio")
def spotify_paquete_audio(video_id: str) -> FileResponse:
    paquete = puente.paquete_spotify(video_id)
    if paquete is None:
        raise HTTPException(404, "No hay paquete preparado para ese video. Pulsa «Preparar para Spotify» primero.")
    ruta = config.SPOTIFY_DIR / video_id / "audio.mp3"
    if not ruta.is_file():
        raise HTTPException(404, "No encontré el archivo de audio en el paquete.")
    return FileResponse(ruta, media_type="audio/mpeg", filename=f"{paquete['titulo'] or video_id}.mp3")


@app.get("/api/spotify/paquete/{video_id}/zip")
def spotify_paquete_zip(video_id: str) -> FileResponse:
    paquete = puente.paquete_spotify(video_id)
    if paquete is None:
        raise HTTPException(404, "Prepara el paquete primero.")

    carpeta = config.SPOTIFY_DIR / video_id
    tmp = carpeta / "spotify-paquete.zip"
    if tmp.is_file():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w") as z:
        for nombre in ("audio.mp3", "titulo.txt", "descripcion.txt", "info.json"):
            ruta = carpeta / nombre
            if ruta.is_file():
                # El MP3 ya viene comprimido: recomprimirlo solo gasta tiempo.
                compresion = zipfile.ZIP_STORED if nombre.endswith(".mp3") else zipfile.ZIP_DEFLATED
                z.write(ruta, arcname=nombre, compress_type=compresion)
    return FileResponse(tmp, media_type="application/zip", filename=f"spotify-{video_id}.zip")


@app.post("/api/cancelar")
async def cancelar() -> dict:
    await trabajo.cancelar()
    return {"ok": True, "mensaje": "Cancelado."}


# --- clips ---

@app.get("/api/clip/{nombre}")
def ver_clip(nombre: str) -> FileResponse:
    """Sirve el MP4 para previsualizarlo. Solo archivos de la carpeta de clips."""
    if "/" in nombre or "\\" in nombre or ".." in nombre:
        raise HTTPException(400, "Nombre de archivo inválido.")
    ruta = (config.CLIPES_DIR / nombre).resolve()
    if ruta.parent != config.CLIPES_DIR.resolve() or not ruta.is_file():
        raise HTTPException(404, "No se encontró ese clip.")
    return FileResponse(ruta, media_type="video/mp4")


@app.get("/api/clip/{nombre}/zip")
def clip_zip(nombre: str) -> FileResponse:
    """Descarga el MP4 + título/descripcion/hashtags en un .ZIP para subirlo a mano."""
    if "/" in nombre or "\\" in nombre or ".." in nombre:
        raise HTTPException(400, "Nombre de archivo inválido.")
    ruta = (config.CLIPES_DIR / nombre).resolve()
    if ruta.parent != config.CLIPES_DIR.resolve() or not ruta.is_file():
        raise HTTPException(404, "No se encontró ese clip.")
    textos = config.leer_textos(nombre)
    carpeta_tmp = config.CLIPES_DIR / "_paquetes"
    carpeta_tmp.mkdir(parents=True, exist_ok=True)
    tmp = carpeta_tmp / f"{ruta.stem}.zip"
    if tmp.is_file():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w") as z:
        z.write(ruta, arcname=nombre)
        for campo in ("titulo", "descripcion", "hashtags"):
            valor = str(textos.get(campo) or "").strip()
            if valor:
                z.writestr(f"{campo}.txt", valor)
    return FileResponse(tmp, media_type="application/zip", filename=f"{ruta.stem}_para_subir.zip")


@app.get("/api/miniatura/{nombre}")
def ver_miniatura(nombre: str) -> FileResponse:
    """Sirve el JPG de miniatura. Si no existe, 404 y el frontend usa el visor."""
    if "/" in nombre or "\\" in nombre or ".." in nombre:
        raise HTTPException(400, "Nombre de archivo inválido.")
    stem = nombre[:-4] if nombre.lower().endswith(".mp4") else nombre
    ruta = (config.MINIATURAS_DIR / f"{stem}.jpg").resolve()
    if ruta.parent != config.MINIATURAS_DIR.resolve() or not ruta.is_file():
        raise HTTPException(404, "Sin miniatura todavía.")
    return FileResponse(ruta, media_type="image/jpeg")


@app.get("/api/miniaturas/crear")
def crear_miniaturas(video_id: str = "") -> dict:
    """Fuerza la creación de miniaturas (para clips viejos o si ffmpeg falló antes)."""
    cantidad = puente.crear_miniaturas_para(video_id or None)
    if video_id:
        puente.historial_marcar_miniaturas(video_id, cantidad)
    return {"ok": True, "miniaturas": cantidad}


@app.get("/api/lote-pendiente")
def lote_pendiente() -> dict:
    """El resumen que escribe el publicador, para leerlo sin abrir la terminal."""
    if not config.LOTE_RESUMEN.is_file():
        return {"existe": False, "texto": ""}
    return {"existe": True, "texto": config.LOTE_RESUMEN.read_text(encoding="utf-8")}


# --- textos editables ---

@app.get("/api/textos/{nombre_clip}")
def leer_textos_clip(nombre_clip: str) -> dict:
    if "/" in nombre_clip or "\\" in nombre_clip or ".." in nombre_clip:
        raise HTTPException(400, "Nombre de archivo inválido.")
    return {"clip": nombre_clip, **config.leer_textos(nombre_clip)}


@app.put("/api/textos/{nombre_clip}")
async def guardar_textos_clip(nombre_clip: str, peticion: PeticionTexto) -> dict:
    if "/" in nombre_clip or "\\" in nombre_clip or ".." in nombre_clip:
        raise HTTPException(400, "Nombre de archivo inválido.")
    # Solo aceptamos clips que existan (o al menos tengan sentido como nombre mp4).
    if not nombre_clip.lower().endswith(".mp4"):
        nombre_clip = nombre_clip + ".mp4"
    config.guardar_textos(nombre_clip, peticion.dict())
    return {"ok": True, "mensaje": f"Textos guardados para {nombre_clip}"}


# --- historial ---

@app.get("/api/historial")
def historial() -> dict:
    return {"historial": puente.cargar_historial()}


# --- calendario ---

@app.get("/api/calendario")
def ver_calendario() -> dict:
    return puente.calendario()


@app.get("/api/video_hoy")
def ver_video_hoy() -> dict:
    """El Reel pendiente que tocaría hoy y si ya se publicó el del día."""
    return puente.video_hoy()


@app.put("/api/calendario/fecha")
async def mover_calendario(peticion: PeticionCalendario) -> dict:
    try:
        resultado = puente.calendario_mover(peticion.clip, peticion.fecha)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"ok": True, **resultado}


@app.post("/api/calendario/reordenar")
async def reordenar_calendario() -> dict:
    try:
        resultado = puente.calendario_reordenar()
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"ok": True, **resultado, "mensaje": "Fechas reasignadas desde mañana, 7 p. m."}


if __name__ == "__main__":
    import uvicorn

    # host 127.0.0.1 y no 0.0.0.0: esta página maneja el token de Meta.
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
