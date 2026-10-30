"""Autoriza el acceso a YouTube con tu cuenta de Google y guarda el token local.

Se llama desde el panel (botón «Conectar YouTube»). Solo corre en esta máquina:
abre el navegador en 127.0.0.1 y pide los permisos de subida de videos.
"""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

CARPETA = Path(__file__).parent
CREDENCIALES = CARPETA / "credenciales_youtube.json"
TOKEN = CARPETA / "token_credencial.json"
PERMISO = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    if not CREDENCIALES.is_file():
        raise SystemExit(
            f"Falta el archivo de credenciales de Google: {CREDENCIALES}\n"
            "Descárgalo desde Google Cloud Console (OAuth client, tipo Desktop) "
            "y guárdalo con ese nombre."
        )
    print("Abriendo el navegador para autorizar YouTube...")
    print("Si no se abre solo, copia la URL que aparezca en esta ventana.")
    flujo = InstalledAppFlow.from_client_secrets_file(str(CREDENCIALES), PERMISO)
    token = flujo.run_local_server(port=0, open_browser=True)
    TOKEN.write_text(token.to_json(), encoding="utf-8")
    print(f"TOKEN_GUARDADO:{TOKEN}")


if __name__ == "__main__":
    main()
