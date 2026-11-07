"""Persistent lifecycle for configuration, latency and CPU experiments."""
import json
import statistics
import uuid

from controller import Conflict, Rejected
from faults import AdmissionChanged, CATALOG, TARGET, parameters
from observations import healthy, latency, throttle

PREPARATION_SECONDS = 180
RECOVERY_SECONDS = 180
STABLE_SECONDS = 10


def samples(controller, after, limit=200):
    rows = controller.db.execute('SELECT data FROM observations WHERE at>=? ORDER BY at DESC LIMIT ?', (after, limit)).fetchall()
    return [json.loads(r[0]) for r in reversed(rows)]


def start(controller, service, duration, mechanism, values):
    if service != TARGET or mechanism not in CATALOG or type(duration) is not int or duration not in (120, 240):
        raise Rejected('Objetivo, mecanismo o duración no autorizados.')
    parameters(mechanism, values)
    c = controller
    with c.lock:
        if c.active():
            raise Rejected('Hay una ejecución pendiente; primero debe recuperarse.')
        now = c.clock()
        baseline = samples(c, now - 60)[-5:]
        if len(baseline) < 3 or baseline[-1]['at'] < now - 15 or not all(healthy(s) for s in baseline):
            raise Rejected('Se necesitan al menos tres observaciones recientes y sanas de la operación.')
        if mechanism == 'cpu_limit' and any(throttle(s) is None or throttle(s) >= .1 for s in baseline):
            raise Rejected('CPU requiere métricas completas y una línea base sin limitación significativa.')
        if c.backend.autoscaled(service):
            raise Rejected('El servicio tiene HPA; experimento no compatible.')
        ident = str(uuid.uuid4())
        plan = c.backend.faults.prepare(mechanism, values, ident)
        target = c.backend.get(service)
        if target['uid'] != plan['uid'] or target['replicas'] < 1 or not target.get('rolled_out'):
            raise Rejected('El objetivo cambió o no completó su rollout.')
        plan.update(baseline_latency_ms=statistics.median(latency(s) for s in baseline),
                    baseline_dependency_ms=statistics.median(s['dependency']['elapsed_ms'] for s in baseline),
                    baseline_observations=baseline, preparation_deadline=now + PREPARATION_SECONDS,
                    stable_seconds=STABLE_SECONDS, recovery_seconds=RECOVERY_SECONDS)
        # Snapshot and an absolute safety deadline are durable before any mutation.
        with c.db:
            c.db.execute('INSERT INTO experiments(id,service,uid,original,duration,started,deadline,state,mechanism,plan) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (ident, service, plan['uid'], target['replicas'], duration, now,
                          now + PREPARATION_SECONDS + duration, 'injecting', mechanism, json.dumps(plan)))
            c._event(ident, 'recorded', {'message': 'Estado y plazos persistidos antes de aplicar.', 'baseline_samples': len(baseline)})
        try:
            plan = c.backend.faults.apply(plan)
            with c.db:
                c.db.execute('UPDATE experiments SET plan=?,state=? WHERE id=?', (json.dumps(plan), 'effect_pending', ident))
                c._event(ident, 'mutation_requested', {'message': 'Cambio solicitado; efecto todavía por comprobar.'})
            if plan.get('admission_changed'):
                with c.db:
                    c.db.execute("UPDATE experiments SET state='restoring',result='admission_changed' WHERE id=?", (ident,))
                c._issue(ident, 'Admisión cambió los parámetros; se restaura sin acreditar el escenario solicitado.')
        except Conflict as exc:
            with c.db:
                c._state(ident, 'conflict')
            c._issue(ident, str(exc))
        except Exception:
            with c.db:
                c.db.execute("UPDATE experiments SET state='restoring',result='write_uncertain' WHERE id=?", (ident,))
            c._issue(ident, 'Resultado de escritura incierto; reconciliación prioritaria.')
        return ident


def effect(plan, observation):
    if observation.get('coverage') != 'complete':
        return False
    if plan['kind'] == 'wrong_port':
        return (observation['configuration']['redis_address'] == plan['applied']['address']
                and not observation['dependency']['success']
                and any(p['status'] != 200 for p in observation.get('http', [])))
    slow = latency(observation) is not None and latency(observation) > max(plan['baseline_latency_ms'] * 1.5, plan['baseline_latency_ms'] + 25)
    if plan['kind'] == 'latency':
        return (slow and observation['dependency']['elapsed_ms'] > plan['baseline_dependency_ms'] + plan['parameters']['latency_ms'] * .5)
    limited = throttle(observation, after=plan['ready_at'] + 60)
    return slow and limited is not None and limited >= .1


def recovered(plan, observation, restored):
    if not healthy(observation) or observation['at'] < restored:
        return False
    if plan['kind'] in ('latency', 'cpu_limit') and latency(observation) > max(plan['baseline_latency_ms'] * 1.5, plan['baseline_latency_ms'] + 25):
        return False
    if plan['kind'] == 'latency' and observation['dependency']['elapsed_ms'] > max(plan['baseline_dependency_ms'] * 1.5, plan['baseline_dependency_ms'] + 25):
        return False
    if plan['kind'] == 'cpu_limit':
        limited = throttle(observation, after=restored + 60)
        return limited is not None and limited < .1
    return True


