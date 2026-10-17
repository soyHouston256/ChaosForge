# ChaosForge — Online Boutique fault laboratory

**Propósito:** ambiente mock reproducible para generar **logs, métricas y trazas** mediante Online Boutique de Google y ejecutar inyecciones reversibles. **No incluye agentes TiderOps.**

Proyecto GCP previsto: `tider-ops`, región `us-central1`, clúster `chaosforge-lab` (GKE Autopilot). No hay ningún recurso creado por este paquete.

## Arquitectura
Ver [`docs/architecture.md`](docs/architecture.md). Fuente oficial de la app: https://github.com/GoogleCloudPlatform/microservices-demo (rama `v0` por defecto; se imprime el commit clonado). El código de Online Boutique se **descarga** a `vendor/` y NO va incluido en este ZIP. Se recomienda fijar a un tag/commit concreto antes de resultados académicos.

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
- `deploy.yml`: manual, OIDC, configurado para *environment* `gcp-lab`; **no estará operativo** hasta crear el Workload Identity Pool, proveedor, service account de despliegue, permisos mínimos y definir secretos `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA` y variable `STATE_BUCKET` en el repo. No otorgar rol Owner al deployer.
- Destrucción deliberadamente manual desde Cloud Shell hasta revisar los permisos y el estado remoto.

## Alcance real
- Terraform: GKE Autopilot, VPC, subred, APIs GCP. State remoto GCS inicializado con script de bootstrap.
- App: script instala la **demo oficial** y variante Cloud Operations con Kustomize; **no** está validado aún contra una cuenta GCP real.
- Chaos: primer fallo replicable de Cart Service; la recuperación automática depende de que el proceso script siga en ejecución (trap). No hay fault injection específica de Redis aún.
- Evidencia: logs básicos y conectores de Cloud Operations de la demo. Exportación de datasets y dashboards académicos están pendientes.
- **No debe usarse contra SIBI producción.**

## Costos
GKE Autopilot y otros recursos generan cargos. Antes de aplicar, revisar `terraform plan` y presupuesto. `terraform destroy` debe ejecutarse al terminar las sesiones. Las alertas de presupuesto no frenan los cobros.

## Guías
- [`docs/experiments.md`](docs/experiments.md)
- [`docs/security.md`](docs/security.md)
