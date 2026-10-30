# Automatización de clips

Este proyecto organiza los clips y sus textos, y tiene un panel web que reúne las tres tareas: generar los textos con Gemini, programar los videos en YouTube y agendar Reels en Facebook con la API de Meta. Instagram queda fuera de este flujo: se publica por separado, como hasta ahora.

## El panel

Abre `abrir_panel.bat` (doble clic). Levanta un servidor en `http://127.0.0.1:5000` y abre esa dirección en el navegador. La página muestra cuatro números (clips totales, con los tres textos, en YouTube y en Facebook), una tabla con el estado de cada video y un punto de color con la vigencia del permiso de Meta.

Los botones del panel arrancan un programa en segundo plano y muestran sus mensajes en la consola negra, uno por uno. Solo puedes presionar un botón a la vez por tarea: si el trabajo sigue corriendo, el panel lo rechaza.

El panel corre en tu propio computador, en `127.0.0.1`. No es público y no necesita internet para arrancar, aunque sí lo necesita para revisar el permiso de Meta o publicar.

## Generar textos con Gemini

`prueba.py` revisa los MP4 de `META_VIDEO_DIR` y escribe en `META_TEXT_DIR` cuatro archivos por cada video nuevo: `titulo_`, `descripcion_`, `hashtags_` y `calificacion_`. Un clip queda anotado en `registro.txt` (dentro de la carpeta de videos) solo cuando los archivos quedaron guardados, así un fallo de Gemini no lo marca como hecho.

### Por qué cada clip suena distinto

Antes el prompt solo recibía el nombre del archivo, y como los clips de un mismo video se llaman casi igual (`VIDEO_clip_0_final.mp4`, `VIDEO_clip_1_final.mp4`...), Gemini no tenía nada que los diferenciara: repetía títulos y descripciones. Ahora el programa le manda el contenido real del clip:

| Fuente | Qué aporta |
|---|---|
| `momentos_clave/<video>.json` | La razón por la que se eligió ese fragmento |
| `transcripciones/<video>.txt` | El texto hablado dentro del clip |

El índice del clip en el nombre (`clip_3`) corresponde a su posición en ese JSON, así que cada clip recibe un fragmento distinto de la transcripción. Además el prompt prohíbe las fórmulas fijas (`En la marca sabemos...`), pide una temperatura alta y rechaza títulos ya usados: si Gemini repite uno, el programa reintenta.

Las carpetas de apoyo se buscan junto a la de clips. Si están en otro sitio:

```ini
MOMENTOS_CLAVE_DIR=C:\ruta\a\momentos_clave
TRANSCRIPCIONES_DIR=C:\ruta\a\transcripciones
```

Si un clip no tiene transcripción o su nombre no sigue el patrón `_clip_N_final`, los textos se generan igual, solo con el nombre del archivo: el programa lo avisa en la consola.

### Volver a generar textos viejos

Los clips que están en `registro.txt` se saltan. Para rehacerlos (por ejemplo, para corregir textos repetidos generados antes de este arreglo):

```powershell
.\.venv\Scripts\python.exe .\prueba.py --forzar
```

Con `--forzar` no se toca `registro.txt` y se sobrescriben los `.txt` de cada clip.

Si Gemini falla, el programa reintenta hasta diez veces con pausas crecientes de diez segundos. Para probarlo sin usar la carpeta real:

```powershell
.\.venv\Scripts\python.exe .\prueba.py --videos "C:\ruta\de\prueba\videos" --textos "C:\ruta\de\prueba\textos"
```

## Programar en YouTube

`subir_clips_yt.py` busca los `titulo_*.txt`, arma la descripción con los hashtags al final y sube cada clip como privado con fecha de publicación, un video por día a las 7:00 p. m., hora de Colombia. El primer turno libre se calcula a partir de las fechas ya reservadas en `registro_youtube.json`. Si YouTube rechaza un video, el envío se detiene ahí: ese clip no se anota y se reintenta en la próxima ejecución.

El token de Google se guarda en `token_credencial.json`, junto al programa. Si no existe, se genera con el flujo de autenticación de Google y queda guardado para no pedir el login otra vez.

## El permiso de Facebook

Un token de página generado desde Graph API Explorer dura pocas horas. `meta_tokens.py` resuelve eso con un **usuario sistema**, que es la cuenta que Meta recomienda para servidores:

- El token del usuario sistema no caduca. Hay que regenerarlo solo si lo revoacas tú, si alguien sale de la página o si Meta invalida la app.
- El programa lo refresca solo cuando le quedan siete días o menos, así que no dependes de acordarte.

### Cómo se configura, una sola vez

