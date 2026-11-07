# -*- coding: utf-8 -*-
"""
Mail Downloader — servidor web (Flask).

Interfaz web para descargar correos de cualquier proveedor IMAP (Gmail, Outlook,
Yahoo, iCloud, Hostinger o personalizado), organizados por carpeta/año/mes, con
verificación y borrado opcional. Corre LOCAL (127.0.0.1). La contraseña vive solo
en memoria durante la sesión; nunca se guarda en disco.
"""

import os
import json
import queue
import secrets
import threading
import webbrowser
from pathlib import Path

from flask import (Flask, request, jsonify, Response,
                   render_template, stream_with_context)

import imap_core as core

app = Flask(__name__)

# Carpeta de descargas por defecto (configurable desde la UI).
DESTINO_DEFECTO = str(Path.home() / "Descargas" / "Mail Downloader")

# Sesiones y trabajos en memoria.
SESIONES = {}   # token -> {"imap":..., "email":...}
JOBS = {}       # job_id -> {"q": Queue, "cancel": bool, "done": bool}
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html",
                           destino_defecto=DESTINO_DEFECTO,
                           proveedores=list(core.PROVEEDORES.keys()))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/api/connect")
def api_connect():
    d = request.get_json(force=True)
    correo = (d.get("email") or "").strip()
    password = d.get("password") or ""
    provider = d.get("provider") or "custom"
    if not correo or not password:
        return jsonify(error="Ingresa correo y contraseña."), 400
    try:
        host, port = core.resolver_servidor(provider, d.get("host"), d.get("port"))
        imap = core.conectar(correo, password, host, port)
        carpetas_raw = core.listar_carpetas(imap)
    except Exception as e:
        return jsonify(error=f"No se pudo conectar: {e}"), 400

    token = secrets.token_urlsafe(16)
    with _LOCK:
        SESIONES[token] = {"imap": imap, "email": correo}
    carpetas = [{"raw": c, "nombre": core._imap_utf7_decode(c)} for c in carpetas_raw]
    return jsonify(token=token, email=correo, servidor=f"{host}:{port}",
                   carpetas=carpetas)


@app.post("/api/review")
def api_review():
    d = request.get_json(force=True)
    sesion = SESIONES.get(d.get("token"))
    if not sesion:
        return jsonify(error="Sesión no válida. Vuelve a conectar."), 401
    imap = sesion["imap"]
    folders = d.get("folders") or []
    periodo = d.get("period") or core.PERIODO_TODO
    agregado, desglose = {}, []
    try:
        for raw in folders:
            nombre = core._imap_utf7_decode(raw)
            parcial = core.resumen_por_mes(imap, raw, periodo=periodo)
            sub = sum(c for _, c in parcial)
            desglose.append({"carpeta": nombre, "correos": sub})
            for (anio, mes), cant in parcial:
                agregado[(anio, mes)] = agregado.get((anio, mes), 0) + cant
    except Exception as e:
        return jsonify(error=f"No se pudo revisar: {e}"), 400
    meses = [{"anio": a, "mes": m, "mes_nombre": core.MESES_ES[m - 1], "cantidad": c}
             for (a, m), c in sorted(agregado.items(), reverse=True)]
    return jsonify(meses=meses, desglose=desglose)


@app.post("/api/download")
def api_download():
    d = request.get_json(force=True)
    sesion = SESIONES.get(d.get("token"))
    if not sesion:
        return jsonify(error="Sesión no válida. Vuelve a conectar."), 401
    folders = d.get("folders") or []
    meses = [(int(m["anio"]), int(m["mes"])) for m in (d.get("months") or [])]
    periodo = d.get("period") or core.PERIODO_TODO
    borrar = bool(d.get("delete"))
    destino = (d.get("dest") or DESTINO_DEFECTO).strip() or DESTINO_DEFECTO
    if not folders or not meses:
        return jsonify(error="Faltan carpetas o meses."), 400

    job_id = secrets.token_urlsafe(10)
    job = {"q": queue.Queue(), "cancel": False, "done": False}
    JOBS[job_id] = job
    t = threading.Thread(target=_trabajo_descarga,
                         args=(job, sesion["imap"], sesion["email"], folders,
                               meses, periodo, borrar, destino),
                         daemon=True)
    t.start()
    return jsonify(job_id=job_id)


