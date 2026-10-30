"""Orquestación de los subprocesos: cola, etapas, progreso y estado para la página.

No sabe nada de HTTP. Si mañana se usa desde otro sitio, se importa y listo.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

# Los dos venvs son pesados; creamos el proceso con su propia lupa de Windows para
# poder matar el árbol entero (python -> ffmpeg) y que no queden huerfanos.
CREACION_GRUPO = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

# "✅ Clip 1 completado: C:\...\clips_finales\abc_clip_0_final.mp4"
REGRESO_CLIP = re.compile(r"completado:\s*(.+?\.mp4)\s*$", re.MULTILINE)
# Líneas que el generador imprime para que el panel sepa dónde va.
REGEX_VIDEO_ID = re.compile(r"^VIDEO_ID:(.+)$")
REGEX_DURACION = re.compile(r"^DURACION_SEGUNDOS:(\d+)$")
REGEX_TITULO = re.compile(r"^VIDEO_TITULO:(.+)$")
REGEX_RESULTADO = re.compile(r"^RESULTADO_CLIPS:(\d+)$")

# Etapas conocidas del generador, para mapear el progreso si el JSON no llega.
ETAPAS_PORCENTAJE = {
    "Cargando modelo WhisperX": (20, "Cargando modelo WhisperX"),
    "Transcribiendo audio": (25, "Transcribiendo audio"),
    "Transcripci": (30, "Transcribiendo audio"),  # la línea puede venir cortada
    "Alineando timestamps": (35, "Alineando transcripción"),
    "Momentos clave": (50, "Analizando momentos clave"),
    "Clips descargados": (65, "Clips descargados"),
    "Procesando clip": (70, "Procesando clips"),
    "vertical generado": (75, "Generando recorte vertical"),
    "Transcribiendo clip localmente": (80, "Subiendo subtítulos"),
    "quemados": (90, "Subtítulos quemados"),
}

ETAPAS = {
    "generar": "Generando clips del video",
    "textos": "Escribiendo título, descripción y hashtags",
    "lotes": "Preparando el lote de Facebook",
    "publicar": "Subiendo y programando en Facebook",
    "youtube": "Subiendo clips a YouTube",
    "instagram": "Subiendo clip a Instagram",
    "tiktok": "Subiendo clip a TikTok",
    "auth_tiktok": "Conectando TikTok",
    "cola": "Procesando la cola de videos",
}

ZONA = timezone(timedelta(hours=-5))  # Colombia, todo el año


# ---------------------------------------------------------------------------
# JSON del panel (historial, cola, calendario)
# ---------------------------------------------------------------------------

def leer_json(ruta: Path, defecto):
    if not ruta.is_file():
        return defecto
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return defecto


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def cargar_historial() -> list:
    datos = leer_json(config.HISTORIAL_JSON, [])
    return datos if isinstance(datos, list) else []


def guardar_historial(filas: list) -> None:
    guardar_json(config.HISTORIAL_JSON, filas)


def cargar_cola() -> list:
    datos = leer_json(config.COLA_JSON, [])
    return datos if isinstance(datos, list) else []


def guardar_cola(filas: list) -> None:
    guardar_json(config.COLA_JSON, filas)


def cargar_calendario() -> dict:
    datos = leer_json(config.CALENDARIO_JSON, {})
    return datos if isinstance(datos, dict) else {}


def guardar_calendario(datos: dict) -> None:
    guardar_json(config.CALENDARIO_JSON, datos)


# ---------------------------------------------------------------------------
# Miniaturas con ffmpeg
# ---------------------------------------------------------------------------

def crear_miniatura(clip: Path) -> Path | None:
    """Genera un JPG a ~1s del clip. Devuelve la ruta o None si ffmpeg falla."""
    salida = config.MINIATURAS_DIR / f"{clip.stem}.jpg"
    config.MINIATURAS_DIR.mkdir(parents=True, exist_ok=True)
    if salida.is_file() and salida.stat().st_size > 0:
        return salida
    comando = [
        "ffmpeg", "-y", "-ss", "1", "-i", str(clip),
        "-frames:v", "1", "-q:v", "4", str(salida),
    ]
    try:
        proc = subprocess.run(comando, capture_output=True, timeout=60)
        if proc.returncode == 0 and salida.is_file() and salida.stat().st_size > 0:
            return salida
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return None


def crear_miniaturas_para(video_id: str | None = None) -> int:
    """Crea miniaturas para los clips que aún no la tienen. Devuelve cuántas hizo."""
    if not config.CLIPES_DIR.is_dir():
        return 0
    hechas = 0
    patron = f"{video_id}_clip_*_final.mp4" if video_id else "*_clip_*_final.mp4"
    for clip in sorted(config.CLIPES_DIR.glob(patron)):
        mini = crear_miniatura(clip)
        if mini:
            hechas += 1
    return hechas


def ruta_miniatura(nombre_clip: str) -> Path | None:
    """Devuelve la miniatura de un clip si existe."""
    stem = nombre_clip[:-4] if nombre_clip.lower().endswith(".mp4") else nombre_clip
    ruta = config.MINIATURAS_DIR / f"{stem}.jpg"
    return ruta if ruta.is_file() else None


# ---------------------------------------------------------------------------
# Audio del video completo + paquete para Spotify
# ---------------------------------------------------------------------------
# El generador ya deja el MP3 en audio_temporal/. Aquí lo localizamos, leemos
# los datos del video (título, descripción, duración) y armamos un paquete
# cómodo de descargar. Spotify NO tiene API pública para subir audio, así que
# el panel solo prepara los archivos; la subida final es manual.

ID_VIDEO = re.compile(r"^[\w-]{6,64}$")


def ruta_audio(video_id: str) -> Path | None:
    """Ruta del MP3 del video, si existe y el ID es válido."""
    if not ID_VIDEO.match(video_id or ""):
        return None
    ruta = config.AUDIO_DIR / f"{video_id}.mp3"
    return ruta if ruta.is_file() else None


def leer_info_audio(video_id: str) -> dict:
    """Título, descripción y demás datos del video.

    Prioridad: el paquete de Spotify (por si editaste los textos) → el JSON que
    deja el generador junto al MP3 → el historial del panel.

    Un paquete preparado antes de tener los metadatos guarda el ID del video
    como título. Eso cuenta como «sin título» y no tapa los datos buenos que
    lleguen después (por ejemplo, del historial o de YouTube).
    """
    paquete = leer_json(config.SPOTIFY_DIR / video_id / "info.json", {})
    generador = leer_json(config.AUDIO_DIR / f"{video_id}.json", {})
    paquete = paquete if isinstance(paquete, dict) else {}
    generador = generador if isinstance(generador, dict) else {}

    def _campo(nombre: str):
        """Primer valor útil: manda el paquete, salvo que sea un marcador vacío."""
        for fuente in (paquete, generador):
            valor = fuente.get(nombre)
            if not valor:
                continue
            if nombre == "titulo" and str(valor).strip() == video_id:
                continue
            return valor
        return ""

    historial = next((f for f in cargar_historial() if f.get("video_id") == video_id), {})
    return {
        "video_id": video_id,
        "titulo": str(_campo("titulo") or historial.get("titulo") or video_id),
        "descripcion": str(_campo("descripcion") or ""),
        "duracion_segundos": int(_campo("duracion_segundos") or historial.get("duracion_segundos") or 0),
        "url": str(_campo("url") or historial.get("url") or ""),
        "canal": str(_campo("canal") or ""),
        "fecha_subida": str(_campo("fecha_subida") or ""),
        "miniatura": str(_campo("miniatura") or ""),
        "descargado": int(_campo("descargado") or 0),
    }


def paquete_spotify(video_id: str) -> dict | None:
    """Datos del paquete ya preparado, o None si todavía no existe."""
    if not ID_VIDEO.match(video_id or ""):
        return None
    carpeta = config.SPOTIFY_DIR / video_id
    audio = carpeta / "audio.mp3"
    info = leer_json(carpeta / "info.json", {})
    if not audio.is_file() or not isinstance(info, dict) or not info:
        return None
    return {
        "video_id": video_id,
        "titulo": str(info.get("titulo") or ""),
        "descripcion": str(info.get("descripcion") or ""),
        "duracion_segundos": int(info.get("duracion_segundos") or 0),
        "canal": str(info.get("canal") or ""),
        "url": str(info.get("url") or ""),
        "tamano": audio.stat().st_size,
        "audio_url": f"/api/spotify/paquete/{video_id}/audio",
        "carpeta": str(carpeta),
        "preparado": str(info.get("preparado") or ""),
    }


def listar_audios() -> dict:
    """Todos los MP3 descargados, con sus datos y si ya tienen paquete de Spotify."""
    audios = []
    if config.AUDIO_DIR.is_dir():
        for audio in config.AUDIO_DIR.glob("*.mp3"):
            video_id = audio.stem
            if not ID_VIDEO.match(video_id):
                continue
            datos = leer_info_audio(video_id)
            paquete = paquete_spotify(video_id)
            datos.update({
                "audio": audio.name,
                "tamano": audio.stat().st_size,
                "audio_url": f"/api/spotify/audio/{video_id}",
                "preparado": bool(paquete),
                "paquete": paquete,
                "modificado": datetime.fromtimestamp(audio.stat().st_mtime, ZONA).isoformat(timespec="minutes"),
            })
            audios.append(datos)
    audios.sort(key=lambda a: a.get("modificado") or "", reverse=True)
    return {"audios": audios, "total": len(audios)}


def preparar_spotify(video_id: str, titulo: str | None = None, descripcion: str | None = None) -> dict:
    """Copia/enlaza el MP3 a la carpeta de Spotify y guarda sus textos.

    El enlace duro evita duplicar el archivo (los MP3 pesan decenas de MB).
    Si el sistema de archivos no lo permite, se copia.
    """
    audio = ruta_audio(video_id)
    if audio is None:
        raise ValueError("No encontré el audio de ese video. Genera los clips primero.")

    datos = leer_info_audio(video_id)
    if titulo is not None and str(titulo).strip():
        datos["titulo"] = str(titulo).strip()
    if descripcion is not None:
        datos["descripcion"] = str(descripcion).strip()

    carpeta = config.SPOTIFY_DIR / video_id
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "audio.mp3"
    if not destino.is_file() or destino.stat().st_size != audio.stat().st_size:
        try:
            if destino.is_file():
                destino.unlink()
            os.link(audio, destino)  # enlace duro: mismo archivo, sin gastar el doble
        except OSError:
            shutil.copy2(audio, destino)

    (carpeta / "titulo.txt").write_text(datos["titulo"], encoding="utf-8")
    (carpeta / "descripcion.txt").write_text(datos["descripcion"], encoding="utf-8")
    datos["preparado"] = datetime.now(ZONA).isoformat(timespec="minutes")
    (carpeta / "info.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        **datos,
        "tamano": destino.stat().st_size,
        "audio_url": f"/api/spotify/paquete/{video_id}/audio",
        "carpeta": str(carpeta),
    }


def buscar_info_video(video_id: str) -> dict:
    """Rellena título/descripción de audios viejos consultando YouTube.

    Usa el intérprete del generador porque es el que tiene yt-dlp instalado.
    Si falla (sin internet, cookies, etc.) devuelve lo que ya tuviéramos.
    """
    if not ID_VIDEO.match(video_id or ""):
        return leer_info_audio(video_id)

    destino = config.AUDIO_DIR / f"{video_id}.json"
    if destino.is_file():
        return leer_info_audio(video_id)

    script = config.PANEL_DIR / "info_video.py"
    if not script.is_file() or not config.GENERADOR_PY.is_file():
        return leer_info_audio(video_id)

    salida = config.AUDIO_DIR / f"{video_id}.info.tmp.json"
    comando = [str(config.GENERADOR_PY), str(script), video_id, str(salida)]
    try:
        proceso = subprocess.run(
            comando,
            cwd=str(config.GENERADOR_DIR),
            capture_output=True,
            timeout=120,
            creationflags=CREACION_GRUPO,
        )
        if proceso.returncode != 0 or not salida.is_file():
            return leer_info_audio(video_id)
        datos = json.loads(salida.read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            return leer_info_audio(video_id)
        datos.setdefault("video_id", video_id)
        datos.setdefault("descargado", int(datetime.now().timestamp()))
        destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return leer_info_audio(video_id)
    finally:
        try:
            salida.unlink(missing_ok=True)
        except OSError:
            pass

    return leer_info_audio(video_id)


# ---------------------------------------------------------------------------
# Progreso del generador
# ---------------------------------------------------------------------------

def leer_progreso_generador() -> dict | None:
    """JSON que escribe el generador_clips.py en cada etapa."""
    if not config.PROGRESO_GENERADOR.is_file():
        return None
    try:
        datos = json.loads(config.PROGRESO_GENERADOR.read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            return None
        return {
            "etapa": str(datos.get("etapa") or ""),
            "porcentaje": int(datos.get("porcentaje") or 0),
            "mensaje": str(datos.get("mensaje") or ""),
        }
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def progreso_desde_linea(linea: str) -> tuple[int, str] | None:
    """Si la línea del generador marca una etapa conocida, devuelve (%, mensaje)."""
    for marca, (pct, mensaje) in ETAPAS_PORCENTAJE.items():
        if marca in linea:
            return pct, mensaje
    return None


# ---------------------------------------------------------------------------
# Estado en vivo
# ---------------------------------------------------------------------------

@dataclass
class Estado:
    """Lo que la interfaz necesita saber en cada momento."""

    etapa: str | None = None
    estado: str = "inactivo"  # inactivo | ejecutando | listo | error | cancelado
    lineas: list = field(default_factory=list)
    clips: list = field(default_factory=list)
    mensaje: str = ""
    url: str = ""
    video_id: str = ""
    duracion: int = 0
    titulo_video: str = ""
    progreso: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {
            "etapa": self.etapa,
            "estado": self.estado,
            "lineas": self.lineas[-400:],
            "clips": self.clips,
            "mensaje": self.mensaje,
            "url": self.url,
            "video_id": self.video_id,
            "duracion": self.duracion,
            "titulo_video": self.titulo_video,
            "progreso": self.progreso,
        }


class Trabajo:
    """Un proceso a la vez + una cola de URLs que se van soltando solas."""

    def __init__(self) -> None:
        self.estado = Estado()
        self.proceso: asyncio.subprocess.Process | None = None
        self.oyentes: set[asyncio.Queue] = set()
        self._tarea_actual: asyncio.Task | None = None

    # --- log en vivo ---

    def suscribir(self) -> asyncio.Queue:
        """Registra a quien quiere ver el log. La cola trae primero lo ya escrito."""
        cola: asyncio.Queue = asyncio.Queue()
        for linea in self.estado.lineas:
            cola.put_nowait({"tipo": "linea", "texto": linea})
        cola.put_nowait({"tipo": "estado", "datos": self.estado.como_dict()})
        cola.put_nowait({"tipo": "cola", "datos": cargar_cola()})
        self.oyentes.add(cola)
        return cola

    def desuscribir(self, cola: asyncio.Queue) -> None:
        self.oyentes.discard(cola)

    def emitir(self, linea: str) -> None:
        self.estado.lineas.append(linea)
        # El generador puede escribir el progreso en su JSON; lo refrescamos.
        progreso = leer_progreso_generador()
        if progreso:
            self.estado.progreso = progreso
        else:
            estimado = progreso_desde_linea(linea)
            if estimado:
                pct, mensaje = estimado
                self.estado.progreso = {"etapa": "log", "porcentaje": pct, "mensaje": mensaje}
        for cola in list(self.oyentes):
            try:
                cola.put_nowait({"tipo": "linea", "texto": linea})
                cola.put_nowait({"tipo": "progreso", "datos": self.estado.progreso})
            except Exception:
                pass

    def _avisar_estado(self) -> None:
        """Manda el estado completo a quien este escuchando."""
        for cola in list(self.oyentes):
            try:
                cola.put_nowait({"tipo": "estado", "datos": self.estado.como_dict()})
            except Exception:
                pass

    def _avisar_cola(self) -> None:
        datos = cargar_cola()
        for cola in list(self.oyentes):
            try:
                cola.put_nowait({"tipo": "cola", "datos": datos})
            except Exception:
                pass

    # --- ejecucion ---

    def en_ejecucion(self) -> bool:
        return self.estado.estado == "ejecutando"

    async def ejecutar(
        self,
        etapa: str,
        comando: list,
        cwd: Path,
        entorno: dict | None = None,
    ) -> Estado:
        """Corre un subproceso y transmite su salida linea por linea."""
        if self.en_ejecucion():
            raise RuntimeError("Ya hay un proceso corriendo.")

        self.estado = Estado(etapa=etapa, estado="ejecutando")
        if config.PROGRESO_GENERADOR.is_file():
            try:
                config.PROGRESO_GENERADOR.unlink()
            except OSError:
                pass
        self._avisar_estado()

        try:
            proceso = await asyncio.create_subprocess_exec(
                *comando,
                cwd=str(cwd),
                env=entorno,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=CREACION_GRUPO,
            )
        except FileNotFoundError as error:
            self.estado.estado = "error"
            self.estado.mensaje = f"No se encontró el intérprete: {error}"
            self._avisar_estado()
            return self.estado

        self.proceso = proceso
        try:
            proceso.stdin.close()
        except Exception:
            pass

        lector = asyncio.create_task(self._transmitir(etapa))
        limite = config.TIEMPO_MAXIMO_ETAPA.get(etapa)  # Tope de tiempo para esta etapa (si lo tiene).
        try:
            if limite:  # Si la etapa tiene tope (típicamente al conectar con servicios externos)...
                codigo = await asyncio.wait_for(proceso.wait(), timeout=limite)  # ...esperamos con límite.
            else:  # Si no tiene tope...
                codigo = await proceso.wait()  # ...esperamos lo que haga falta.
        except asyncio.TimeoutError:  # La etapa se quedó colgada más de la cuenta.
            await self._matar_arbol(proceso)  # Detenemos el proceso y sus hijos.
            await lector  # Terminamos de leer lo que alcanzó a salir.
            self.proceso = None
            self.estado.estado = "error"
            self.estado.mensaje = (
                f"{ETAPAS.get(etapa, etapa)} tardó demasiado y se detuvo solo. "
                "El panel sigue disponible: revisa, corrige y vuelve a intentarlo cuando quieras."
            )
            self._avisar_estado()
            return self.estado
        await lector

        self.proceso = None
        if self.estado.estado == "cancelado":
            self.estado.mensaje = "Cancelado."
        elif codigo == 0:
            self.estado.estado = "listo"
            self.estado.mensaje = ETAPAS.get(etapa, "Listo.")
            self.estado.progreso = {"etapa": etapa, "porcentaje": 100, "mensaje": "Completado"}
        else:
            self.estado.estado = "error"
            self.estado.mensaje = f"El proceso terminó con código {codigo}."

        self._avisar_estado()
        return self.estado

    async def _transmitir(self, etapa: str) -> None:
        """Lee la salida del subproceso linea a linea hasta que se cierra."""
        while True:
            try:
                linea = await self.proceso.stdout.readline()
            except Exception:
                break
            if not linea:
                break
            texto = linea.decode("utf-8", errors="replace").rstrip()
            if not texto:
                continue

            # El generador anuncia datos útiles en líneas clave.
            m_id = REGEX_VIDEO_ID.match(texto)
            if m_id:
                self.estado.video_id = m_id.group(1).strip()
            m_dur = REGEX_DURACION.match(texto)
            if m_dur:
                self.estado.duracion = int(m_dur.group(1))
            m_tit = REGEX_TITULO.match(texto)
            if m_tit:
                self.estado.titulo_video = m_tit.group(1).strip()

            coincidencia = REGRESO_CLIP.search(texto)
            if coincidencia:
                ruta = coincidencia.group(1).strip()
                if ruta not in self.estado.clips:
                    self.estado.clips.append(ruta)

            self.emitir(texto)

        # Al cerrar el generador, refrescamos el progreso final del JSON.
        if etapa == "generar":
            progreso = leer_progreso_generador()
            if progreso:
                self.estado.progreso = progreso

    # --- cancelacion ---

    async def _matar_arbol(self, proceso) -> None:
        """Mata un subproceso y todo su arbol (python puede tener ffmpeg debajo)."""
        if sys.platform == "win32":
            await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proceso.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        else:
            proceso.kill()
        try:
            await proceso.wait()  # Confirmamos que ya terminó.
        except Exception:  # noqa: BLE001 — si ya no existe, no pasa nada.
            pass

    async def cancelar(self) -> None:
        """Mata el proceso y todo su arbol (python puede tener ffmpeg debajo)."""
        if not self.proceso:
            return
        self.estado.estado = "cancelado"
        await self._matar_arbol(self.proceso)
        self.proceso = None
        self._avisar_estado()


# ---------------------------------------------------------------------------
# Validación de URL de YouTube
# ---------------------------------------------------------------------------

PATRONES_YOUTUBE = [
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=)([\w-]{6,})"),
    re.compile(r"(?:youtu\.be/)([\w-]{6,})"),
    re.compile(r"(?:youtube\.com/shorts/)([\w-]{6,})"),
    re.compile(r"(?:youtube\.com/embed/)([\w-]{6,})"),
    re.compile(r"(?:youtube\.com/live/)([\w-]{6,})"),
    re.compile(r"(?:youtube\.com/v/)([\w-]{6,})"),
]


def extraer_video_id(url: str) -> str | None:
    """Saca el ID de un enlace de YouTube válido. None si no es de YouTube."""
    url = (url or "").strip()
    if not url:
        return None
    for patron in PATRONES_YOUTUBE:
        m = patron.search(url)
        if m:
            return m.group(1)
    return None


def es_url_youtube(url: str) -> bool:
    return extraer_video_id(url) is not None


# ---------------------------------------------------------------------------
# Cola de videos
# ---------------------------------------------------------------------------

def cola_agregar(url: str) -> dict:
    """Agrega una URL a la cola (o la arranca si no hay nada corriendo)."""
    video_id = extraer_video_id(url)
    if not video_id:
        raise ValueError("Esa URL no parece un video de YouTube válido.")
    fila = {
        "id": uuid.uuid4().hex[:12],
        "url": url.strip(),
        "video_id": video_id,
        "creado": datetime.now(ZONA).isoformat(timespec="minutes"),
        "estado": "pendiente",  # pendiente | ejecutando | listo | error | cancelado
    }
    filas = cargar_cola()
    # Evitamos duplicados exactos en pendientes.
    if any(f["url"] == fila["url"] and f["estado"] == "pendiente" for f in filas):
        raise ValueError("Esa URL ya está en la cola.")
    filas.append(fila)
    guardar_cola(filas)
    return fila


def cola_quitar(id_fila: str) -> bool:
    filas = cargar_cola()
    nuevos = [f for f in filas if f["id"] != id_fila]
    if len(nuevos) == len(filas):
        return False
    guardar_cola(nuevos)
    return True


def cola_marcar(id_fila: str, estado: str) -> None:
    filas = cargar_cola()
    for f in filas:
        if f["id"] == id_fila:
            f["estado"] = estado
    guardar_cola(filas)


def cola_siguiente_pendiente() -> dict | None:
    for f in cargar_cola():
        if f["estado"] == "pendiente":
            return f
    return None


# ---------------------------------------------------------------------------
# Historial de videos procesados
# ---------------------------------------------------------------------------

def registrar_historial(url: str, video_id: str, duracion: int, titulo: str, clips: list) -> dict:
    """Anota en el historial del panel un video que se procesó (o intentó)."""
    filas = cargar_historial()
    # Si ya existe una entrada para este video_id hoy, la actualizamos.
    hoy = datetime.now(ZONA).date().isoformat()
    entrada = {
        "id": uuid.uuid4().hex[:12],
        "url": url,
        "video_id": video_id,
        "titulo": titulo,
        "duracion_segundos": int(duracion or 0),
        "fecha": datetime.now(ZONA).isoformat(timespec="minutes"),
        "clips_generados": len(clips),
        "archivos": [Path(c).name for c in clips],
        "miniaturas": 0,
    }
    # Reemplazamos la última entrada del mismo video_id si es del mismo día.
    for i, fila in enumerate(filas):
        if fila.get("video_id") == video_id and str(fila.get("fecha", ""))[:10] == hoy:
            entrada["id"] = fila.get("id", entrada["id"])
            filas[i] = entrada
            guardar_historial(filas)
            return entrada
    filas.insert(0, entrada)
    # Mantenemos un tope razonable.
    guardar_historial(filas[:200])
    return entrada


def historial_marcar_miniaturas(video_id: str, cantidad: int) -> None:
    filas = cargar_historial()
    for fila in filas:
        if fila.get("video_id") == video_id:
            fila["miniaturas"] = cantidad
    guardar_historial(filas)


# ---------------------------------------------------------------------------
# Resumen de clips (para la vista general)
# ---------------------------------------------------------------------------

def resumen() -> dict:
    """Lo que la página muestra al abrir: cuántos clips hay, en qué estado están y sus textos."""
    clips = sorted(config.CLIPES_DIR.glob("*_clip_*_final.mp4")) if config.CLIPES_DIR.is_dir() else []
    registro = leer_json(config.REGISTRO_META, {})
    registro_yt = leer_json(config.REGISTRO_YOUTUBE, {})
    registro_tt = leer_json(config.REGISTRO_TIKTOK, {})
    registro_ig = leer_json(config.REGISTRO_INSTAGRAM, {})

    filas = []
    for clip in clips:
        estado = registro.get(clip.name, {})
        textos = all(
            config.ruta_texto(clip.name, campo).is_file()
            and config.ruta_texto(clip.name, campo).read_text(encoding="utf-8").strip()
            for campo in config.CAMPOS_TEXTO
        )
        if estado.get("facebook_scheduled_at") or estado.get("facebook_id"):
            situacion = "programado"
        elif textos:
            situacion = "listo"
        else:
            situacion = "sin textos"
        mini = ruta_miniatura(clip.name)
        datos_texto = config.leer_textos(clip.name) if textos else {}
        filas.append({
            "archivo": clip.name,
            "video_id": clip.stem.split("_clip_")[0],
            "estado": situacion,
            "fecha": estado.get("facebook_scheduled_at", ""),
            "miniatura": f"/api/miniatura/{clip.name}" if mini else "",
            "con_textos": textos,
            "titulo": datos_texto.get("titulo", ""),
            "descripcion": datos_texto.get("descripcion", ""),
            "hashtags": datos_texto.get("hashtags", ""),
            "calificacion": config.leer_calificacion(clip.name),
            "en_facebook": bool(estado.get("facebook_id") or estado.get("facebook_scheduled_at")),
            "en_youtube": clip.name in registro_yt or clip.stem in registro_yt,
            "en_tiktok": clip.name in registro_tt,
            "en_instagram": clip.name in registro_ig or clip.stem in registro_ig,
        })

    lote = leer_json(config.LOTE_PENDIENTE, {})
    return {
        "clips": filas,
        "total": len(filas),
        "lote_pendiente": config.LOTE_PENDIENTE.is_file(),
        "lote": lote if isinstance(lote, dict) else {},
    }


# ---------------------------------------------------------------------------
# Calendario de publicación
# ---------------------------------------------------------------------------

def _fecha_legible(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %I:%M %p").lstrip("0").replace(" 0", " ")
    except ValueError:
        return iso or "—"


def _fecha_dt(iso: str) -> datetime | None:
    """Convierte un ISO guardado a hora de Colombia, o None si no se puede leer."""
    if not iso:
        return None
    try:
        momento = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZONA)
    return momento.astimezone(ZONA)


def _dias_ocupados() -> set:
    """Días (fecha) que ya tienen un video agendado en cualquier plataforma."""
    ocupados = set()
    for ruta, claves in (
        (config.REGISTRO_META, ("facebook_scheduled_at", "publish_at")),
        (config.REGISTRO_YOUTUBE, ("publish_at",)),
        (config.REGISTRO_TIKTOK, ("schedule_time", "publish_at", "created_time")),
    ):
        for datos in leer_json(ruta, {}).values():
            if not isinstance(datos, dict):
                continue
            for clave in claves:
                momento = _fecha_dt(datos.get(clave, ""))
                if momento is not None:
                    ocupados.add(momento.date())
                    break
        if config.REGISTRO_INSTAGRAM.is_file():
            for datos in leer_json(config.REGISTRO_INSTAGRAM, {}).values():
                if isinstance(datos, dict):
                    momento = _fecha_dt(datos.get("publicado_en", ""))
                    if momento is not None:
                        ocupados.add(momento.date())
    return ocupados


def _proximos_turnos(cantidad: int) -> list:
    """Los próximos días libres a las 7 p. m. (empieza mañana), saltando días ocupados."""
    ocupados = _dias_ocupados()
    dia = datetime.now(ZONA).date() + timedelta(days=1)
    turnos = []
    while len(turnos) < cantidad:
        if dia not in ocupados:
            turnos.append(datetime.combine(dia, datetime.min.time()).replace(hour=19, minute=0).isoformat(timespec="minutes"))
        dia += timedelta(days=1)
    return turnos


def calendario() -> dict:
    """Calendario único por clip con todas las plataformas (Facebook, YouTube, TikTok, Instagram)."""
    ahora = datetime.now(ZONA)
    lote = leer_json(config.LOTE_PENDIENTE, {})
    propias = cargar_calendario()

    # clip -> datos acumulados
    filas: dict[str, dict] = {}

    def agregar(clip: str, fecha: str, plataforma: str, estado: str, titulo: str = "") -> None:
        """Suma una presencia de un clip en una plataforma. La mejor fecha gana."""
        clip = clip[:-4] if clip.lower().endswith(".mp4") else clip
        fila = filas.setdefault(clip, {"fechas": [], "plataformas": set(), "estado": "nuevo", "titulo": "", "fecha_plataforma": ""})
        if titulo and not fila["titulo"]:
            fila["titulo"] = titulo
        if fecha:
            fila["fechas"].append({"fecha": fecha, "plataforma": plataforma})
        fila["plataformas"].add(plataforma)
        if estado in ("programado", "publicado") and fila["estado"] in ("nuevo", "pendiente"):
            fila["estado"] = estado
        elif estado == "pendiente" and fila["estado"] == "nuevo":
            fila["estado"] = estado

    # Ya programadas / publicadas en Facebook
    for nombre, datos in leer_json(config.REGISTRO_META, {}).items():
        if not isinstance(datos, dict):
            continue
        fecha = datos.get("facebook_scheduled_at") or datos.get("publish_at") or ""
        if datos.get("facebook_id") or datos.get("facebook_scheduled_at") or datos.get("video_id"):
            estado = "programado" if fecha else "publicado"
            agregar(nombre, fecha, "facebook", estado)

    # Ya programadas en YouTube
    for nombre, datos in leer_json(config.REGISTRO_YOUTUBE, {}).items():
        if not isinstance(datos, dict):
            continue
        agregar(nombre, datos.get("publish_at", ""), "youtube", "programado")

    # Ya publicadas en TikTok e Instagram
    for ruta, claves in ((config.REGISTRO_TIKTOK, ("schedule_time", "publish_at", "created_time")),
                         (config.REGISTRO_INSTAGRAM, ("publicado_en",))):
        for nombre, datos in leer_json(ruta, {}).items():
            if not isinstance(datos, dict):
                continue
            fecha = next((datos.get(c, "") for c in claves if datos.get(c)), "")
            agregar(nombre, fecha, "instagram" if ruta == config.REGISTRO_INSTAGRAM else "tiktok", "publicado")

    # Pendientes del lote de Facebook (aún no subidos)
    if isinstance(lote, dict):
        for clip in lote.get("clips", []):
            agregar(clip.get("video", ""), clip.get("programar_para", ""), "facebook",
                    "pendiente" if clip.get("programar_para") else "nuevo", clip.get("titulo", ""))

    # Anotaciones propias del panel: solo para clips sin fecha real en ninguna plataforma
    for clip, fecha in propias.items():
        clave = clip[:-4] if clip.lower().endswith(".mp4") else clip
        fila = filas.get(clave)
        if fila is None or (not fila["fechas"] and fecha):
            agregar(clip, fecha, "facebook", "pendiente")

    # Clips nuevos: tienen textos pero aún no están en ninguna plataforma
    if config.CLIPES_DIR.is_dir():
        for clip_path in sorted(config.CLIPES_DIR.glob("*_clip_*_final.mp4")):
            nombre = clip_path.name
            if nombre in filas or nombre[:-4] in filas:
                continue
            if not config.clip_tiene_textos(nombre):
                continue
            datos_texto = config.leer_textos(nombre)
            agregar(nombre, "", "disponible", "nuevo", datos_texto.get("titulo", ""))

    entradas = []
    for clip, fila in filas.items():
        mejor = ""
        mejor_plataforma = ""
        if fila["fechas"]:
            fechas_dt = [(v, _fecha_dt(v["fecha"])) for v in fila["fechas"]]
            fechas_dt = [(v, dt) for v, dt in fechas_dt if dt is not None]
            if fechas_dt:
                mejor_dt = max(dt for _, dt in fechas_dt)
                mejor = mejor_dt.isoformat(timespec="minutes")
                mejor_plataforma = next(v["plataforma"] for v, dt in fechas_dt if dt == mejor_dt)
        # Ocultamos clips cuyas fechas ya pasaron; los nuevos sin fecha se quedan.
        mejor_dt = _fecha_dt(mejor)
        if mejor_dt is not None and mejor_dt.date() < ahora.date():
            continue
        entradas.append({
            "clip": clip,
            "titulo": fila["titulo"],
            "fecha": mejor,
            "fecha_legible": _fecha_legible(mejor) if mejor else "—",
            "estado": fila["estado"],
            "plataformas": sorted(fila["plataformas"]),
            "plataforma": mejor_plataforma,
        })

    entradas.sort(key=lambda e: (e["fecha"] or "9999", e["clip"].casefold()))
    return {"entradas": entradas, "total": len(entradas)}


def video_hoy() -> dict:
    """El Reel que tocaría publicar hoy en Instagram y si ya se publicó el de hoy."""
    ahora = datetime.now(ZONA)
    hoy = ahora.date()
    registro = leer_json(config.REGISTRO_INSTAGRAM, {})
    ya_publicado_hoy = False
    for datos in registro.values():
        if not isinstance(datos, dict):
            continue
        momento = _fecha_dt(datos.get("publicado_en", ""))
        if momento is not None and momento.date() == hoy:
            ya_publicado_hoy = True
            break

    pendientes = []
    if config.CLIPES_DIR.is_dir():
        for clip_path in sorted(config.CLIPES_DIR.glob("*_clip_*_final.mp4")):
            nombre = clip_path.name
            if nombre in registro:
                continue
            if not config.clip_tiene_textos(nombre):
                continue
            textos = config.leer_textos(nombre)
            pendientes.append({"clip": nombre, "titulo": (textos or {}).get("titulo", "")})

    return {
        "hoy": hoy.isoformat(),
        "fecha_legible": hoy.strftime("%d/%m/%Y"),
        "ya_publicado_hoy": ya_publicado_hoy,
        "pendientes": len(pendientes),
        "siguiente": pendientes[0] if pendientes else None,
    }


def calendario_mover(clip: str, nueva_fecha: str) -> dict:
    """Cambia la fecha de un clip pendiente en el lote de Facebook (y en el panel)."""
    try:
        fecha_pedida = datetime.fromisoformat(nueva_fecha)
    except ValueError as error:
        raise ValueError("La fecha debe venir en formato AAAA-MM-DDTHH:MM") from error
    if fecha_pedida.tzinfo is None:
        fecha_pedida = fecha_pedida.replace(tzinfo=ZONA)
    dia = fecha_pedida.astimezone(ZONA).date()

    # No permitimos dos clips el mismo día en otra plataforma.
    for ruta in (config.REGISTRO_META, config.REGISTRO_YOUTUBE, config.REGISTRO_TIKTOK):
        for nombre, datos in leer_json(ruta, {}).items():
            if not isinstance(datos, dict):
                continue
            for clave in ("facebook_scheduled_at", "publish_at", "schedule_time", "created_time"):
                momento = _fecha_dt(datos.get(clave, ""))
                if momento is not None and momento.date() == dia and nombre != clip:
                    raise ValueError(
                        f"El {dia.strftime('%d/%m/%Y')} ya tiene agendado «{nombre}» en otra plataforma. "
                        "Elige otro día o cambia la hora."
                    )

    tocado = False
    lote = leer_json(config.LOTE_PENDIENTE, {})
    if isinstance(lote, dict) and lote.get("clips"):
        for fila in lote["clips"]:
            if fila.get("video") == clip:
                fila["programar_para"] = nueva_fecha
                tocado = True
        if tocado:
            guardar_json(config.LOTE_PENDIENTE, lote)
            # Reescribimos el resumen legible.
            if config.LOTE_RESUMEN.is_file() or True:
                lineas = ["REELS QUE SE PROGRAMARÁN EN FACEBOOK", ""]
                for fila in lote["clips"]:
                    fecha = fila.get("programar_para", "")
                    lineas.append(f"{fila.get('video','')}  →  {_fecha_legible(fecha)}")
                    lineas.append(f"   Título: {fila.get('titulo','')}")
                    lineas.append("")
                config.LOTE_RESUMEN.write_text("\n".join(lineas), encoding="utf-8")

    propias = cargar_calendario()
    propias[clip] = nueva_fecha
    guardar_calendario(propias)

    return {"clip": clip, "fecha": nueva_fecha, "fecha_legible": _fecha_legible(nueva_fecha), "lote_tocado": tocado}


def calendario_reordenar() -> dict:
    """Reasigna fechas (mañana en adelante, 7 p. m.) a los pendientes, saltando días ocupados."""
    lote = leer_json(config.LOTE_PENDIENTE, {})
    if not isinstance(lote, dict) or not lote.get("clips"):
        raise ValueError("No hay lote pendiente con fechas para reordenar.")

    turnos = _proximos_turnos(len(lote["clips"]))
    for fila, turno in zip(lote["clips"], turnos):
        fila["programar_para"] = turno
    guardar_json(config.LOTE_PENDIENTE, lote)

    propias = {fila["video"]: fila["programar_para"] for fila in lote["clips"]}
    guardar_calendario(propias)

    lineas = ["REELS QUE SE PROGRAMARÁN EN FACEBOOK", ""]
    for fila in lote["clips"]:
        lineas.append(f"{fila.get('video','')}  →  {_fecha_legible(fila.get('programar_para',''))}")
        lineas.append(f"   Título: {fila.get('titulo','')}")
        lineas.append("")
    config.LOTE_RESUMEN.write_text("\n".join(lineas), encoding="utf-8")

    return {"reordenados": len(lote["clips"])}


# ---------------------------------------------------------------------------
# Etapas (atajos)
# ---------------------------------------------------------------------------

async def generar_clips(trabajo: Trabajo, url: str) -> Estado:
    return await trabajo.ejecutar(
        etapa="generar",
        comando=[str(config.GENERADOR_PY), str(config.GENERADOR_SCRIPT), "--url", url],
        cwd=config.GENERADOR_DIR,
        entorno=config.entorno_generador(),
    )


async def generar_textos(trabajo: Trabajo) -> Estado:
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="textos",
        comando=[
            str(config.PUBLICADOR_PY), str(config.TEXTOS_SCRIPT),
            "--videos", str(config.CLIPES_DIR),
            "--textos", str(config.TEXTOS_DIR),
        ],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def preparar_lote(trabajo: Trabajo, cantidad: int = 5) -> Estado:
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="lotes",
        comando=[
            str(config.PUBLICADOR_PY), str(config.PUBLICAR_SCRIPT),
            "preparar", "--cantidad", str(cantidad),
        ],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def publicar(trabajo: Trabajo) -> Estado:
    """Sube de verdad. A diferencia de los otros, este toca la red."""
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="publicar",
        comando=[str(config.PUBLICADOR_PY), str(config.PUBLICAR_SCRIPT), "programar"],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def subir_youtube(trabajo: Trabajo) -> Estado:
    """Sube a YouTube los clips que aún no estén en el registro. Usa el mismo .env."""
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="youtube",
        comando=[
            str(config.PUBLICADOR_PY), str(config.YOUTUBE_SCRIPT),
            "--videos", str(config.CLIPES_DIR),
            "--textos", str(config.TEXTOS_DIR),
        ],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def subir_instagram(trabajo: Trabajo, clip: str) -> Estado:
    """Sube un clip a Instagram: Firebase Hosting + Graph API."""
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="instagram",
        comando=[
            str(config.PUBLICADOR_PY), str(config.INSTAGRAM_SCRIPT),
            "--clip", clip,
        ],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def subir_instagram_lote(trabajo: Trabajo) -> Estado:
    """Publica el Reel del día (máximo uno); nada si hoy ya se publicó o no hay pendientes."""
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="instagram",
        comando=[
            str(config.PUBLICADOR_PY),
            str(config.PUBLICADOR_DIR / "publicar_instagram_diario.py"),
        ],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def subir_tiktok(trabajo: Trabajo, clip: str) -> Estado:
    """Sube un clip a TikTok con la Content Posting API."""
    if not config.TOKEN_TIKTOK.is_file():
        return Estado(
            etapa="tiktok",
            estado="error",
            mensaje="Primero conecta TikTok desde la sección de credenciales.",
        )
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="tiktok",
        comando=[
            str(config.PUBLICADOR_PY), str(config.TIKTOK_SCRIPT),
            "--clip", clip,
        ],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def conectar_tiktok(trabajo: Trabajo) -> Estado:
    """Abre el flujo OAuth de TikTok en el servidor local para autorizar la cuenta."""
    if not config.AUTH_TIKTOK_SCRIPT.is_file():
        return Estado(
            etapa="auth_tiktok",
            estado="error",
            mensaje=f"No existe el script de autorización: {config.AUTH_TIKTOK_SCRIPT}",
        )
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="auth_tiktok",
        comando=[str(config.PUBLICADOR_PY), str(config.AUTH_TIKTOK_SCRIPT)],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


async def conectar_youtube(trabajo: Trabajo) -> Estado:
    """Abre el flujo OAuth de Google en el servidor local para autorizar YouTube."""
    if not config.AUTH_YOUTUBE_SCRIPT.is_file():
        return Estado(
            etapa="auth_youtube",
            estado="error",
            mensaje=f"No existe el script de autorización: {config.AUTH_YOUTUBE_SCRIPT}",
        )
    entorno = config.entorno_publicador()
    return await trabajo.ejecutar(
        etapa="auth_youtube",
        comando=[str(config.PUBLICADOR_PY), str(config.AUTH_YOUTUBE_SCRIPT)],
        cwd=config.PUBLICADOR_DIR,
        entorno=entorno,
    )


# ---------------------------------------------------------------------------
# Post-proceso tras generar: miniaturas + historial
# ---------------------------------------------------------------------------

def post_proceso_generar(url: str, estado: Estado, trabajo: Trabajo | None = None) -> None:
    """Después de que el generador termina: miniaturas, historial y audio de Spotify."""
    video_id = estado.video_id or extraer_video_id(url) or ""
    clips = list(estado.clips)
    # Si el log no trajo las rutas, las buscamos por prefijo del video_id.
    if not clips and video_id and config.CLIPES_DIR.is_dir():
        clips = [str(c) for c in sorted(config.CLIPES_DIR.glob(f"{video_id}_clip_*_final.mp4"))]

    if estado.estado == "listo":
        miniaturas = crear_miniaturas_para(video_id or None)
        if video_id:
            historial_marcar_miniaturas(video_id, miniaturas)
        if video_id or clips:
            registrar_historial(
                url=url,
                video_id=video_id,
                duracion=estado.duracion,
                titulo=estado.titulo_video,
                clips=clips,
            )
            # Anotamos cuántas miniaturas hizo.
            if video_id and miniaturas:
                historial_marcar_miniaturas(video_id, miniaturas)
    else:
        # Aunque falle, queremos saber qué se intentó.
        if video_id or url:
            registrar_historial(
                url=url,
                video_id=video_id,
                duracion=estado.duracion,
                titulo=estado.titulo_video,
                clips=clips,
            )

    # El audio se descarga antes que los clips: aunque el proceso falle después,
    # lo guardamos igual en la carpeta de Spotify para no perderlo.
    if video_id and ruta_audio(video_id):
        try:
            preparar_spotify(video_id, titulo=estado.titulo_video or None)
            if trabajo is not None:
                trabajo.emitir(f"🎵 Audio guardado para Spotify: {video_id}.mp3")
        except Exception as error:  # noqa: BLE001 — no debe tumbar el post-proceso
            if trabajo is not None:
                trabajo.emitir(f"⚠ No pude preparar el audio de Spotify: {error}")