1. En [Business Settings](https://business.facebook.com/settings) crea un **System User** y asígnale tu app con los permisos, y también la página de Facebook. Ese paso es el único que hay que hacer a mano, porque ocurre dentro de Facebook.

Los permisos que hay que marcar son estos:

| Para | Permisos |
| --- | --- |
| Facebook | `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` |
| Instagram | `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`, `pages_show_list`, `ads_read` |

El `ads_read` en Instagram no es para publicidad. Se necesita porque el usuario sistema tiene el rol sobre la página dentro de Business Manager, y Meta lo exige en esa combinación. Para no tener que memorizarlo:

```powershell
.\.venv\Scripts\python.exe .\meta_tokens.py permisos
```

`pages_manage_posts` no sale en la pantalla de permisos y funciones del panel de Meta, porque esa pantalla solo lista los que necesitan revisión.

2. Pega en el `.env` tres líneas: `META_APP_ID`, `META_APP_SECRET` y `META_SYSTEM_USER_TOKEN` con el token que generaste para ese usuario sistema.
3. Deja que el programa saque el token de la página:

```powershell
.\.venv\Scripts\python.exe .\meta_tokens.py renovar
```

A partir de ahí `META_PAGE_ACCESS_TOKEN` se llena solo y queda renewed cada 60 días sin que hagas nada. Para mirar cómo está:

```powershell
.\.venv\Scripts\python.exe .\meta_tokens.py revisar
```

El panel también lo hace: el punto de color muestra la fecha de vencimiento y el botón **Renovar el permiso de Facebook** fuerza un token nuevo cuando lo necesites. Cuando el permiso se está por vencer, los otros programas lo renuevan solos antes de publicar.

Requisito: la app debe estar en modo **Live** en [developers.facebook.com](https://developers.facebook.com/apps). Una app en Development siempre entrega tokens cortos, sin importar el usuario sistema.

**No necesitas App Review.** Meta solo lo pide cuando la app sirve cuentas que tú no administras. Como la tuya publica únicamente en tu propia página, quedas en Standard Access y los permisos se conceden sin revisión.

## Programar cinco clips en Facebook

El programa escoge los primeros cinco MP4 pendientes por orden alfabético. Para cada video busca en `META_TEXT_DIR` tres archivos con el mismo nombre base: `titulo_`, `descripcion_` y `hashtags_`. Por ejemplo, `clip_2_final.mp4` usa `titulo_clip_2_final.txt`, `descripcion_clip_2_final.txt` y `hashtags_clip_2_final.txt`.

En PowerShell, desde la carpeta del proyecto, ejecuta:

```powershell
.\.venv\Scripts\python.exe .\publicar_clips_meta.py programar
```

El módulo sube directamente cada MP4 desde el computador a Facebook y programa uno por día a las 7:00 p. m., hora de Colombia, empezando mañana. Al terminar cada video, guarda el ID y la fecha confirmada en `registro_meta.json`. Facebook publica los videos en la fecha elegida aunque el computador esté apagado después de programarlos.

`lote_meta_pendiente.txt` muestra qué clips se eligieron. Si Facebook confirma todos, el lote temporal se limpia. Si ocurre un error, el programa conserva el lote para investigar y evita repetir automáticamente un envío cuyo resultado no esté claro. Antes de volver a ejecutar después de un error, revisa **Meta Business Suite > Contenido > Programadas**. No borres las marcas de intento del registro hasta verificar qué hizo Facebook.

### Comandos disponibles

- `programar`: sube y programa el lote guardado; si no hay lote, selecciona cinco clips automáticamente.
- `preparar`: crea solo una vista previa; no sube ni programa nada.
- `recrear`: reemplaza con confirmación un lote no enviado y asigna fechas nuevas; después ejecuta `programar` para subirlo.
- `cancelar`: borra el lote pendiente, pero conserva el historial de publicaciones.

La carpeta `registro_meta.json` evita que se programe de nuevo un Reel ya registrado en Facebook. Al agotarse los clips, agrega videos y sus tres archivos de texto correspondientes a las carpetas configuradas.

## Ajustes necesarios

El archivo `.env` debe tener, como mínimo:

- `META_GRAPH_API_VERSION`
- `META_PAGE_ID`
- `META_PAGE_ACCESS_TOKEN`
- `META_VIDEO_DIR`
- `META_TEXT_DIR`

Guarda el token solo en `.env`; no lo pegues en mensajes ni capturas. La cuenta que lo generó debe conservar permisos para publicar Reels en la página.

Esta programación de Facebook envía el video binario directamente a los servidores de Meta. No usa Firebase Hosting ni Firebase Storage, así que esta ruta no consume la cuota de transferencia de Firebase. Instagram no se programa con este comando; continúa con tu publicación diaria separada.

## Archivos relacionados

- `abrir_panel.bat`: abre el navegador y levanta el panel.
- `panel.py` y `templates/panel.html`: el panel web y su página.
- `prueba.py`: genera título, descripción, hashtags y calificación de cada clip con Gemini.
- `subir_clips_yt.py`: programa los clips en YouTube.
- `publicar_clips_meta.py`: comando principal para preparar, programar y cancelar lotes de Facebook.
- `subir_clips_meta.py`: funciones internas de conexión y publicación mediante la API de Meta.
- `meta_tokens.py`: revisa y renueva el permiso de Meta para que no caduque.
- `registro_meta.json`: historial local de IDs y horarios de publicaciones.
- `lote_meta_pendiente.json`: selección que se conserva si hay que reanudar un lote.
- `token_credencial.json`: permiso de Google para YouTube.
- `.env`: rutas y credenciales privadas; no debe compartirse.
- `.env.example`: la lista de ajustes que debe tener el `.env`, sin los valores reales.

Los archivos de historial (`registro_youtube.json`, `registro_meta.json`) y las credenciales quedan fuera de git a propósito: son datos de tu cuenta y del historial de publicaciones, no del código.
