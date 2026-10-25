"""Durable, single-experiment controller. No shell execution or arbitrary targets."""
import json
import sqlite3
import threading
import time
import uuid

SERVICES = {
    'cartservice': ('Carrito', 'Gestiona los carritos de compra.', 'cart'),
    'paymentservice': ('Pagos', 'Procesa los pagos de la tienda.', 'card'),
    'productcatalogservice': ('Catálogo', 'Productos y su información.', 'tag'),
    'shippingservice': ('Envíos', 'Calcula las opciones de envío.', 'truck'),
    'currencyservice': ('Monedas', 'Convierte los precios de la tienda.', 'coins'),
    'recommendationservice': ('Recomendaciones', 'Sugiere productos relacionados.', 'star'),
}
TERMINAL = ('completed', 'cancelled')


class Rejected(Exception):
    pass


class Controller:
    def __init__(self, path, backend, clock=time.time):
        self.backend, self.clock = backend, clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY, service TEXT NOT NULL, uid TEXT NOT NULL,
                original INTEGER NOT NULL, duration INTEGER NOT NULL,
                started REAL NOT NULL, deadline REAL NOT NULL, state TEXT NOT NULL,
                restored REAL, finished REAL, issue TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active ON experiments ((1))
                WHERE state NOT IN ('completed','cancelled');
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, experiment TEXT NOT NULL,
                at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
        ''')
        # A restarted controller restores immediately, even before the saved deadline.
        with self.lock, self.db:
            active = self.active()
            if active:
                self._state(active['id'], 'restoring')
                self._event(active['id'], 'restart_recovery', {'message': 'Servidor reiniciado; restauración prioritaria.'})

    def active(self):
        row = self.db.execute("SELECT * FROM experiments WHERE state NOT IN ('completed','cancelled')").fetchone()
        return dict(row) if row else None

    def _event(self, ident, kind, data):
        self.db.execute('INSERT INTO events(experiment,at,kind,data) VALUES(?,?,?,?)',
                        (ident, self.clock(), kind, json.dumps(data)))

    def _state(self, ident, state):
        self.db.execute('UPDATE experiments SET state=? WHERE id=?', (state, ident))

    def _issue(self, ident, message):
        old = self.db.execute('SELECT issue FROM experiments WHERE id=?', (ident,)).fetchone()[0]
        with self.db:
            if old != message:
                self._event(ident, 'attention', {'message': message})
            self.db.execute('UPDATE experiments SET issue=? WHERE id=?', (message, ident))

    def start(self, service, duration):
        if service not in SERVICES or type(duration) is not int or duration not in (30, 60, 120):
            raise Rejected('Servicio o duración no autorizados.')
        with self.lock:
            if self.active():
                raise Rejected('Ya existe un experimento activo; primero debe recuperarse.')
            target = self.backend.get(service)
            if target['replicas'] < 1 or target['ready'] != target['replicas']:
                raise Rejected('El servicio debe tener todas sus réplicas disponibles.')
            if self.backend.autoscaled(service):
                raise Rejected('El servicio tiene HPA; este administrador no modifica autoscalers.')
            probes = self.backend.probe()
            if not probes or any(p['status'] != 200 for p in probes):
                raise Rejected('La comprobación HTTP base no está sana; no se inyectará una falla.')
            ident, now = str(uuid.uuid4()), self.clock()
            # Commit original replicas + identity + deadline BEFORE any mutating API call.
            with self.db:
                self.db.execute('INSERT INTO experiments VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (ident, service, target['uid'], target['replicas'], duration,
                                 now, now + duration, 'injecting', None, None, None))
                self._event(ident, 'recorded', {'original_replicas': target['replicas'], 'deadline': now + duration, 'baseline_http': probes})
            try:
                self.backend.scale(service, 0, target['uid'])
                with self.db:
                    self._state(ident, 'active')
                    self._event(ident, 'scale_requested', {'replicas': 0})
            except Exception as exc:
                # A timeout can mean the write succeeded. Always reconcile restoration.
                with self.db:
                    self._state(ident, 'restoring')
                self._issue(ident, 'Inyección incierta; se restaurará: ' + str(exc))
            return ident

    def restore(self):
        with self.lock, self.db:
            active = self.active()
            if active:
                self._state(active['id'], 'restoring')
                self._event(active['id'], 'restore_requested', {'message': 'Restauración manual de los servicios afectados por este administrador.'})
            return active['id'] if active else None

    def tick(self):
        with self.lock:
            active = self.active()
            if not active:
                return
            ident, service = active['id'], active['service']
            try:
                if active['state'] == 'active' and self.clock() >= active['deadline']:
                    with self.db:
                        self._state(ident, 'restoring')
                        self._event(ident, 'deadline', {'message': 'Plazo alcanzado.'})
                    active['state'] = 'restoring'
                if active['state'] == 'restoring':
                    self.backend.scale(service, active['original'], active['uid'])
                    with self.db:
                        self._state(ident, 'verifying')
                        self.db.execute('UPDATE experiments SET restored=?,issue=NULL WHERE id=?', (self.clock(), ident))
                        self._event(ident, 'replicas_restored', {'replicas': active['original']})
                    active['state'] = 'verifying'
                target = self.backend.get(service)
                if target['uid'] != active['uid']:
                    raise Rejected('El Deployment fue reemplazado; no se modificará su nueva identidad. Requiere revisión del operador.')
                probes = self.backend.probe()
                # Sampled observations, not inferred events or made-up telemetry.
                with self.db:
                    self._event(ident, 'observation', {'deployment': target, 'http': probes})
                if active['state'] == 'verifying':
                    if target['replicas'] != active['original']:
                        with self.db:
                            self._state(ident, 'restoring')
                    elif target['ready'] == active['original'] and probes and all(p['status'] == 200 for p in probes):
                        with self.db:
                            self._state(ident, 'completed')
                            self.db.execute('UPDATE experiments SET finished=?,issue=NULL WHERE id=?', (self.clock(), ident))
                            self._event(ident, 'recovered', {'message': 'Réplicas disponibles y sondas HTTP 200. Las sondas no validan todas las operaciones de negocio.'})
                    elif self.clock() - (active['restored'] or self.clock()) > 180:
                        self._issue(ident, 'Recuperación aún no verificada tras 180 s. El administrador sigue comprobando; nuevos experimentos bloqueados.')
            except Exception as exc:
                self._issue(ident, str(exc))

    def snapshot(self):
        with self.lock:
            experiments = [dict(r) for r in self.db.execute('SELECT * FROM experiments ORDER BY started DESC LIMIT 50')]
            for exp in experiments:
                rows = self.db.execute('SELECT at,kind,data FROM events WHERE experiment=? ORDER BY id DESC LIMIT 100', (exp['id'],)).fetchall()
                exp['events'] = [dict(at=r['at'], kind=r['kind'], data=json.loads(r['data'])) for r in reversed(rows)]
            return {'active': self.active(), 'history': experiments, 'server_time': self.clock()}

    def evidence(self, ident):
        with self.lock:
            row = self.db.execute('SELECT * FROM experiments WHERE id=?', (ident,)).fetchone()
            if not row:
                raise Rejected('Experimento desconocido.')
            return {'experiment': dict(row), 'events': [dict(at=r['at'], kind=r['kind'], data=json.loads(r['data'])) for r in self.db.execute('SELECT * FROM events WHERE experiment=? ORDER BY id', (ident,))], 'mode': self.backend.mode}
