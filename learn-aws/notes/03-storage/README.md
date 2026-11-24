# Storage

Where data lives: object, block, file storage and backups.

| Service folder | What it is | Status |
|---|---|---|
| `s3/` | Object storage, the base of every data lake (5 files) | written |
| `s3-tables-and-iceberg/` | Covered inside `s3/5-s3-tables-and-iceberg.md` | merged into s3 |
| `ebs-and-efs/` | Block disks for one server (EBS) and shared file systems (EFS) (2 files) | written |
| `aws-backup/` | Central backup plans, resource support matrix, Vault Lock and air-gapped vaults, cross-Region/account copies, restores and restore testing, Organizations, Audit Manager, security, cost (3 files) | written |
