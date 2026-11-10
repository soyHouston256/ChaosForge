# Primer incremento de mecanismos

Implementación local de CF-001, CF-004 y CF-007, además del escalado existente. Los tres adaptadores nuevos están acotados a `cartservice`, contenedor `server`, Online Boutique `v0.10.4`. La compatibilidad de otra versión o servicio requiere adaptar y validar el contrato.

## Qué hace

| Mecanismo | Cambio | Efecto que exige |
|---|---|---|
| `wrong_port` | Cambia solo el puerto de `REDIS_ADDR` a 6380 | Destino efectivo cambiado, conexión fallida y error en carrito |
| `latency` | Añade una perturbación propia al proxy Redis preparado previamente | Lentitud de carrito y dependencia, incluso con HTTP 200 |
| `cpu_limit` | Reduce request/limit CPU a 50–200m y conserva los originales | Límite admitido en el contenedor correcto, períodos limitados y degradación |

Duraciones nuevas: 120/240 segundos de exposición; preparación máxima 180 segundos y límite absoluto persistido. Recuperación exige configuración/revisión y ventana funcional estable. Los umbrales iniciales del código necesitan calibración antes de una campaña: no son resultados medidos de rendimiento del clúster.

CPU registra la configuración del generador de carga y comprueba que no cambie. Las solicitudes HTTP del observador son una muestra; no se conoce el volumen de todo el tráfico. El piloto debe fijar carga comparable y documentar esas condiciones. Consumo alto por sí solo no acredita limitación.

## Ejecución local

```sh
python3 admin/server.py --demo --port 18092 --admin-port 18093 --data /tmp/chaosforge-demo
```

La simulación aparece identificada en el panel y en la evidencia. Esperar al menos tres muestras de línea base antes de iniciar. El caso CPU espera una ventana de métricas antes de acreditar efecto; la restauración también comprueba una ventana posterior. No abre conexiones a GCP. Las pruebas automatizadas avanzan un reloj simulado y cubren los estados sin esperar esos plazos reales.

## Preparación futura del laboratorio

Los mecanismos nuevos están deshabilitados por defecto en GKE. El despliegue base permite leer opcionalmente `chaosforge-experiments/mechanisms`; sin ese ConfigMap conserva escalado solamente. `admin/k8s/experiments.yaml` contiene permisos adicionales separados y habilita únicamente puerto. No lo aplica el pipeline del administrador.

Seguir el procedimiento de entrega de [DEPLOYMENT.md](DEPLOYMENT.md), siempre sin experimentos pendientes. La variable `CHAOSFORGE_FAULTS` admite `wrong_port,latency,cpu_limit`, pero habilitar una opción no omite sus comprobaciones previas.

Para latencia, preparar `admin/k8s/proxy.yaml` mediante `render_proxy.py` con una imagen `ghcr.io/shopify/toxiproxy@sha256:DIGEST`. Referencia verificada de Toxiproxy 2.13.0: digest multiarch `sha256:5d3dae09bc185dcc5ff6cf43abf6062a4a720aff0c4306a471e773acdcd107aa`. El manifiesto no modifica Boutique. La ruta `REDIS_ADDR=chaosforge-proxy:6379` y su línea base se preparan por separado antes de habilitar latencia.

El control del proxy queda restringido por NetworkPolicy al administrador. Su API no ofrece comparación atómica como Kubernetes: exige un único escritor administrativo. Detecta perturbaciones ajenas o modificadas, pero no garantiza exclusión frente a un operador que eluda ese aislamiento. No reiniciar ni modificar el proxy durante una prueba.

Para CPU, verificar permisos de lectura de Monitoring con la identidad del pod del administrador y calibrar la carga. Se utilizan cAdvisor/Managed Prometheus y la cadena de propietarios Deployment → ReplicaSet → Pod. La sesión local del desarrollador no acredita permisos del ServiceAccount. El adaptador hace dry-run de admisión antes de inyectar y comprueba recursos del pod después del rollout.

## Persistencia y evidencia

SQLite migra a esquema 2 conservando experimentos anteriores. No hacer downgrade del binario sobre esta base; mantener una copia coherente del PVC antes de actualizar y resolver las ejecuciones pendientes primero. Un conflicto conserva el bloqueo; restaurar otra vez solo reconcilia, no fuerza valores ajenos. La comparación de campos Kubernetes es atómica y preserva cambios de otros campos.

El observador captura operación, configuración permitida y CPU de forma independiente del estado del experimento. `/api/observations?start=TIMESTAMP&end=TIMESTAMP` expone solo esa proyección: máximo una hora, hasta 500 muestras, retención de 24 horas y cobertura explícita. No expone IDs de experimento, causa, snapshots de reversión o controles del proxy. Los registros administrativos conservan las observaciones usadas y la línea base como evidencia durable de cada ejecución.

El servidor sirve esa proyección en un puerto propio (`--port`, 8080 en el pod; 127.0.0.1:8092 por el túnel), que solo responde `/healthz` y `/api/observations`: `/api/state`, `/api/evidence/<id>`, el panel y los POST responden 404 allí y viven en el puerto de administración (`--admin-port`, 8081 en el pod; 127.0.0.1:8093 por el túnel). Tider lee la proyección mediante `AGENT_OBSERVER_URL=http://127.0.0.1:8092` y nunca recibe la URL de administración. Su herramienta resume períodos y conserva configuración, tiempos y cobertura. Rechaza simulaciones como evidencia de incidentes GCP. La configuración actual de Kubernetes sigue marcada como actual, no histórica.

## Estado al cierre

Probado localmente, con simulaciones y mocks de API; admisión CPU comprobada en GKE únicamente mediante dry-run del servidor. No se desplegaron estos cambios, no se instaló el proxy y no se aplicaron perturbaciones reales. El piloto de efecto/recuperación en GKE y la campaña causal permanecen pendientes.
