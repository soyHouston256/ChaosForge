# Desplegar el administrador mediante GitHub Actions

## Flujo integrado

El workflow existente `.github/workflows/deploy.yml` conserva `verify-auth` y `deploy` (Terraform + Online Boutique). Se añade **`deploy-admin`**, independiente de Terraform y del despliegue de Boutique. Usa la misma federación OIDC, cuenta `chaosforge-deployer`, protección de rama `main`, entorno `gcp-lab` y grupo de concurrencia `chaosforge-gcp-lab` con cancelación desactivada.

Secuencia del job protegido:

1. Checkout de la revisión seleccionada y validación compartida con CI: pruebas Python, sintaxis JavaScript/shell y rechazo de imágenes mutables.
2. Construcción Docker `linux/amd64` en el runner de GitHub; pruebas del controlador dentro de la imagen antes de publicarla. No utiliza Cloud Build.
3. Autenticación OIDC, acceso a GKE y comprobación de que el administrador existente no tiene un experimento pendiente. Un fallo de lectura bloquea el despliegue.
4. Publicación en el repositorio existente `us-central1-docker.pkg.dev/tider-ops/chaosforge`. Tag de trazabilidad: SHA del commit + ID de ejecución + intento.
5. Resolución del digest publicado y renderizado del manifiesto con `@sha256`. El tag nunca se usa para el Deployment.
6. Segunda comprobación de inactividad, aplicación exclusivamente de `admin/k8s/admin.yaml` y espera del rollout.
7. Verificación de lecturas reales de los seis servicios, ausencia de experimento pendiente, Service privado, NetworkPolicy, una réplica, PVC Bound y SQLite legible. El pod consulta su propio RBAC mediante SelfSubjectAccessReview; no escala ningún servicio para probar permisos.
8. Resumen en GitHub con commit, digest y comando de acceso privado.

La CI de push/PR y el despliegue comparten `.github/actions/check-admin/action.yml`. El deploy repite las pruebas sobre su propia revisión: no confía en que otro run haya pasado. `verify-auth` emite una credencial, pero no publica ni despliega. Solo el job protegido publica la imagen después de sus pruebas.

## Estado conocido de GCP: no recrear estos recursos

Según las últimas lecturas del 24/10/2026, realizadas antes de esta integración local:

- Clúster `chaosforge-lab`, namespace `boutique` y 12 deployments disponibles.
- Repositorio Docker `chaosforge` en `us-central1` creado y vacío.
- Los nodos usan la cuenta Compute predeterminada y ya tienen `roles/artifactregistry.reader` sobre ese repositorio.
- Cuenta `chaosforge-builder` creada para el intento anterior, con writer sobre el repositorio y objectViewer/objectCreator sobre `gs://tider-ops-chaosforge-build`.
- Bucket `tider-ops-chaosforge-build` contiene un archivo fuente del intento anterior. Cloud Build se habilitó; la solicitud de build falló con `PERMISSION_DENIED` y el listado no mostró builds ni imágenes.
- No se había creado `chaosforge-system`, ni PVC, Deployment, Role o RoleBinding del administrador.

**La ruta GitHub Actions no usa la cuenta builder, el bucket ni Cloud Build.** Se conservan sin modificarlos; cualquier limpieza futura corresponde al usuario. `admin/cloudbuild.yaml` y `.gcloudignore` quedan como registro del procedimiento anterior y no son invocados por CI/CD. No se ha ejecutado esta nueva ruta ni vuelto a consultar GCP durante su preparación.

## Prerrequisitos para que el usuario revise

### IAM y OIDC

La federación existente debe permitir el repositorio `soyHouston256/ChaosForge`, la rama `main` y la cuenta `chaosforge-deployer@tider-ops.iam.gserviceaccount.com`. El entorno `gcp-lab` mantiene sus revisores y restricciones; no se agregan claves JSON.

**Permiso pendiente conocido:** el writer asignado al builder anterior no sirve a `chaosforge-deployer`. Esta última necesita `roles/artifactregistry.writer` únicamente sobre el repositorio `chaosforge`. Si el usuario confirma que aún falta, puede ejecutarlo personalmente:

```bash
gcloud artifacts repositories add-iam-policy-binding chaosforge \
  --project=tider-ops --location=us-central1 \
  --member=serviceAccount:chaosforge-deployer@tider-ops.iam.gserviceaccount.com \
  --role=roles/artifactregistry.writer
```

La cuenta de despliegue ya tenía roles amplios heredados del bootstrap (`container.admin`, `compute.networkAdmin`, `serviceusage.serviceUsageAdmin`). Esta integración **no añade ni necesita ampliar** los dos últimos. Para obtener credenciales necesita `container.clusters.get`; para aplicar objetos necesita autorización Kubernetes efectiva. Reutilizar OIDC no equivale a verificar todos esos permisos.

### Kubernetes

