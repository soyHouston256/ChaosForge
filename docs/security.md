# Seguridad y costos

- Nada de datos SIBI ni datos reales en el laboratorio.
- El acceso de TiderOps será solo lectura y se gestionará en otro repositorio.
- No subir claves JSON, terraform.tfstate, planes ni `.env` a GitHub.
- El workflow es manual: `deploy` requiere `approval=CREAR`; `deploy-admin` requiere `approval=ADMIN`. Ambos despliegues se limitan a `main` y al entorno `gcp-lab`, que debe tener aprobadores.
- El administrador usa acceso local por port-forward, Service ClusterIP y namespace separado. Su ServiceAccount solo puede consultar y escalar los seis Deployments autorizados, y consultar HPA; no tiene permisos de Secrets, exec ni eliminación de pods. El runner usa su identidad OIDC distinta para desplegar y ejecutar diagnósticos.
- Los commits, pushes y despliegues los ejecuta el usuario. Los [prerrequisitos IAM y de conectividad](../admin/DEPLOYMENT.md) se revisan antes del primer run; no se amplían permisos automáticamente.
- Crear la identidad de GitHub OIDC en Google Cloud por separado; no se incluye un secreto estático ni se crea una identidad con permisos excesivos.
- El bucket de state persiste tras `terraform destroy`; tiene costo de almacenamiento y necesita permisos restringidos.
- Terraform destroy no garantiza eliminación de objetos ajenos a Terraform.
- Un presupuesto de 30 USD solo notifica: NO apaga GKE.

## Aislamiento del ground truth (Tider)

- El servidor del administrador escucha en dos puertos. `observer` (8080 en el pod, 127.0.0.1:8092 por el túnel) sirve solo `/healthz` y `/api/observations`; cualquier otra ruta, GET o POST, responde el mismo 404 opaco. `admin` (8081 en el pod, 127.0.0.1:8093 por el túnel) sirve el panel, `/api/state`, `/api/evidence/<id>`, el token CSRF y los POST. Tider se configura solo con `AGENT_OBSERVER_URL=http://127.0.0.1:8092`.
- Pruebas: `admin/tests/test_http.py` cubre la matriz 404/200 por puerto, el rechazo de POST en el observador aun con token válido y que la respuesta de `/api/observations`, durante experimentos de los cuatro mecanismos, no contiene IDs de experimento, nombres ni IDs de mecanismo, ni claves de causa, objetivo, réplicas originales o eventos. `verify-admin.sh` comprueba el 404 del observador tras cada despliegue.
- Riesgos residuales (no cubiertos por estas pruebas):
  - **Eventos de Kubernetes del namespace `boutique`** (`ScalingReplicaSet`, reinicios por cambio de spec): muestran el síntoma y su hora, y el escalado a cero lo hace visible por diseño. Mitigación: el registrador de Tider guarda solo la lista de campos permitidos (réplicas, generación, hash del spec, `*_ADDR`, recursos) y nunca etiquetas o anotaciones `chaosforge*`; no se leen eventos del namespace `chaosforge-system`.
  - **Logs del propio ChaosForge** (contenedor `admin` en `chaosforge-system`) y **Cloud Audit Logs** con el principal `system:serviceaccount:chaosforge-system:chaosforge-admin`: hoy el servidor no registra solicitudes ni IDs, pero el actor del PATCH aparece en auditoría. Mitigación: el barrido de Tider excluye `resource.labels.namespace_name="chaosforge-system"` y las entradas `protoPayload.authenticationInfo.principalEmail` de esa ServiceAccount, y la identidad de Tider no recibe `roles/logging.privateLogViewer` (Data Access). Debe comprobarse con la prueba de grep del id y del mecanismo sobre la ventana congelada y los prompts (A13).
  - **`REDIS_ADDR=chaosforge-proxy:6379`** en los mecanismos de latencia: es configuración real del Deployment y el observador la expone a propósito; su tratamiento queda prerregistrado en el protocolo (P9).
