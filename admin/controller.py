"""Durable, single-experiment controller. No shell execution or arbitrary targets."""
import json
import math
import sqlite3
import threading
import time
import uuid

SERVICES = {
    'frontend': ('Tienda web', 'Punto de entrada; su caída impide navegar.', 'web'),
    'redis-cart': ('Redis del carrito', 'Almacenamiento del carrito; reiniciar puede perder datos no persistidos.', 'coins'),
    'checkoutservice': ('Checkout', 'Coordina la compra y sus dependencias.', 'cart'),
    'emailservice': ('Correo', 'Confirmaciones de compra.', 'mail'),
    'adservice': ('Anuncios', 'Anuncios de la tienda.', 'tag'),
    'loadgenerator': ('Generador de tráfico', 'Detiene tráfico sintético; no implica caída de la tienda.', 'activity'),
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


class Conflict(Rejected):
    """The experiment no longer owns the value it would overwrite."""


class Controller:
    def __init__(self, path, backend, clock=time.time):
        self.backend, self.clock = backend, clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        if self.db.execute('PRAGMA user_version').fetchone()[0] > 2:
            raise Rejected('Base de datos de una versión más reciente; no se permite downgrade.')
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
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, at REAL NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS observations_time ON observations(at);
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(experiments)')}
        with self.db:
            for name, definition in {
                'mechanism': "TEXT NOT NULL DEFAULT 'scale_zero'", 'plan': 'TEXT',
                'effect_at': 'REAL', 'steady_since': 'REAL', 'result': 'TEXT',
            }.items():
                if name not in columns:
                    self.db.execute('ALTER TABLE experiments ADD COLUMN ' + name + ' ' + definition)
            self.db.execute('PRAGMA user_version=2')
        # A restarted controller restores immediately, even before the saved deadline.
        with self.lock, self.db:
            active = self.active()
            if active and active['state'] != 'conflict':
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

    def start(self, service, duration, mechanism='scale_zero', parameters=None):
        if mechanism != 'scale_zero':
            from experiments import start
            return start(self, service, duration, mechanism, {} if parameters is None else parameters)
        if parameters:
            raise Rejected('El escalado no admite parámetros adicionales.')
        if service not in SERVICES or type(duration) is not int or duration not in (30, 60, 120):
            raise Rejected('Servicio o duración no autorizados.')
        with self.lock:
            if self.active():
                raise Rejected('Ya existe un experimento activo; primero debe recuperarse.')
            target = self.backend.get(service)
            if target['replicas'] < 1 or target['ready'] != target['replicas'] or not target.get('rolled_out', True):
                raise Rejected('El servicio debe tener todas sus réplicas disponibles.')
            if self.backend.autoscaled(service):
                raise Rejected('El servicio tiene HPA; este administrador no modifica autoscalers.')
            probes = self.backend.probe()
            if not probes or any(p['status'] != 200 for p in probes):
                raise Rejected('La comprobación HTTP base no está sana; no se inyectará una falla.')
            ident, now = str(uuid.uuid4()), self.clock()
            # Commit original replicas + identity + deadline BEFORE any mutating API call.
            with self.db:
                self.db.execute('INSERT INTO experiments(id,service,uid,original,duration,started,deadline,state,restored,finished,issue) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (ident, service, target['uid'], target['replicas'], duration,
                                 now, now + duration, 'injecting', None, None, None))
                self._event(ident, 'recorded', {'original_replicas': target['replicas'], 'deadline': now + duration, 'baseline_http': probes})
            try:
                self.backend.compare_scale(service, 0, target['uid'], target['replicas'])
                with self.db:
                    self._state(ident, 'active')
                    self._event(ident, 'scale_requested', {'replicas': 0})
            except Conflict as exc:
                with self.db:
                    self._state(ident, 'conflict')
                self._issue(ident, str(exc))
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
            if active['mechanism'] != 'scale_zero':
                from experiments import tick
                return tick(self, active)
            if active['state'] == 'conflict':
                return
            ident, service = active['id'], active['service']
            try:
                if active['state'] == 'active' and self.clock() >= active['deadline']:
                    with self.db:
                        self._state(ident, 'restoring')
                        self._event(ident, 'deadline', {'message': 'Plazo alcanzado.'})
                    active['state'] = 'restoring'
                if active['state'] == 'restoring':
                    target = self.backend.get(service)
                    if target['uid'] != active['uid']:
                        raise Conflict('Identidad distinta; no se sobrescribirá el recurso.')
                    if target['replicas'] != active['original']:
                        self.backend.compare_scale(service, active['original'], active['uid'], 0)
                    with self.db:
                        self._state(ident, 'verifying')
                        self.db.execute('UPDATE experiments SET restored=?,issue=NULL WHERE id=?', (self.clock(), ident))
                        self._event(ident, 'replicas_restored', {'replicas': active['original']})
                    active['state'] = 'verifying'
                target = self.backend.get(service)
                if target['uid'] != active['uid']:
                        raise Conflict('El Deployment fue reemplazado; no se modificará su nueva identidad. Requiere revisión del operador.')
                probes = self.backend.probe()
                # Sampled observations, not inferred events or made-up telemetry.
                with self.db:
                    self._event(ident, 'observation', {'deployment': target, 'http': probes})
                if active['state'] == 'verifying':
                    if target['replicas'] != active['original']:
                        raise Conflict('Réplicas modificadas durante recuperación; se conserva el cambio ajeno.')
                    elif target['ready'] == active['original'] and target.get('rolled_out', True) and probes and all(p['status'] == 200 for p in probes):
                        with self.db:
                            self._state(ident, 'completed')
                            self.db.execute('UPDATE experiments SET finished=?,issue=NULL WHERE id=?', (self.clock(), ident))
                            self._event(ident, 'recovered', {'message': 'Réplicas disponibles y sondas HTTP 200. Las sondas no validan todas las operaciones de negocio.'})
                    elif self.clock() - (active['restored'] or self.clock()) > 180:
                        self._issue(ident, 'Recuperación aún no verificada tras 180 s. El administrador sigue comprobando; nuevos experimentos bloqueados.')
            except Conflict as exc:
                with self.db:
                    self._state(ident, 'conflict')
                self._issue(ident, str(exc))
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

    def observe(self):
        from observations import capture
        sample = capture(self.backend, self.clock())
        with self.lock, self.db:
            self.db.execute('INSERT INTO observations(at,data) VALUES(?,?)', (sample['at'], json.dumps(sample)))
            self.db.execute('DELETE FROM observations WHERE at<?', (self.clock() - 86400,))
        return sample

    def operational_evidence(self, start, end, limit=500):
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end)) or not start < end or end - start > 3600:
            raise Rejected('Ventana de observaciones inválida; máximo una hora.')
        with self.lock:
            rows = self.db.execute('SELECT data FROM observations WHERE at>=? AND at<=? ORDER BY at LIMIT ?', (start, end, limit + 1)).fetchall()
            first = self.db.execute('SELECT MIN(at) FROM observations').fetchone()[0]
        return {'observations': [json.loads(r[0]) for r in rows[:limit]], 'truncated': len(rows) > limit,
                'retained_since': first, 'requested_start': start, 'requested_end': end,
                'coverage': 'observed_samples_only', 'mode': self.backend.mode}
