# Seguridad y costos

- Nada de datos SIBI ni datos reales en el laboratorio.
- El acceso de TiderOps será solo lectura y se gestionará en otro repositorio.
- No subir claves JSON, terraform.tfstate, planes ni `.env` a GitHub.
- Workflow deploy es manual, requiere `approval=CREAR` y el entorno GitHub `gcp-lab` debe tener aprobadores.
- Crear la identidad de GitHub OIDC en Google Cloud por separado; no se incluye un secreto estático ni se crea una identidad con permisos excesivos.
- El bucket de state persiste tras `terraform destroy`; tiene costo de almacenamiento y necesita permisos restringidos.
- Terraform destroy no garantiza eliminación de objetos ajenos a Terraform.
- Un presupuesto de 30 USD solo notifica: NO apaga GKE.