def tick(c, active):
    if active['state'] == 'conflict':
        return
    ident = active['id']
    try:
        plan = json.loads(active['plan'])
        if plan.get('version') != 1:
            raise Conflict('Versión de restauración desconocida; se conserva el bloqueo.')
        now = c.clock()
        if active['state'] in ('injecting', 'effect_pending', 'effect_observed'):
            finished = active['effect_at'] is not None and now >= active['effect_at'] + active['duration']
            expired = now >= active['deadline'] or (active['effect_at'] is None and now >= plan['preparation_deadline'])
            if finished or expired:
                with c.db:
                    c.db.execute("UPDATE experiments SET state='restoring',result=COALESCE(result,?) WHERE id=?",
                                 ('effect_observed' if active['effect_at'] is not None else 'effect_not_observed', ident))
                    c._event(ident, 'deadline', {'message': 'Exposición o plazo máximo alcanzado; restauración prioritaria.'})
                active['state'] = 'restoring'
        if active['state'] == 'restoring':
            c.backend.faults.restore(plan)
            with c.db:
                c.db.execute("UPDATE experiments SET state='verifying_recovery',restored=?,steady_since=NULL,issue=NULL,result=COALESCE(result,?) WHERE id=?",
                             (now, 'interrupted', ident))
                c._event(ident, 'configuration_restored', {'message': 'Campos restaurados; falta verificar operación y revisión.'})
            active.update(state='verifying_recovery', restored=now, steady_since=None)
        observations = samples(c, max(active['started'], now - 30))
        latest = observations[-1] if observations and observations[-1]['at'] >= now - 15 else None
        if latest and latest['at'] != plan.get('last_observation_at'):
            plan['last_observation_at'] = latest['at']
            with c.db:
                c._event(ident, 'observation', latest)
                c.db.execute('UPDATE experiments SET plan=? WHERE id=?', (json.dumps(plan), ident))
        if active['state'] in ('effect_pending', 'effect_observed'):
            ready = c.backend.faults.matches(plan)
            if active['effect_at'] is not None and not ready:
                with c.db:
                    c.db.execute("UPDATE experiments SET state='restoring',result='effect_interrupted' WHERE id=?", (ident,))
                c._issue(ident, 'La perturbación dejó de estar aplicada; se reconcilia sin acreditar exposición completa.')
                return
            if active['effect_at'] is not None and latest is None:
                with c.db:
                    c.db.execute("UPDATE experiments SET result=COALESCE(result,'coverage_incomplete') WHERE id=?", (ident,))
            if ready and 'ready_at' not in plan:
                plan['ready_at'] = now
                with c.db:
                    c.db.execute('UPDATE experiments SET plan=? WHERE id=?', (json.dumps(plan), ident))
            if ready and latest and latest['at'] >= plan['ready_at'] and effect(plan, latest) and active['effect_at'] is None:
                with c.db:
                    c.db.execute("UPDATE experiments SET state='effect_observed',effect_at=? WHERE id=?", (now, ident))
                    c._event(ident, 'effect_observed', {'message': 'Efecto observado en telemetría operativa.', 'observed_at': latest['at']})
        elif active['state'] in ('verifying_recovery', 'recovery_unverified'):
            ok = c.backend.faults.matches(plan, restored=True) and latest and recovered(plan, latest, active['restored'])
            steady = active['steady_since'] if ok else None
            if ok and steady is None:
                steady = latest['at']
            with c.db:
                c.db.execute('UPDATE experiments SET steady_since=? WHERE id=?', (steady, ident))
                window = [s for s in observations if steady is not None and s['at'] >= steady]
                if ok and len(window) >= 3 and latest['at'] - steady >= plan['stable_seconds'] and all(recovered(plan, s, active['restored']) for s in window):
                    c.db.execute("UPDATE experiments SET state='completed',finished=?,issue=NULL WHERE id=?", (now, ident))
                    c._event(ident, 'recovered', {'message': 'Configuración, revisión y operación recuperadas durante la ventana requerida.'})
                elif now - active['restored'] > plan['recovery_seconds']:
                    c._state(ident, 'recovery_unverified')
                    c._issue(ident, 'Recuperación todavía no verificada; nuevos experimentos bloqueados.')
    except AdmissionChanged as exc:
        with c.db:
            if active['state'] in ('injecting', 'effect_pending', 'effect_observed'):
                c.db.execute("UPDATE experiments SET state='restoring',result='admission_changed' WHERE id=?", (ident,))
            else:
                c._state(ident, 'recovery_unverified')
        c._issue(ident, str(exc))
    except Conflict as exc:
        with c.db:
            c._state(ident, 'conflict')
        c._issue(ident, str(exc))
    except Exception:
        # A failed read must never suppress the next deadline reconciliation.
        c._issue(ident, 'Comprobación incompleta; se conserva la ejecución y se reintentará.')
