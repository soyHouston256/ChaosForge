# Levantar el laboratorio en una cuenta nueva

ChaosForge no guarda ningún identificador de cuenta en el código. Para moverlo a otro
proyecto de Google Cloud basta un proyecto vacío con facturación y un comando.

## Qué crea cada pieza

| Pieza | Dónde | Cuándo | Qué crea |
|---|---|---|---|
| Bootstrap | `infrastructure/bootstrap` + `scripts/bootstrap.sh` | Una vez por proyecto, desde tu máquina | APIs, bucket de estado versionado, repositorio Docker `chaosforge`, cuenta `chaosforge-deployer` con sus roles, pool y proveedor OIDC de GitHub, roles de la cuenta de los nodos, presupuesto con alertas |
| Laboratorio | `infrastructure/terraform` | Cada `deploy` / `destroy`, desde GitHub Actions | VPC, subred, GKE Autopilot |
| Aplicación | `scripts/deploy-boutique.sh` | Cada `deploy` | Online Boutique con el componente de Cloud Operations |
| Administrador | modo `deploy-admin` | Cuando cambia `admin/` | Imagen por digest, namespace `chaosforge-system` |

El bootstrap usa **estado local** (`infrastructure/bootstrap/terraform.tfstate`, ignorado por
Git) porque el bucket de estado remoto es uno de los recursos que crea. Consérvalo en la
máquina desde la que lo ejecutaste; si se pierde, los recursos se pueden importar.

## Pasos

1. Crea el proyecto y enlaza la facturación.
2. `gcloud auth login`, `gcloud auth application-default login` y `gcloud config set project TU-PROYECTO`.
3. `BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX ./scripts/bootstrap.sh` (sin `BILLING_ACCOUNT` no se crea el presupuesto).
   Con `gh` autenticado, publica solo las variables `GCP_*` en el repositorio; si no, las imprime para copiarlas.
4. En GitHub, comprueba que exista el entorno `gcp-lab` con revisor obligatorio y rama `main`.
5. Actions: `verify-auth`, luego `deploy` con `CREAR`, luego `deploy-admin` con `ADMIN`.
6. Al terminar la sesión: `destroy` con `DESTRUIR`.

## Seguridad

- Sin claves JSON: GitHub obtiene credenciales temporales por OIDC, solo desde la rama `main` del repositorio configurado.
- El presupuesto **solo notifica**; lo que detiene los cobros es `destroy`.
- `destroy` conserva el bucket de estado, el repositorio de imágenes y las identidades. El historial del administrador (PVC) se elimina con el clúster.
- La cuenta Compute predeterminada recibe solo lo que los nodos necesitan: envío de logs y métricas, lectura de métricas y lectura del repositorio de imágenes.
