<p align="center">
  <img src="static/logo.svg" width="72" alt="Mail Downloader">
</p>

<h1 align="center">Mail Downloader</h1>

<p align="center">
  Descarga, verifica y organiza tu correo por <b>año y mes</b> desde cualquier
  proveedor <b>IMAP</b> — Gmail, Outlook/Office 365, Yahoo, iCloud, Hostinger o
  un servidor personalizado. App web local con interfaz responsiva.
</p>

---

## ✨ Características

- **Multi-proveedor** por IMAP: Gmail, Outlook/Office 365, Yahoo, iCloud, Hostinger y cualquier host/puerto personalizado.
- **Revisa antes de bajar:** cuenta cuántos correos hay por **año/mes** en cada carpeta.
- **Elige lo que quieras:** marca uno o varios meses, una carpeta o todas, y mes completo o quincena (1–15 / 16–fin).
- **Descarga verificada:** cada correo se guarda como `.eml` (con adjuntos) y se verifica **byte por byte**.
- **Borrado opcional del servidor** (irreversible): solo borra lo que se descargó y verificó correctamente.
- **Progreso en vivo:** barra + dona con porcentaje y contador "X de Y · faltan Z".
- **Interfaz bonita y responsiva** (funciona en escritorio y móvil).
- **Privado:** corre en tu máquina (`127.0.0.1`); la contraseña **nunca se guarda en disco**.

## 🚀 Instalación y uso

Requiere **Python 3.9+**.

```bash
pip install -r requirements.txt
python app.py
```

Se abre solo en tu navegador en **http://127.0.0.1:5000**
(si no, ábrelo manualmente).

1. Elige **proveedor**, pon tu **correo** y **contraseña** → **Conectar**.
2. Elige **carpeta** (o `TODAS`) y **periodo** → **Revisar meses**.
3. **Marca** los meses que quieras → **Descargar seleccionados**.

Los correos se guardan en `~/Descargas/Mail Downloader/<correo>/<carpeta>/<año>/<mes>/`
(puedes cambiar la carpeta destino en la interfaz).

## 🔐 Contraseñas de aplicación (importante)

Por seguridad, varios proveedores **no aceptan tu contraseña normal** vía IMAP;
necesitas una **Contraseña de aplicación** (App Password):

| Proveedor | Cómo obtenerla |
|-----------|----------------|
| **Gmail** | Activa la verificación en 2 pasos → [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| **Outlook / Microsoft 365** | Cuenta → Seguridad → Opciones avanzadas → Contraseñas de aplicación |
| **Yahoo** | Cuenta → Seguridad de la cuenta → Generar contraseña de aplicación |
| **iCloud** | [appleid.apple.com](https://appleid.apple.com) → Seguridad → Contraseñas específicas de app |
| **Hostinger / otros** | Usa la contraseña del buzón (host IMAP del panel de tu hosting) |

## 🔒 Privacidad y seguridad

- La app corre **solo en local** (`127.0.0.1`). No expongas este servidor a internet tal cual.
- La contraseña se usa solo en memoria durante la sesión; **no se escribe en disco** ni se registra.
- Los correos descargados **no** forman parte de este repositorio (ver `.gitignore`).

## 🗂 Estructura

```
app.py              # Servidor Flask (rutas + progreso en vivo por SSE)
imap_core.py        # Lógica IMAP (conectar, contar por mes, descargar, verificar, borrar)
templates/index.html
static/              # style.css, app.js, logo.svg
```

## 📝 Licencia

MIT — ver [LICENSE](LICENSE).
