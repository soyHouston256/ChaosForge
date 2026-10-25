# Administrador web de ChaosForge

Aplicación separada de Online Boutique y de Tider. Python 3.9+ y biblioteca estándar, sin dependencias Python externas. El navegador nunca ejecuta kubectl ni suministra comandos, namespaces o URLs al servidor.

## Abrir localmente

Desde la raíz de ChaosForge:

```bash
python3 admin/server.py --demo --port 8091 --data /tmp/chaosforge-admin-demo
```

Abrir http://localhost:8091. La banda **DEMO LOCAL · datos simulados** es permanente en este modo: los botones solo alteran un backend en memoria; no acceden a GCP. El historial y los plazos sí usan SQLite real. No usar el mismo directorio de datos para una demo y un despliegue real.

```bash
python3 -m unittest discover -s admin/tests -v
node --check admin/static/app.js
```

## Comportamiento

- Seis objetivos permitidos: carrito, pagos, catálogo, envíos, monedas y recomendaciones. La lista está fijada en el servidor y repetida como `resourceNames` en RBAC.
- Solo caída por escalado a cero, con duraciones 30/60/120 s. No manipula Redis, frontend, infraestructura ni Tider.
- Rechaza un inicio si el Deployment no está disponible, existe un HPA para el objetivo, las sondas base no responden 200 o hay otro experimento pendiente.
- Antes del primer PATCH, confirma en SQLite (WAL, synchronous FULL) el UID del Deployment, sus réplicas originales y el plazo absoluto. Índice único en la base, bloqueo de proceso sobre el volumen y lock de controlador impiden dos experimentos simultáneos.
- Un reconciliador independiente del navegador revisa el plazo cada 2 s. Solicita restauración, reintenta errores y comprueba las réplicas y HTTP por separado. Los timeouts de la API pueden retrasar la ejecución respecto al contador; el contador señala el plazo de solicitud, no una garantía de recuperación completa.
- Al reiniciar el proceso, todo experimento pendiente entra inmediatamente en restauración, incluso si todavía no venció. Una respuesta perdida de Kubernetes se trata como escritura incierta y activa restauración.
- El UID y resourceVersion se comprueban al modificar `/scale`. No se toca un Deployment eliminado y recreado con otro UID. Este caso bloquea nuevas pruebas y requiere revisión manual.
- «Restaurar todos los afectados» y «Restaurar ahora» actúan exclusivamente sobre el experimento pendiente registrado por esta instancia. No escanean ni reparan indiscriminadamente `boutique`.
- La recuperación solo se marca cuando las réplicas originales están disponibles y las sondas internas `/` y `/cart` responden 200. Pasados 180 s de verificación se muestra atención, se sigue observando y se bloquean nuevas pruebas.
- Estas sondas no demuestran que funcionen pagos, checkout o todas las operaciones del servicio seleccionado. No se crean compras para verificar negocio.
- Historial: últimos 50 experimentos en pantalla; evidencia JSON completa por experimento. Los eventos son observaciones del controlador y respuestas de API/HTTP, **no una importación de Kubernetes Events ni Cloud Audit Logs**. En demo toda observación de servicios/HTTP es simulada y el JSON incluye el modo.
- Cloud Logging, Monitoring y Trace todavía no están conectados a este panel; se muestran explícitamente como no disponibles. La validación previa del laboratorio no se incorpora como si fuera evidencia de este administrador.

## Despliegue mediante el CI/CD existente

La ruta oficial es **GitHub Actions → `deploy-admin`**, con OIDC y el entorno protegido `gcp-lab`. Construye y prueba en el runner, publica en Artifact Registry y despliega por digest sin Terraform ni cambios en Online Boutique. El usuario hace todos los commits, pushes y ejecuciones.

Ver [procedimiento integrado, estado de recursos y permisos pendientes](DEPLOYMENT.md). Cloud Build no es un requisito de esta ruta. El usuario informó que el pipeline terminó en verde y que ve las tarjetas reales por port-forward. Esta confirmación procede del usuario; no se volvió a consultar GCP al preparar el script de acceso.

## Recuperación y límites operativos

Cerrar el navegador o interrumpir port-forward no detiene el reconciliador. Si el contenedor reinicia y el PVC permanece accesible, retoma la recuperación. Si el clúster, el controlador, el disco o la API permanecen caídos, no puede garantizarse restauración en el plazo. No hay controlador externo independiente en esta versión.

Si se pierde el acceso al panel, consultar primero la evidencia persistente y restaurar **solo** el Deployment y el número original registrados. No asumir que la réplica original era 1. No borrar el PVC ni desinstalar el administrador con experimentos pendientes. Si se reemplazó el UID, revisar el nuevo recurso manualmente; no hay botón para eludir esa protección.

La base no tiene purga automática; revisar capacidad y preservar evidencias antes de una limpieza. Los logs operativos no incluyen tokens. El historial no identifica operadores individuales: el acceso previsto es privado para un operador de laboratorio. Para acceso multiusuario remoto harían falta autenticación, autorización por usuario y auditoría de identidad adicionales.

## Validación realizada

17 pruebas automatizadas (14 del runtime y 3 de guardas del despliegue): exclusión mutua, commit antes de mutación, plazos, réplicas originales, reintentos, reinicio, SIGKILL del servidor y reapertura de la base, bloqueo de segunda instancia, separación de HTTP y disponibilidad, allowlist, HPA y protección Host/Origin/CSRF.

Flujo de navegador probado en demo: iniciar, recargar página conservando experimento, bloquear otros objetivos, observar HTTP simulado 500, restaurar y obtener historial recuperado. Diseño comprobado a 1440 px y 390 px sin desbordamiento horizontal. JavaScript validado con `node --check`; manifiestos procesados con `kubectl create --dry-run=client --validate=false`. Esto verifica estructura de objetos, no admisión Autopilot, montaje PVC, RBAC efectivo ni conectividad real. Esas verificaciones quedan para el despliegue.

## Abrir el panel real desde el Mac

Con el administrador desplegado, ejecutar desde cualquier carpeta:

```bash
/Users/maxhoustonramirezmartel/code/utec/5/integrador/project/code/chaosforge/scripts/abrir-panel.sh
```

Esperar `Forwarding from`, abrir http://127.0.0.1:8092 y mantener la terminal abierta. Ctrl+C cierra el túnel. Este comando usa la sesión gcloud existente y un kubeconfig temporal; no despliega ni modifica servicios. La demo local continúa siendo un modo distinto, marcado explícitamente como simulación.

El lanzador cuenta con cinco pruebas locales usando comandos simulados; verifican guardas, dirección loopback y limpieza del kubeconfig. La comprobación del puerto ocurre antes de abrir el túnel: si otro proceso ocupa el puerto después, kubectl informa el fallo y se limpia el archivo temporal.
