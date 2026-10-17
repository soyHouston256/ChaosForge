# Experimentos

## CHAOS-001 (implementado): `cartservice-unavailable`
- Inyección: `kubectl scale deployment/cartservice --replicas=0` en namespace `boutique`, durante 60 segundos.
- Resultado esperado: operaciones dependientes del carrito fallan; comprobar logs/errores.
- Reversión: trap restaura el número original de réplicas; script `scripts/restore.sh` de emergencia.
- Limitación: **no** simula indisponibilidad específica de Redis; tampoco garantiza recovery si Cloud Shell termina abruptamente. Ejecutar solo en entorno mock, monitoreando y sin exposición a usuarios reales.
- Baseline: comprobar servicio, HTTP, pods; capturar timestamps, telemetría y la causa conocida fuera de acceso del futuro agente.

## Futuro: Redis network partition, latency, payment timeout
Aún **no implementados**. Requieren un inyector que sea compatible con GKE Autopilot, reversión automática a nivel clúster y runbooks probados.
