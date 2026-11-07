# -*- coding: utf-8 -*-
"""
Núcleo IMAP (sin interfaz): conectar, listar carpetas, contar por mes y
descargar correos como .eml, con verificación y borrado opcional.

Multi-proveedor: Gmail, Outlook/Office 365, Yahoo, iCloud, Hostinger y cualquier
servidor IMAP personalizado.
"""

import imaplib
import email
import re
import base64
from email.header import decode_header, make_header
from pathlib import Path

# ---------------------------------------------------------------------------
# Proveedores (host, puerto) — "custom" pide host/puerto al usuario.
# ---------------------------------------------------------------------------
PROVEEDORES = {
    "gmail":     ("imap.gmail.com", 993),
    "outlook":   ("outlook.office365.com", 993),
    "yahoo":     ("imap.mail.yahoo.com", 993),
    "icloud":    ("imap.mail.me.com", 993),
    "hostinger": ("imap.hostinger.com", 993),
    "custom":    (None, None),
}

# Límite de espera (s) para operaciones de red; evita cuelgues infinitos.
IMAP_TIMEOUT = 120

MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
MESES_IMAP = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Periodos dentro de un mes.
PERIODO_TODO = "todo"
PERIODO_Q1 = "q1"       # días 1-15
PERIODO_Q2 = "q2"       # día 16 al fin
ETIQUETAS_PERIODO = {
    PERIODO_TODO: "Todo el mes",
    PERIODO_Q1: "1ª quincena (1-15)",
    PERIODO_Q2: "2ª quincena (16-fin)",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def resolver_servidor(provider, host=None, port=None):
    """Devuelve (host, port) a partir del proveedor o de valores personalizados."""
    provider = (provider or "").lower()
    if provider in PROVEEDORES and provider != "custom":
        return PROVEEDORES[provider]
    # custom o desconocido: usar lo que pase el usuario.
    if not host:
        raise ValueError("Falta el servidor IMAP (host).")
    return host, int(port or 993)


def conectar(correo, password, host, port=993):
    """Conecta por IMAP SSL y hace login. Devuelve IMAP4_SSL o lanza excepción."""
    imap = imaplib.IMAP4_SSL(host, int(port), timeout=IMAP_TIMEOUT)
    imap.login(correo, password)
    return imap


def _imap_utf7_decode(nombre):
    """Decodifica nombres de carpeta IMAP (modified UTF-7) a texto legible."""
    if isinstance(nombre, bytes):
        nombre = nombre.decode("ascii", "replace")
    res, i = [], 0
    while i < len(nombre):
        c = nombre[i]
        if c == "&":
            j = nombre.find("-", i + 1)
            if j == -1:
                res.append(nombre[i:])
                break
            chunk = nombre[i + 1:j]
            if chunk == "":
                res.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    res.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:
                    res.append(nombre[i:j + 1])
            i = j + 1
        else:
            res.append(c)
            i += 1
    return "".join(res)


def _decodificar(valor):
    """Decodifica encabezados MIME (asuntos con acentos, etc.)."""
    if valor is None:
        return ""
    try:
        return str(make_header(decode_header(valor)))
    except Exception:
        return str(valor)


def listar_carpetas(imap):
    """Lista los nombres RAW de carpetas del buzón (INBOX primero)."""
    typ, data = imap.list()
    if typ != "OK" or not data:
        return ["INBOX"]
    carpetas = []
    for linea in data:
        if linea is None:
            continue
        if isinstance(linea, bytes):
            linea = linea.decode("utf-8", errors="replace")
        m = re.search(r'"([^"]*)"\s*$', linea)
        nombre = m.group(1) if m else linea.split()[-1].strip('"')
        if nombre:
            carpetas.append(nombre)
    carpetas = list(dict.fromkeys(carpetas))
    carpetas.sort(key=lambda c: (c.upper() != "INBOX", c.upper()))
    return carpetas or ["INBOX"]


def _seleccionar_carpeta(imap, carpeta, readonly=True):
    typ, data = imap.select(f'"{carpeta}"', readonly=readonly)
    if typ != "OK":
        raise RuntimeError(f"No se pudo abrir la carpeta '{carpeta}': {data}")
    return data


def _inicio_mes_siguiente(anio, mes):
    if mes == 12:
        return f"01-{MESES_IMAP[0]}-{anio + 1}"
    return f"01-{MESES_IMAP[mes]}-{anio}"


def _rango_periodo(anio, mes, periodo=PERIODO_TODO):
    mmm = MESES_IMAP[mes - 1]
    if periodo == PERIODO_Q1:
        return f"01-{mmm}-{anio}", f"16-{mmm}-{anio}"
    if periodo == PERIODO_Q2:
        return f"16-{mmm}-{anio}", _inicio_mes_siguiente(anio, mes)
    return f"01-{mmm}-{anio}", _inicio_mes_siguiente(anio, mes)


def _dia_en_periodo(dia, periodo):
    if periodo == PERIODO_Q1:
        return 1 <= dia <= 15
    if periodo == PERIODO_Q2:
        return dia >= 16
    return True


def resumen_por_mes(imap, carpeta, periodo=PERIODO_TODO, progreso=None):
    """Cuenta correos por (año, mes) en la carpeta, filtrando por periodo."""
    _seleccionar_carpeta(imap, carpeta)
    typ, data = imap.search(None, "ALL")
    if typ != "OK":
        raise RuntimeError("No se pudieron buscar los correos.")
    ids = data[0].split()
    if not ids:
        return []
    total, leidos = len(ids), 0
    conteo = {}
    BLOQUE = 500
    for i in range(0, len(ids), BLOQUE):
        lote = b",".join(ids[i:i + BLOQUE])
        typ, resp = imap.fetch(lote, "(INTERNALDATE)")
        if typ != "OK" or not resp:
            leidos = min(leidos + BLOQUE, total)
            continue
        for item in resp:
            if not isinstance(item, (tuple, bytes)):
                continue
            texto = item.decode("utf-8", "replace") if isinstance(item, bytes) \
                else item[0].decode("utf-8", "replace")
            m = re.search(r'INTERNALDATE "([^"]+)"', texto)
            if not m:
                continue
            dt = imaplib.Internaldate2tuple(f'INTERNALDATE "{m.group(1)}"'.encode())
            if dt is None or not _dia_en_periodo(dt.tm_mday, periodo):
                continue
            clave = (dt.tm_year, dt.tm_mon)
            conteo[clave] = conteo.get(clave, 0) + 1
        leidos = min(leidos + BLOQUE, total)
        if progreso:
            progreso(leidos, total)
    return sorted(conteo.items(), key=lambda kv: kv[0], reverse=True)


def contar_mes(imap, carpeta, anio, mes, periodo=PERIODO_TODO):
    """Cuenta (sin descargar) los correos de un (mes, periodo) en la carpeta."""
    _seleccionar_carpeta(imap, carpeta)
    since, before = _rango_periodo(anio, mes, periodo)
    typ, data = imap.uid("search", None, "SINCE", since, "BEFORE", before)
    if typ != "OK" or not data or data[0] is None:
        return 0
    return len(data[0].split())


def _sanear(texto, maxlen=60):
    texto = texto or "sin-asunto"
    texto = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:maxlen].strip() or "sin-asunto"