@app.post("/api/cancel")
def api_cancel():
    job = JOBS.get(request.get_json(force=True).get("job_id"))
    if job:
        job["cancel"] = True
    return jsonify(ok=True)


@app.get("/api/progress/<job_id>")
def api_progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="job no encontrado"), 404

    @stream_with_context
    def gen():
        while True:
            try:
                msg = job["q"].get(timeout=30)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg.get("tipo") in ("completado", "error"):
                break
        JOBS.pop(job_id, None)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


def _trabajo_descarga(job, imap, correo, folders, meses, periodo, borrar, destino):
    q = job["q"]

    def emitir(tipo, **kw):
        kw["tipo"] = tipo
        q.put(kw)

    try:
        # 1) Total real (para el %).
        trabajos, total_global = [], 0
        unidades, hechas = max(len(folders) * len(meses), 1), 0
        for raw in folders:
            nombre = core._imap_utf7_decode(raw)
            for anio, mes in sorted(meses):
                if job["cancel"]:
                    break
                try:
                    n = core.contar_mes(imap, raw, anio, mes, periodo)
                except Exception:
                    n = 0
                if n:
                    trabajos.append((raw, nombre, anio, mes, n))
                    total_global += n
                hechas += 1
                emitir("progreso", pct=int(hechas / unidades * 50),
                       actual=0, total=total_global or 1,
                       estado=f"Calculando total… ({nombre})")
        total_global = max(total_global, 1)

        # 2) Descargar reportando progreso global.
        tot = {"guardados": 0, "verificados": 0, "fallidos": 0, "borrados": 0}
        hecho, carpeta_actual = 0, None
        for raw, nombre, anio, mes, n in trabajos:
            if job["cancel"]:
                break
            if nombre != carpeta_actual:
                carpeta_actual = nombre
            base = hecho

            def prog(actual, total, texto, _base=base, _nom=nombre):
                g = _base + actual
                emitir("progreso", pct=int(g / total_global * 100),
                       actual=g, total=total_global,
                       estado=f"{_nom} · {texto}")

            st = core.descargar_mes(imap, raw, anio, mes, destino, correo,
                                    progreso=prog,
                                    cancelar=lambda: job["cancel"],
                                    borrar=borrar, periodo=periodo)
            hecho += n
            for k in tot:
                tot[k] += st.get(k, 0)
            emitir("progreso", pct=int(hecho / total_global * 100),
                   actual=hecho, total=total_global,
                   estado=f"{nombre} · {core.MESES_ES[mes - 1]} {anio} listo")

        if job["cancel"]:
            emitir("completado", pct=100, cancelado=True, stats=tot,
                   destino=destino,
                   mensaje=f"⏹ Cancelado — {tot['guardados']} descargados")
        else:
            msg = f"✅ Listo, ya quedó — {tot['guardados']} descargados"
            if borrar:
                msg += f", {tot['borrados']} borrados"
            emitir("completado", pct=100, stats=tot, destino=destino, mensaje=msg)
    except Exception as e:
        emitir("error", mensaje=f"Error durante la descarga: {e}")
    finally:
        job["done"] = True


if __name__ == "__main__":
    url = "http://127.0.0.1:5000"
    # Abre el navegador automáticamente (solo el proceso principal).
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"\n  Mail Downloader corriendo en {url}\n  (Ctrl+C para detener)\n")
    app.run(host="127.0.0.1", port=5000, threaded=True, debug=False)
