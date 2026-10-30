# Automatización de clips

Pipeline para convertir un video largo (YouTube, entrevista, podcast) en clips
cortos con título, descripción y hashtags, y publicarlos programados en
**Facebook, Instagram, YouTube y TikTok**.

El repositorio reúne dos herramientas que trabajan juntas:

| Carpeta | Qué hace | Stack |
| --- | --- | --- |
| `panel/` | Panel web local: pegas una URL, elige dónde cortar y programa todo con botones | FastAPI + Uvicorn |
| `publicador/` | Genera los textos con Gemini y sube/programa los clips en cada red | Flask + APIs de Meta, Google y TikTok |

```
                 ┌──────────────────────────┐
   URL de video →│  generador de clips      │  (proyecto aparte, no está en este repo:
                 │  descarga, transcribe y  │   pesa varios GB por torch/WhisperX)
                 │  corta los clips         │
                 └───────────┬──────────────┘
                             │  clips_finales/*.mp4  +  textos_clips/*.txt
                             ▼
                 ┌──────────────────────────┐
                 │  panel/ (FastAPI)        │  orquesta las etapas y muestra el avance
                 └───────────┬──────────────┘
                             │  ejecuta los scripts como subprocesos
                             ▼
                 ┌──────────────────────────┐
                 │  publicador/             │  Gemini → textos
                 │                          │  Meta → Facebook + Reels
                 │                          │  Google → YouTube
                 │                          │  TikTok → TikTok
                 └──────────────────────────┘
```

## Estructura del repositorio

```
automatizacion-clips/
├── abrir_panel.bat          Arranca el panel en Windows (doble clic)
├── .gitignore               Deja fuera secretos, medios y entornos virtuales
├── README.md                Este archivo
├── panel/
│   ├── app.py               Servidor web y endpoints
│   ├── puente.py            Cola de trabajos y lanzamiento de subprocesos
│   ├── config.py            Rutas configurables por .env
│   ├── info_video.py        Metadatos del video con yt-dlp
│   ├── templates/index.html Interfaz
│   ├── requirements.txt
│   └── .env.example
└── publicador/
    ├── prueba.py                      Textos con Gemini
    ├── publicar_clips_meta.py         Programa el lote de Facebook
    ├── subir_clips_meta.py            Subida real a Meta (FB + IG)
    ├── subir_instagram.py             Reels de Instagram
    ├── subir_clips_yt.py              YouTube programado
    ├── subir_clips_tiktok.py          TikTok
    ├── meta_tokens.py                 Renueva el token de Meta solo
    ├── auth_youtube.py / auth_tiktok.py   Autorización OAuth inicial
    ├── firebase_hosting.py            URL HTTPS temporal para el video
    ├── renovar_token_facebook.py
    ├── generar_calificacion.py
    ├── panel.py                       Panel Flask alternativo (versión antigua)
    ├── templates/panel.html
    ├── README.md                      Guía detallada del publicador
    ├── requirements.txt
    └── .env.example
```

## Requisitos

- **Python 3.11 o superior** (probado con 3.13)
- **Windows** para el flujo completo (el `.bat` y las rutas de los venvs). El
  código Python es multiplataforma si ajustas las rutas en `.env`.
- Cuenta de **Meta for Developers** con una app en modo Live (Facebook + Instagram)
- Proyecto en **Google Cloud** con la YouTube Data API habilitada
- App en **TikTok for Developers**
- Clave de **Gemini** (Google AI Studio)
- Opcional: **Firebase CLI** y un proyecto en plan Spark (Meta necesita una URL
  HTTPS para descargar el video antes de publicar un Reel)

## Instalación

Clona el repositorio y crea un entorno virtual por cada herramienta:

```powershell
git clone https://github.com/TU-USUARIO/automatizacion-clips.git
cd automatizacion-clips

python -m venv panel\.venv
panel\.venv\Scripts\python.exe -m pip install -r panel\requirements.txt

python -m venv publicador\.venv
publicador\.venv\Scripts\python.exe -m pip install -r publicador\requirements.txt
```

