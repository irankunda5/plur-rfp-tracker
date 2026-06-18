# Lightsail Deployment Complete ✅

## Status: Infrastructure Deployed Successfully

**Deployment Time:** ~20 minutes (including RDS provisioning)  
**Date:** 2026-06-18

---

## Access Information

### Application URL
```
http://52.207.113.238
```

### Application API Health Check
```
http://52.207.113.238/api/health
```

### SSH Access
```
ssh ec2-user@52.207.113.238
```
*(Use Lightsail console to get SSH key)*

---

## Infrastructure Created

### Compute
- **Lightsail Instance:** `plur-rfp-tracker-app`
  - Bundle: `small_2_0` (1GB RAM, 1 CPU, 40GB SSD)
  - Public IP: `52.207.113.238` (static)
  - Private IP: `172.26.0.118`
  - Availability Zone: `us-east-1a`
  - Blueprint: Amazon Linux 2

### Database
- **RDS PostgreSQL:** `plur-rfp-tracker-postgres`
  - Instance Class: `db.t3.micro`
  - Engine: PostgreSQL 15.7
  - Endpoint: `plur-rfp-tracker-postgres.c63k2iewojax.us-east-1.rds.amazonaws.com`
  - Port: 5432
  - Database: `rfptracker`
  - Username: `rfpAdmin`
  - Backup Retention: 1 day (free tier limit)

### Storage & Backups
- **S3 Backup Bucket:** `plur-rfp-tracker-backup-039840515309`
  - Versioning: Enabled
  - Encryption: AES256
  - Public Access: Blocked
  - Lifecycle: Auto-archive to Glacier after 30 days

### Networking & Security
- **Static IP:** `52.207.113.238`
- **Security Group (RDS):** Allows PostgreSQL from 0.0.0.0/0
- **Lightsail Firewall:** Ports 22 (SSH), 80 (HTTP), 443 (HTTPS) open

---

## Terraform State

**Backend:** S3 + DynamoDB
- **Bucket:** `plur-rfp-tracker-lightsail-state`
- **Key:** `prod/terraform.tfstate`
- **Lock Table:** `terraform-locks`
- **Region:** `us-east-1`

---

## What's Running on the Instance

The Lightsail instance is currently executing the `user_data.sh` initialization script, which:

1. Installs Docker, Docker Compose, Git, Nginx, Certbot
2. Clones the application from GitHub
   - Repository: `https://github.com/aronhsiao-pl/plur-rfp-tracker-v2`
   - Branch: `deployment/lightsail`
3. Builds and starts Docker container with:
   - Application: FastAPI on port 8081
   - Nginx reverse proxy on port 80/443
4. Sets up daily backup cron job to S3
5. Configures systemd service for auto-restart on crash

**Current Status:** Application is initializing (first startup can take 2-5 minutes)

---

## Next Steps

### Verify Deployment
```bash
# Wait 2-3 minutes for app to start, then test:
curl http://52.207.113.238/api/health

# SSH to instance (get key from Lightsail console):
ssh ec2-user@52.207.113.238

# View logs on instance:
docker-compose logs -f
```

### Optional: Setup HTTPS with Let's Encrypt
Edit `terraform.tfvars`:
```hcl
domain_name = "your-domain.com"  # Add your domain
enable_https = true
```
Then reapply: `terraform apply`

### Optional: Setup CloudWatch Monitoring
Already enabled in RDS (PostgreSQL logs). To view:
```bash
aws logs tail /aws/rds/instance/plur-rfp-tracker-postgres --follow
```

### Cost Summary
```
Lightsail (small_2_0):  $5.00/month
RDS (db.t3.micro):     $16.00/month
S3 + data transfer:    $1.00/month
Total:                 ~$22.00/month
```

---

## Terraform Files & Commands

### Key Files
- `lightsail/main.tf` - Provider & backend
- `lightsail/lightsail.tf` - Lightsail instance
- `lightsail/rds.tf` - RDS PostgreSQL  
- `lightsail/s3.tf` - Backup bucket
- `lightsail/iam.tf` - IAM roles
- `lightsail/user_data.sh` - Instance initialization script
- `lightsail/terraform.tfvars` - Configuration values

### Commands
```bash
cd lightsail

# Show current infrastructure:
terraform output

# SSH via Terraform:
terraform output -raw ssh_command

# View RDS endpoint:
terraform output rds_endpoint

# View backup bucket:
terraform output s3_backup_bucket

# Destroy entire infrastructure (careful!):
terraform destroy
```

---

## Account Transfer (~15 minutes)

To move this setup to another AWS account:

1. **In current account (A):**
   ```bash
   aws rds create-db-snapshot \
     --db-instance-identifier plur-rfp-tracker-postgres \
     --db-snapshot-identifier backup-2026-06-18
   ```

2. **Copy snapshot to account (B) via AWS Console**

3. **In target account (B):**
   ```bash
   cd lightsail
   terraform init  # Uses your AWS credentials
   terraform apply  # Deploys fresh infrastructure
   ```

4. **Restore database from snapshot** (done separately)

See `ACCOUNT_TRANSFER.md` for full step-by-step guide.

---

## Troubleshooting

### Application not responding on port 8081
- Wait 2-3 minutes for initialization
- SSH to instance and check: `docker-compose logs app`
- Verify RDS is available: `aws rds describe-db-instances --db-instance-identifier plur-rfp-tracker-postgres`

### RDS connection issues
```bash
# Check RDS status:
aws rds describe-db-instances \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --query 'DBInstances[0].DBInstanceStatus'

# Should output: "available"
```

### Nginx/HTTPS issues
```bash
ssh ec2-user@52.207.113.238
certbot certificates
systemctl status nginx
docker-compose logs nginx
```

---

## Success Indicators ✅

- [x] Terraform plan validated
- [x] IAM roles created
- [x] S3 backup bucket created
- [x] RDS PostgreSQL instance created
- [x] Lightsail instance created
- [x] Static IP assigned
- [x] Firewall ports open (22, 80, 443)
- [ ] Application responding to health check (pending - initializing)
- [ ] Database connected and working
- [ ] Daily backups running

---

**Deployment completed by:** Claude Code  
**Infrastructure as Code:** Terraform  
**Provider:** AWS Lightsail + RDS + S3  
**Transferable:** Yes (to any AWS account in ~15 minutes)
