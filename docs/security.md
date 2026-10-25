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
