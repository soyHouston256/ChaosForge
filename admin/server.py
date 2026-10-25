#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from backend import Demo, Kubernetes
from controller import Controller, SERVICES, Rejected

STATIC = Path(__file__).parent / 'static'


def make_handler(controller):
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # No tokens, request bodies or session data in stdout.

        def send(self, status, body, mime='application/json'):
            if mime == 'application/json':
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local_host(self):
            # DNS rebinding defense for the intended localhost port-forward access.
            try:
                return urlsplit('http://' + self.headers.get('Host', '')).hostname in ('127.0.0.1', 'localhost', '::1')
            except ValueError:
                return False

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/healthz':
                return self.send(200, {'ok': True})
            if not self.local_host():
                return self.send(403, {'error': 'Acceso solo por localhost / port-forward.'})
            try:
                if path == '/api/state':
                    data = controller.snapshot()
                    data.update(csrf=csrf, mode=controller.backend.mode, services=[], telemetry={
                        'logs': 'No disponible: Cloud Logging no conectado a este panel.',
                        'metrics': 'No disponible: Cloud Monitoring no conectado a este panel.',
                        'traces': 'No disponible: Cloud Trace no conectado a este panel.'})
                    for name, (label, description, icon) in SERVICES.items():
                        item = dict(name=name, label=label, description=description, icon=icon)
                        try:
                            item.update(controller.backend.get(name))
                        except Exception as exc:
                            item['error'] = str(exc)
                        data['services'].append(item)
                    return self.send(200, data)
                if path.startswith('/api/evidence/'):
                    return self.send(200, controller.evidence(path.rsplit('/', 1)[1]))
                files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if path in files:
                    filename, mime = files[path]
                    return self.send(200, (STATIC / filename).read_bytes(), mime)
                return self.send(404, {'error': 'Ruta desconocida.'})
            except Rejected as exc:
                return self.send(404, {'error': str(exc)})
            except Exception:
                return self.send(503, {'error': 'No fue posible leer el estado persistente.'})

        def do_POST(self):
            origin = self.headers.get('Origin')
            expected = 'http://' + self.headers.get('Host', '')
            if not self.local_host() or self.headers.get('X-ChaosForge-Token') != csrf or (origin is not None and origin != expected):
                return self.send(403, {'error': 'Solicitud no autorizada; recarga el panel local.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise Rejected('Cuerpo inválido.')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise Rejected('Objeto JSON requerido.')
                if self.path == '/api/start' and set(body) == {'service', 'duration'}:
                    ident = controller.start(body['service'], body['duration'])
                elif self.path == '/api/restore' and body == {}:
                    ident = controller.restore()
                else:
                    raise Rejected('Acción o campos no autorizados.')
                return self.send(200, {'id': ident})
            except (Rejected, ValueError, TypeError) as exc:
                return self.send(409, {'error': str(exc)})
            except Exception:
                return self.send(503, {'error': 'Fallo de acceso al clúster o almacenamiento; revisa el estado antes de reintentar.'})
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='Simulación local explícita; no accede a Kubernetes.')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--data', default='./data')
    args = parser.parse_args()
    os.makedirs(args.data, exist_ok=True)
    lock_file = open(os.path.join(args.data, 'controller.lock'), 'a')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Ya existe un controlador usando este directorio de datos.')
    controller = Controller(os.path.join(args.data, 'experiments.sqlite3'), Demo() if args.demo else Kubernetes())
    stopped = threading.Event()

    def reconcile():
        while not stopped.is_set():
            try:
                controller.tick()
            except Exception as exc:
                print('Reconciliación pendiente: ' + type(exc).__name__, flush=True)
            stopped.wait(2)

    worker = threading.Thread(target=reconcile, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(controller))
    server.daemon_threads = True

    def stop(*_):
        # Persist a recovery request on graceful shutdown; crash recovery also handles SIGKILL.
        controller.restore()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print('ChaosForge: http://localhost:%s — %s' % (args.port, controller.backend.mode), flush=True)
    try:
        server.serve_forever()
    finally:
        stopped.set()
        worker.join(timeout=15)
        server.server_close()
        # PVC retains the deadline/original replicas if this process is killed.


if __name__ == '__main__':
    main()
