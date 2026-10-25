# ChaosForge — Online Boutique fault laboratory

**Propósito:** ambiente mock reproducible para generar **logs, métricas y trazas** mediante Online Boutique de Google y ejecutar inyecciones reversibles. **No incluye agentes TiderOps.**

Proyecto GCP: `tider-ops`, región `us-central1`, clúster `chaosforge-lab` (GKE Autopilot), namespace `boutique`.
La [bitácora del 17/10/2026](docs/GCP_SETUP.md) registra el despliegue observado de Online Boutique,
el estado remoto GCS y la autenticación OIDC. Los pasos siguientes son procedimientos de instalación;
no es necesario recrear el laboratorio para probar el agente.

La consola del agente está en [../tider](../tider/README.md), con escenarios locales y conector Cloud Logging.

## Arquitectura
Ver [`docs/architecture.md`](docs/architecture.md). Fuente oficial de la app: https://github.com/GoogleCloudPlatform/microservices-demo (rama `v0` por defecto; se imprime el commit clonado). El código de Online Boutique se **descarga** a `vendor/` y NO va incluido en este ZIP. Se recomienda fijar a un tag/commit concreto antes de resultados académicos.

Para revisar o desplegar el panel aprobado, empieza por [Administrador web](admin/README.md) y su [flujo oficial en GitHub Actions](admin/DEPLOYMENT.md). Los pasos de Cloud Shell siguientes corresponden al aprovisionamiento original del laboratorio, no son necesarios para desplegar solo el administrador.

## Inicio desde Google Cloud Shell

```bash
# Clonar TU repo luego de subir este contenido a GitHub
# git clone https://github.com/soyHouston256/chaosforge.git
cd chaosforge
./scripts/check.sh
./scripts/preflight.sh

# Crear bucket persistente de Terraform state, UNA VEZ (puede generar pequeños costos)
./scripts/bootstrap-state.sh
export STATE_BUCKET=chaosforge-tfstate-TU_NUMERO_DE_PROYECTO

# Revisar cuidadosamente qué se creará; NO aplica cambios
./scripts/plan.sh

# CREA recursos facturables; pide confirmación explícita
./scripts/apply.sh

# Descarga Online Boutique oficial y configura Cloud Operations
./scripts/deploy-boutique.sh
./scripts/validate.sh

# Experimento v0 controlado: caída cartservice, NO Redis
./scripts/chaos-cart.sh
# Recuperación manual de emergencia si fuese necesaria
./scripts/restore.sh

# Destruir al finalizar, para evitar costos (bucket state permanece)
./scripts/destroy.sh
```

**Dependencias:** `git`, `terraform`, `gcloud`, `kubectl`, `python3`; autenticación gcloud activa y permisos necesarios. Ejecutar en Cloud Shell, no requiere claves JSON. La configuración de Cloud Operations se obtiene del repo oficial mediante Kustomize.

## Automatización GitHub Actions
- `ci.yml`: validaciones sin acceso a GCP (push/PR).
- `deploy.yml`: ejecución manual con OIDC. `deploy` + `CREAR` aplica infraestructura y Boutique; `deploy-admin` + `ADMIN` publica y despliega solo el administrador. Ambos despliegues requieren `main` y el entorno protegido `gcp-lab`. El proveedor OIDC, la cuenta y el proyecto están definidos en el workflow actual; no lee secretos llamados `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA` o `STATE_BUCKET`. Ver [CI/CD del administrador](admin/DEPLOYMENT.md) para los permisos pendientes.
- Destrucción deliberadamente manual desde Cloud Shell hasta revisar los permisos y el estado remoto.

## Alcance real
- Terraform: GKE Autopilot, VPC, subred, APIs GCP. State remoto GCS inicializado con script de bootstrap.
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

El [administrador de ChaosForge](admin/README.md) permite gestionar fallos acotados desde un panel privado, con estado persistente y recuperación tras reinicios. Incluye demo local explícita, pruebas y manifiestos GKE preparados; todavía no está desplegado en el clúster.

```bash
python3 admin/server.py --demo --port 8091 --data /tmp/chaosforge-admin-demo
```

Abrir http://localhost:8091. La demo no accede a GCP.

El despliegue del administrador se integra en el workflow existente con el modo **`deploy-admin`** y aprobación **`ADMIN`**, sin ejecutar Terraform ni redesplegar Online Boutique. Consulta [CI/CD y prerrequisitos](admin/DEPLOYMENT.md). Todos los commits, pushes y despliegues los ejecuta el usuario.
