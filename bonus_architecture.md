# Bonus Architecture — Airflow on AWS at Production Scale

This document covers how to deploy the same Airflow setup into a production AWS environment: resilient, secure, observable, and cost-efficient.

## High-Level Architecture

Internet
    │
    ▼
Route 53 (DNS)
    │
    ▼
Application Load Balancer (ALB)
    │
    ▼
Amazon EKS Cluster
    ├── Airflow Webserver  (Deployment, 2 replicas)
    ├── Airflow Scheduler  (Deployment, 2 replicas — HA mode)
    └── Airflow Workers    (Deployment + HPA, 2–10 replicas)
         │
         ├── Amazon ElastiCache (Redis) — Celery broker
         ├── Amazon RDS PostgreSQL (Multi-AZ) — metadata DB
         ├── Amazon S3 — DAG storage + log archive
         └── AWS Secrets Manager — credentials + Fernet key

## Component Decisions

### Compute — Amazon EKS

All Airflow components run as Kubernetes workloads on EKS. The CeleryExecutor is retained for autoscaling workers independently of the scheduler.

- Webserver and Scheduler run as `Deployment` objects with `replicas: 2` for HA.
- Workers run with a `HorizontalPodAutoscaler` targeting CPU utilisation at 70%, scaling between 2 and 10 replicas.
- Node groups use `m5.xlarge` on-demand instances for scheduler/webserver (stable latency) and `m5.large` Spot instances for workers (cost savings on batch work).
- Cluster Autoscaler is enabled to add/remove EC2 nodes based on pending pod pressure.

### Helm deployment

Airflow is deployed using the official [Apache Airflow Helm chart](https://airflow.apache.org/docs/helm-chart/stable/index.html). This handles:

- Init containers for DB migrations (`airflow db upgrade`)
- Persistent volume claims for logs
- ConfigMaps for `airflow.cfg` overrides
- ServiceAccounts with IRSA for S3 and Secrets Manager access

```bash
helm repo add apache-airflow https://airflow.apache.org
helm upgrade --install airflow apache-airflow/airflow \
  --namespace airflow \
  --values values-production.yaml
```

### Metadata database — Amazon RDS PostgreSQL (Multi-AZ)

- Engine: PostgreSQL 14
- Instance: `db.t3.medium` (scale to `db.r5.large` if scheduler lag increases)
- Multi-AZ: enabled — automatic failover in case of AZ failure
- Automated backups: 7-day retention
- Credentials: stored in AWS Secrets Manager, injected into pods via the Secrets Store CSI Driver
- No public access — only accessible from within the VPC via the EKS security group

### Message broker — Amazon ElastiCache (Redis)

- Engine: Redis 7.x
- Mode: Cluster mode disabled (single primary, one read replica)
- No persistence required — the broker is transient state only
- Placed in a private subnet, accessible only from worker pods

### DAG deployment — GitOps via CI/CD

DAGs are version-controlled in Git. A GitHub Actions workflow handles deployment on merge to `main`:

```
Push to main
    │
    ▼
GitHub Actions
    ├── Run linting (ruff, pylint)
    ├── Run DAG integrity checks (airflow dags list-import-errors)
    ├── Upload DAGs to S3 (s3://company-airflow-dags/dags/)
    └── Sync S3 → EKS volume (via git-sync sidecar or S3 sync CronJob)
```

The git-sync sidecar pattern is preferred: each Airflow pod runs a sidecar container that pulls from the Git repo on a configurable interval (default 60s). This eliminates the need to rebuild Docker images for DAG changes.

### Secrets management — AWS Secrets Manager

No credentials are stored in environment variables or ConfigMaps. All secrets are:

- Stored in AWS Secrets Manager (Fernet key, DB password, Redis auth token)
- Injected at pod startup via the Secrets Store CSI Driver
- Accessed by pods using IAM Roles for Service Accounts (IRSA) — no long-lived credentials

```yaml
# IRSA annotation on Airflow ServiceAccount
annotations:
  eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/airflow-secrets-role
```

### Logging — CloudWatch + S3

- Task logs are written to `/opt/airflow/logs/` and streamed to CloudWatch Logs via Fluent Bit DaemonSet.
- Logs older than 30 days are automatically transitioned to S3 via a CloudWatch Logs export task, with S3 Lifecycle rules moving them to Glacier after 90 days.
- Airflow's `remote_logging` is enabled, pointing at `s3://company-airflow-logs/`.

### Monitoring — Prometheus + Grafana + CloudWatch Alarms

- Airflow exposes a StatsD endpoint; `statsd-exporter` converts metrics to Prometheus format.
- Prometheus scrapes Airflow metrics every 15s.
- Grafana dashboards cover: DAG run success/failure rates, task queue depth, scheduler heartbeat lag, worker pod count, database connection pool saturation.
- CloudWatch Alarms fire on: scheduler heartbeat missing for > 5 minutes, worker pod count = 0, RDS storage below 20%, ElastiCache memory above 80%.
- PagerDuty integration via CloudWatch SNS for on-call alerting.

### Networking and security

```
VPC (10.0.0.0/16)
├── Public subnets  (10.0.1.0/24, 10.0.2.0/24) — ALB only
└── Private subnets (10.0.3.0/24, 10.0.4.0/24) — EKS nodes, RDS, Redis
```

- ALB sits in public subnets; all application traffic stays private.
- Security groups enforce least-privilege: workers can reach Redis and RDS; webserver cannot reach Redis directly.
- Pod-level network policies (Calico) block lateral movement between namespaces.
- AWS WAF on the ALB blocks common web attacks against the Airflow UI.
- TLS termination at the ALB using an ACM certificate; all internal traffic over HTTP within the private VPC.

### Access control

- Airflow RBAC is enabled. Users authenticate via SAML SSO (Okta).
- Kubernetes RBAC: the Airflow service account has the minimum necessary permissions (no cluster-admin).
- IAM roles are scoped to specific S3 prefixes and Secrets Manager paths — no wildcard policies.


## Cost Optimisation

| Area | Strategy |
| Workers | Spot instances (60–70% cost saving vs on-demand) with on-demand fallback |
| RDS | Reserved instance for 1 year (40% saving) once workload is stable |
| Logging | Tiered storage: CloudWatch (30d) → S3 Standard (60d) → Glacier |
| Idle nodes | Cluster Autoscaler scales node groups to 0 at night if no DAGs running |

## Disaster Recovery

| Scenario | Recovery mechanism |

| AZ failure | EKS multi-AZ node groups + RDS Multi-AZ automatic failover |
| DB corruption | RDS automated snapshots (7-day retention) + point-in-time recovery |
| Accidental DAG deletion | Git history; re-deploy takes < 2 minutes |
| Full region failure | RDS cross-region read replica can be promoted (RPO: ~5min, RTO: ~30min) |

## Deployment Checklist (Production Go-Live)

- [ ] EKS cluster provisioned (Terraform)
- [ ] RDS PostgreSQL Multi-AZ created
- [ ] ElastiCache Redis cluster created
- [ ] Secrets loaded into AWS Secrets Manager
- [ ] Airflow Fernet key generated and stored
- [ ] Helm chart deployed with production values
- [ ] ALB Ingress and ACM certificate configured
- [ ] Fluent Bit DaemonSet deployed
- [ ] Prometheus + Grafana deployed
- [ ] CloudWatch Alarms configured
- [ ] GitHub Actions CI/CD pipeline tested
- [ ] RBAC and SSO configured
- [ ] Disaster recovery tested (RDS failover, Spot interruption simulation)