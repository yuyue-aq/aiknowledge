# 运行与备份运维

备份脚本针对本地 Docker Compose 环境，数据库和对象存储必须成对备份。脚本不会输出数据库密码或 MinIO 密钥。

```powershell
cd D:\develop\aiknowledge
.\ops\backup.ps1 -OutputDir .\backups
```

脚本使用 Compose 中的 Postgres 容器执行 `pg_dump`，并使用 PATH 中的 MinIO Client（`mc`）镜像私有桶。若本机没有 `mc`，脚本会保留已生成的数据库备份并提示安装客户端。

恢复会覆盖当前数据库和桶内容，必须显式确认；建议先停止 API/Worker，并在隔离环境演练：

```powershell
.\ops\restore.ps1 `
  -PostgresBackup .\backups\postgres-YYYYMMDD-HHMMSS.dump `
  -MinioBackup .\backups\minio-YYYYMMDD-HHMMSS `
  -ConfirmRestore
```

恢复后执行 `alembic upgrade head`、`/health/ready` 和项目提供的合成数据冒烟测试，确认迁移、依赖和检索链路均可用。
