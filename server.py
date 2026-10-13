#!/usr/bin/env python3
"""NEXO AI - prototipo web local usando solo la biblioteca estándar de Python."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import json, sqlite3, os, re
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "nexo.db")
HOST, PORT = "0.0.0.0", int(os.environ.get("PORT", "8000"))

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact TEXT DEFAULT '',
                business TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Nuevo',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

def log_action(action):
    with connect_db() as db:
        db.execute("INSERT INTO activity(action, created_at) VALUES (?, ?)",
                   (action, datetime.now().isoformat(timespec="seconds")))

def json_bytes(data):
    return json.dumps(data, ensure_ascii=False).encode("utf-8")

class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Solicitud demasiado grande")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("El cuerpo debe ser un objeto JSON")
        return value

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/stats":
            with connect_db() as db:
                total = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
                new = db.execute("SELECT COUNT(*) FROM leads WHERE status='Nuevo'").fetchone()[0]
                active = db.execute("SELECT COUNT(*) FROM leads WHERE status='En seguimiento'").fetchone()[0]
                won = db.execute("SELECT COUNT(*) FROM leads WHERE status='Cliente'").fetchone()[0]
                activity = [dict(r) for r in db.execute(
                    "SELECT action, created_at FROM activity ORDER BY id DESC LIMIT 6"
                ).fetchall()]
            return self.send_json({"total": total, "new": new, "active": active,
                                   "won": won, "activity": activity})
        if path == "/api/leads":
            q = urlparse(self.path).query
            from urllib.parse import parse_qs
            term = parse_qs(q).get("q", [""])[0].strip()
            with connect_db() as db:
                if term:
                    pat = "%" + term + "%"
                    rows = db.execute("""SELECT * FROM leads
                        WHERE name LIKE ? OR contact LIKE ? OR business LIKE ?
                        ORDER BY id DESC""", (pat, pat, pat)).fetchall()
                else:
                    rows = db.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
            return self.send_json([dict(r) for r in rows])
        if path in ("/", "/index.html"):
            file_path = os.path.join(ROOT, "index.html")
            try:
                with open(file_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self.send_error(500, "No se encuentra index.html")
            return
        self.send_json({"error": "Ruta no encontrada"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path == "/api/leads":
                name = str(data.get("name", "")).strip()[:120]
                if not name:
                    return self.send_json({"error": "El nombre es obligatorio"}, 400)
                contact = str(data.get("contact", "")).strip()[:180]
                business = str(data.get("business", "")).strip()[:120]
                status = str(data.get("status", "Nuevo")).strip()
                if status not in ("Nuevo", "En seguimiento", "Cliente"):
                    status = "Nuevo"
                notes = str(data.get("notes", "")).strip()[:1000]
                with connect_db() as db:
                    cur = db.execute("""INSERT INTO leads
                        (name, contact, business, status, notes, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (name, contact, business, status, notes,
                         datetime.now().isoformat(timespec="seconds")))
                    lead_id = cur.lastrowid
                log_action(f"Contacto registrado: {name}")
                return self.send_json({"ok": True, "id": lead_id}, 201)
            if path == "/api/generate":
                kind = str(data.get("kind", "reply"))
                business = str(data.get("business", "tu negocio")).strip()[:120] or "tu negocio"
                tone = str(data.get("tone", "amable"))
                customer = str(data.get("customer", "¡Hola!")).strip()[:500]
                product = str(data.get("product", "nuestros servicios")).strip()[:250]
                price = str(data.get("price", "")).strip()[:80]
                if kind == "marketing":
                    price_line = f" Precio: {price}." if price else ""
                    result = (f"✨ ¡Dale un impulso a {business}! ✨\n\n"
                              f"Descubre {product} y encuentra una opción ideal para ti."
                              f"{price_line}\n\n"
                              "📩 Escríbenos para más información. ¡Será un gusto atenderte!\n"
                              "#Emprendimiento #Calidad #AtenciónAlCliente")
                else:
                    greeting = "¡Hola! Gracias por escribirnos." if tone == "formal" else "¡Hola! 😊 Gracias por contactarnos."
                    result = (f"{greeting}\n\n"
                              f"Con gusto te ayudamos con tu consulta sobre {product}. "
                              f"Cuéntanos un poquito más para brindarte la mejor información.\n\n"
                              f"¡Gracias por considerar a {business}!")
                log_action("Texto de marketing generado" if kind == "marketing" else "Respuesta sugerida")
                return self.send_json({"ok": True, "text": result})
            return self.send_json({"error": "Ruta no encontrada"}, 404)
        except (ValueError, json.JSONDecodeError) as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception:
            return self.send_json({"error": "Error interno del servidor"}, 500)

    def do_PATCH(self):
        match = re.fullmatch(r"/api/leads/(\d+)", urlparse(self.path).path)
        if not match:
            return self.send_json({"error": "Ruta no encontrada"}, 404)
        try:
            data = self.read_json()
            status = str(data.get("status", "Nuevo"))
            if status not in ("Nuevo", "En seguimiento", "Cliente"):
                return self.send_json({"error": "Estado no válido"}, 400)
            with connect_db() as db:
                cur = db.execute("UPDATE leads SET status=? WHERE id=?", (status, int(match.group(1))))
            if not cur.rowcount:
                return self.send_json({"error": "Contacto no encontrado"}, 404)
            log_action(f"Estado actualizado a {status}")
            return self.send_json({"ok": True})
        except Exception:
            return self.send_json({"error": "No se pudo actualizar"}, 400)

    def do_DELETE(self):
        match = re.fullmatch(r"/api/leads/(\d+)", urlparse(self.path).path)
        if not match:
            return self.send_json({"error": "Ruta no encontrada"}, 404)
        with connect_db() as db:
            cur = db.execute("DELETE FROM leads WHERE id=?", (int(match.group(1)),))
        if not cur.rowcount:
            return self.send_json({"error": "Contacto no encontrado"}, 404)
        log_action("Contacto eliminado")
        return self.send_json({"ok": True})

    def log_message(self, fmt, *args):
        print("[NEXO]", fmt % args)

if __name__ == "__main__":
    init_db()
    print(f"\nNEXO AI escuchando en el puerto {PORT}. En local abre http://127.0.0.1:{PORT}")
    print("Para detener el servidor, presiona Ctrl+C.\n")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
