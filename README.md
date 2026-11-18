# ChaosForge — Online Boutique fault laboratory

**Propósito:** ambiente mock reproducible para generar **logs, métricas y trazas** mediante Online Boutique de Google y ejecutar inyecciones reversibles. **No incluye agentes TiderOps.**

Región `us-central1`, clúster `chaosforge-lab` (GKE Autopilot), namespace `boutique`. **El proyecto de Google Cloud no está escrito en el código:** se toma de `PROJECT_ID` (o del proyecto activo de `gcloud`) y de las variables del repositorio en GitHub, de modo que el laboratorio se puede levantar en cualquier cuenta. Ver [Levantar el laboratorio en una cuenta nueva](docs/bootstrap.md).

La consola del agente está en [../tider](../tider/README.md), con escenarios locales y conector Cloud Logging.

## Arquitectura
Ver [`docs/architecture.md`](docs/architecture.md). Fuente oficial de la app: https://github.com/GoogleCloudPlatform/microservices-demo (rama `v0` por defecto; se imprime el commit clonado). El código de Online Boutique se **descarga** a `vendor/` y NO va incluido en este ZIP. Se recomienda fijar a un tag/commit concreto antes de resultados académicos.

Para revisar o desplegar el panel aprobado, empieza por [Administrador web](admin/README.md) y su [flujo oficial en GitHub Actions](admin/DEPLOYMENT.md). Los pasos de Cloud Shell siguientes corresponden al aprovisionamiento original del laboratorio, no son necesarios para desplegar solo el administrador.

## Inicio en una cuenta nueva

```bash
gcloud auth login && gcloud auth application-default login
export PROJECT_ID=tu-proyecto            # proyecto vacío con facturación activa

# UNA VEZ: APIs, bucket de estado, repositorio de imágenes, identidad de despliegue,
# federación OIDC con GitHub y presupuesto. Publica las variables en GitHub.
BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX ./scripts/bootstrap.sh
```

Después, todo se hace desde **GitHub → Actions → ChaosForge - Auth check and deployment**:

| Modo | Aprobación | Qué hace |
|---|---|---|
| `verify-auth` | — | Comprueba la federación OIDC. No crea nada. |
| `deploy` | `CREAR` | Terraform (VPC, subred, GKE Autopilot) + Online Boutique. **Facturable.** |
| `deploy-admin` | `ADMIN` | Construye, publica y despliega solo el administrador. |
| `destroy` | `DESTRUIR` | Elimina cargas, clúster y red para detener los cobros. |

Los scripts locales siguen disponibles para operar a mano con la misma configuración:

```bash
./scripts/check.sh && ./scripts/preflight.sh
./scripts/plan.sh          # no aplica cambios
./scripts/apply.sh         # CREA recursos facturables; pide confirmación
./scripts/deploy-boutique.sh && ./scripts/validate.sh
./scripts/chaos-cart.sh    # experimento v0: caída de cartservice
./scripts/restore.sh       # recuperación manual de emergencia
./scripts/destroy.sh       # el bucket de estado permanece
```

**Dependencias:** `git`, `terraform`, `gcloud`, `kubectl`, `python3`; autenticación gcloud activa y permisos necesarios. Ejecutar en Cloud Shell, no requiere claves JSON. La configuración de Cloud Operations se obtiene del repo oficial mediante Kustomize.

## Automatización GitHub Actions
- `ci.yml`: validaciones sin acceso a GCP (push/PR).
- `deploy.yml`: ejecución manual con OIDC y cuatro modos (tabla anterior). Todos los que cambian algo requieren `main` y el entorno protegido `gcp-lab`. El proveedor OIDC, la cuenta de servicio, el proyecto y el bucket de estado se leen de las variables del repositorio `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `GCP_PROJECT_ID` y `GCP_STATE_BUCKET`, que publica `scripts/bootstrap.sh`. No hay secretos ni claves JSON. Ver [CI/CD del administrador](admin/DEPLOYMENT.md).
- La CI rechaza cualquier proyecto escrito a mano en el código desplegable.

## Alcance real
- Terraform: dos pilas. `infrastructure/bootstrap` (una vez, estado local): bucket de estado, Artifact Registry, identidad de despliegue, OIDC y presupuesto. `infrastructure/terraform` (estado remoto GCS): GKE Autopilot, VPC, subred y APIs.
- App: demo oficial y variante Cloud Operations con Kustomize; servicios y LoadBalancer observados en GKE. La telemetría extremo a extremo se verifica por separado.
- Chaos: primer fallo replicable de Cart Service; la recuperación automática depende de que el proceso script siga en ejecución (trap). No hay fault injection específica de Redis aún.
- Evidencia: logs básicos y conectores de Cloud Operations de la demo. Exportación de datasets y dashboards académicos están pendientes.
- **No debe usarse contra SIBI producción.**

## Costos
GKE Autopilot y otros recursos generan cargos. Antes de aplicar, revisar `terraform plan` y presupuesto. `terraform destroy` debe ejecutarse al terminar las sesiones. Las alertas de presupuesto no frenan los cobros.

## Guías
- [`docs/experiments.md`](docs/experiments.md)
- [`docs/security.md`](docs/security.md)

## Administrador web

El [administrador de ChaosForge](admin/README.md) permite gestionar fallos acotados desde un panel privado, con estado persistente y recuperación tras reinicios. Incluye demo local explícita, pruebas y manifiestos GKE preparados; el usuario confirmó posteriormente el pipeline verde y la lectura real mediante port-forward.

```bash
python3 admin/server.py --demo --port 8090 --admin-port 8091 --data /tmp/chaosforge-admin-demo
```

Abrir http://localhost:8091 (puerto de administración; el 8090 es el observador y solo sirve `/healthz` y `/api/observations`). La demo no accede a GCP.

El despliegue del administrador se integra en el workflow existente con el modo **`deploy-admin`** y aprobación **`ADMIN`**, sin ejecutar Terraform ni redesplegar Online Boutique. Consulta [CI/CD y prerrequisitos](admin/DEPLOYMENT.md). Todos los commits, pushes y despliegues los ejecuta el usuario.

Para abrir el panel real desde este repositorio: `./scripts/abrir-panel.sh`. Mantén la terminal abierta y visita el panel en http://127.0.0.1:8093 cuando aparezca `Forwarding from`; el mismo túnel lleva el observador a http://127.0.0.1:8092, la única URL que se configura en Tider (`AGENT_OBSERVER_URL`). Ctrl+C cierra ambos túneles.