## Configuración

Nada de credenciales vive en el repositorio. Cada herramienta lee su `.env`
(ignorado por Git):

```powershell
Copy-Item publicador\.env.example publicador\.env
Copy-Item panel\.env.example panel\.env      # solo si necesitas cambiar rutas
notepad publicador\.env
```

Las variables están documentadas dentro de `.env.example`. Las mínimas para
publicar en Facebook son `META_PAGE_ID`, `META_PAGE_ACCESS_TOKEN` y
`META_GRAPH_API_VERSION`; para el resto de redes, consulta
[`publicador/README.md`](publicador/README.md).

Dos variables controlan la identidad que usan los textos generados con Gemini:

```ini
MARCA_NOMBRE=Tu marca
MARCA_TONO=cercana, profesional y educativa
```

Si no las defines, los prompts usan un tono neutro. Así el repositorio sirve
para cualquier proyecto sin tocar código.

### Rutas del panel

`panel/config.py` ya no tiene rutas fijas de una máquina. Por defecto busca:

| Herramienta | Ruta por defecto | Variable para cambiarla |
| --- | --- | --- |
| Generador de clips | `<repo>/generador` | `GENERADOR_DIR` |
| Publicador | `<repo>/publicador` | `PUBLICADOR_DIR` |

Si el generador está en otro sitio (por ejemplo `C:\Users\tu-usuario\Desktop\Generador de clips`),
basta con ponerlo en `panel/.env`:

```ini
GENERADOR_DIR=C:\Users\tu-usuario\Desktop\Generador de clips
```

## Uso

### Con el panel (recomendado)

```powershell
.\abrir_panel.bat
```

Abre `http://127.0.0.1:8765` en el navegador. El panel escucha solo en local: no
se expone a la red, porque desde ahí se manejan tokens y se suben videos.

### Por línea de comandos

```powershell
# 1. Generar textos (título, descripción, hashtags) con Gemini
publicador\.venv\Scripts\python.exe publicador\prueba.py

# 2. Programar cinco clips en Facebook (uno por día, 7:00 p. m. Colombia)
publicador\.venv\Scripts\python.exe publicador\publicar_clips_meta.py programar

# 3. Revisar el token de Meta
publicador\.venv\Scripts\python.exe publicador\meta_tokens.py revisar
```

Cada script acepta `--help`. La guía completa de Meta, YouTube y TikTok está en
[`publicador/README.md`](publicador/README.md).

## Seguridad

Lo que **nunca** se sube (ya está en `.gitignore`):

- `.env` y cualquier `.env.*` (salvo los `.example`)
- Tokens OAuth: `token_credencial.json`, `token_tiktok.json`, `credenciales_youtube.json`
- `client_secret*.json` y cuentas de servicio de Google
- Registros de publicaciones (`registro_*.json`): contienen IDs de tu cuenta
- Videos, audios, zips y paquetes de Spotify
- Entornos virtuales (`.venv/`) y cachés

Si alguna credencial se filtró alguna vez, **bórrala y genera otra**: quitarla de
un commit no la borra del historial.

## Problemas comunes

| Síntoma | Causa probable |
| --- | --- |
| `No existe el intérprete del generador` | Falta `GENERADOR_DIR` en `panel/.env` o no creaste su venv |
| `Token de Facebook vencido` | Regenera con `meta_tokens.py renovar`; revisa que la app esté en modo Live |
| Meta rechaza el Reel | El video no tiene URL HTTPS pública: revisa `META_PUBLIC_VIDEO_BASE_URL` y Firebase |
| El panel abre pero los botones fallan | El `.env` del publicador no tiene la clave que esa etapa necesita |
| Acentos raros en la consola | Ejecuta con `PYTHONIOENCODING=utf-8` (el panel ya lo hace) |

## Licencia

MIT. Consulta [`LICENSE`](LICENSE) para el texto completo.