def _verificar_eml(ruta, raw):
    """Verifica byte por byte que el .eml quedó completo y es parseable."""
    try:
        if not ruta.exists() or ruta.stat().st_size != len(raw):
            return False
        with open(ruta, "rb") as f:
            en_disco = f.read()
        if en_disco != raw:
            return False
        return bool(email.message_from_bytes(en_disco).keys())
    except Exception:
        return False


def descargar_mes(imap, carpeta, anio, mes, destino_base, correo,
                  progreso=None, cancelar=None, borrar=False,
                  periodo=PERIODO_TODO):
    """
    Descarga los correos de (anio, mes, periodo), verifica cada uno y, si
    borrar=True, elimina del servidor SOLO los verificados. Trabaja por UID.
    Devuelve dict: guardados, verificados, fallidos, borrados.
    """
    _seleccionar_carpeta(imap, carpeta, readonly=not borrar)
    since, before = _rango_periodo(anio, mes, periodo)
    typ, data = imap.uid("search", None, "SINCE", since, "BEFORE", before)
    if typ != "OK":
        raise RuntimeError(f"Búsqueda fallida para {mes}/{anio}.")
    uids = data[0].split()
    total = len(uids)
    stats = {"guardados": 0, "verificados": 0, "fallidos": 0, "borrados": 0}
    if total == 0:
        return stats

    cuenta_dir = _sanear(correo, 80)
    carpeta_dir = _sanear(_imap_utf7_decode(carpeta), 40)
    sub_mes = f"{mes:02d} - {MESES_ES[mes - 1]}"
    if periodo == PERIODO_Q1:
        sub_mes += " (1-15)"
    elif periodo == PERIODO_Q2:
        sub_mes += " (16-fin)"
    destino = (Path(destino_base) / cuenta_dir / carpeta_dir /
               str(anio) / sub_mes)
    destino.mkdir(parents=True, exist_ok=True)

    uids_verificados = []
    for idx, uid in enumerate(uids, start=1):
        if cancelar and cancelar():
            break
        uid_txt = uid.decode() if isinstance(uid, bytes) else str(uid)
        typ, msg_data = imap.uid("fetch", uid, "(RFC822)")
        if typ != "OK" or not msg_data or msg_data[0] is None:
            stats["fallidos"] += 1
            continue
        raw = msg_data[0][1]
        if not raw:
            stats["fallidos"] += 1
            continue
        msg = email.message_from_bytes(raw)
        asunto = _sanear(_decodificar(msg.get("Subject")))
        try:
            fecha_dt = email.utils.parsedate_to_datetime(msg.get("Date"))
            fecha_str = fecha_dt.strftime("%Y-%m-%d")
        except Exception:
            fecha_str = f"{anio}-{mes:02d}-00"
        ruta = destino / f"{fecha_str}_{asunto}_uid{uid_txt}.eml"
        with open(ruta, "wb") as f:
            f.write(raw)
        stats["guardados"] += 1
        if _verificar_eml(ruta, raw):
            stats["verificados"] += 1
            uids_verificados.append(uid)
        else:
            stats["fallidos"] += 1
        if progreso:
            progreso(idx, total, f"{MESES_ES[mes - 1]} {anio}: {idx}/{total}")

    if borrar and uids_verificados:
        BLOQUE = 200
        for i in range(0, len(uids_verificados), BLOQUE):
            lote = b",".join(uids_verificados[i:i + BLOQUE])
            typ, _ = imap.uid("store", lote, "+FLAGS", r"(\Deleted)")
            if typ != "OK":
                raise RuntimeError("No se pudieron marcar correos para borrar.")
        typ, _ = imap.expunge()
        if typ != "OK":
            raise RuntimeError("EXPUNGE falló; los correos no se borraron.")
        stats["borrados"] = len(uids_verificados)

    return stats