El primer despliegue necesita crear el namespace `chaosforge-system`; gestionar su ServiceAccount, PVC, Deployment, Service y NetworkPolicy; y crear/actualizar el Role y RoleBinding restringidos en `boutique`. Las reglas anti-escalación de Kubernetes también exigen que la identidad esté autorizada a conceder las reglas de ese Role. No conceder `cluster-admin` o `escalate` global por defecto si falla: revisar la denegación concreta o hacer el bootstrap limitado personalmente.

Los chequeos necesitan leer esos recursos, observar pods/rollout y abrir `pods/portforward` y `pods/exec` **en chaosforge-system**. Exec ejecuta dos diagnósticos fijos: revisión de permisos con la identidad del pod y lectura de SQLite. No requiere impersonación de ServiceAccounts ni lectura de sus tokens desde el runner. La cuenta del administrador conserva únicamente GET de seis Deployments/scale, PATCH de sus scale y LIST de HPA en `boutique`.

El PVC usa `standard-rwo`, observado en el clúster. Autopilot puede ajustar recursos; su admisión, el montaje del volumen y los permisos efectivos siguen pendientes de la primera ejecución real. No escalar el administrador por encima de una réplica, no borrar el PVC y no instalar una segunda instancia con otro volumen.

### Conectividad y mantenimiento

El runner necesita alcanzar Artifact Registry y el endpoint de la API GKE. El acceso desde el equipo local verificado anteriormente no prueba acceso desde GitHub-hosted runners. Si las redes autorizadas o un endpoint privado lo impiden, usar un runner con la conectividad correspondiente; no abrir la API a todo Internet como solución automática.

Durante el despliegue, no iniciar experimentos desde otra sesión. La comprobación de inactividad se repite antes de aplicar, pero no es un bloqueo de mantenimiento distribuido. Si una prueba empieza en ese intervalo, el reinicio del controlador priorizaría su restauración. El pipeline no llama `/api/start` ni `/api/restore` y no ejecuta los scripts de caos.

## Pasos que ejecuta el usuario

1. Trabajar desde `/Users/maxhoustonramirezmartel/code/utec/5/integrador/project/code/chaosforge`. Revisar el diff local, especialmente `deploy.yml`, la acción compartida, `admin/` y `scripts/*-admin.sh`. Los documentos locales previos son trabajo separado; no incluirlos accidentalmente.
2. Preparar su commit y push o PR. Ejemplo de selección explícita, ajustable antes del commit:

   ```bash
   git add .github/workflows/ci.yml .github/workflows/deploy.yml \
     .github/actions/check-admin/action.yml .gitignore README.md admin \
     scripts/deploy-admin.sh scripts/verify-admin.sh docs/security.md docs/architecture.md docs/README.md
   git diff --cached
   git commit -m "Add private ChaosForge admin and GitHub Actions deployment"
   git push
   ```

3. Esperar CI verde y llevar la revisión a `main` mediante el proceso habitual.
4. Revisar el permiso de publicación y los prerrequisitos anteriores. No recrear el repositorio ni activar Cloud Build.
5. En GitHub → **Actions → ChaosForge - Auth check and deployment → Run workflow**, seleccionar rama `main`, **mode `deploy-admin`** y **approval `ADMIN`**. Aprobar `gcp-lab` cuando GitHub lo solicite. `deploy` sigue significando infraestructura + Boutique; no elegirlo para actualizar solo el administrador.
6. Esperar el job verde y guardar el commit/digest del resumen. Si falla después de publicar, la imagen puede existir; si falla después de aplicar, el Deployment puede haber cambiado. No hay rollback automático ni borrado del PVC. Inspeccionar el paso fallido antes de reintentar.
7. Abrir el panel desde el equipo propio:

   ```bash
   export KUBECONFIG=/tmp/chaosforge-admin-kubeconfig
   gcloud container clusters get-credentials chaosforge-lab \
     --project=tider-ops --region=us-central1
   kubectl -n chaosforge-system port-forward --address 127.0.0.1 \
     service/chaosforge-admin 8092:8080
   ```

   Visitar http://localhost:8092. Confirmar la banda de datos reales. No se crea endpoint público ni acceso persistente desde el runner. La prueba inicial no incluye inyecciones.

## Validación local y límites

Se validaron YAML con el parser local, sintaxis shell/JavaScript, renderizado por digest y 17 pruebas Python, incluidas tres que usan kubectl/curl falsos para comprobar que una lectura denegada o un experimento pendiente bloquean `apply`. En la imagen se ejecutan las 14 pruebas de runtime; las tres de scripts se omiten allí porque los scripts de despliegue no se empaquetan.

No se ejecutaron Docker, GitHub Actions, publicación, despliegue ni cambios IAM/GCP para validar esta integración. El parser YAML no sustituye el validador de Actions y la comprobación local no garantiza admisión Autopilot o conectividad del runner. La ruta real será comprobada en la ejecución que dispare el usuario.
