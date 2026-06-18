# Lightsail Deployment - 10 Minute Production Setup

**Total Time: ~10 minutes**  
**Monthly Cost: ~$45-50 (Lightsail $5-20 + RDS Postgres $16-30)**  
**Production Ready: ✅ Yes**  
**Transferable to Another Account: ✅ Yes**

---

## Architecture

```
Lightsail Instance (Amazon Linux 2)
├── Docker & Docker Compose
├── FastAPI Application
├── Nginx Reverse Proxy
└── HTTPS (Let's Encrypt, auto-renewing)

RDS PostgreSQL (managed database)
├── Automated backups (30 days)
└── Encrypted storage

S3 Backup Bucket
├── Daily backups from Lightsail
└── Cross-account transferable
```

---

## Phase 1: Prerequisites (2 minutes)

### 1.1 Install Terraform
```bash
# macOS
brew install terraform

# Windows (via Chocolatey)
choco install terraform

# Linux
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
sudo apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main"
sudo apt-get update && sudo apt-get install terraform
```

### 1.2 Setup AWS Credentials
```bash
aws configure

# Enter:
# AWS Access Key ID: [your-key]
# AWS Secret Access Key: [your-secret]
# Default region: us-east-1
# Default output format: json
```

### 1.3 Create Terraform State Backend (one-time)
```bash
# Create S3 bucket
aws s3api create-bucket \
  --bucket plur-rfp-tracker-lightsail-state \
  --region us-east-1

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket plur-rfp-tracker-lightsail-state \
  --versioning-configuration Status=Enabled

# Create DynamoDB table
aws dynamodb create-table \
  --table-name terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
  --region us-east-1
```

---

## Phase 2: Configure Terraform (2 minutes)

### 2.1 Prepare Terraform Variables
```bash
cd lightsail

# Copy template
cp terraform.tfvars.example terraform.tfvars

# Edit with your values
vim terraform.tfvars  # or nano, code, etc.
```

### 2.2 Set Required Values in `terraform.tfvars`

```hcl
# AWS Region
aws_region = "us-east-1"

# Lightsail (cheapest option)
lightsail_bundle_id = "small_2_0"  # 1GB RAM, 1 CPU, 40GB SSD

# RDS Database
db_instance_class = "db.t3.micro"  # ~$16/month (cheapest safe option)
db_password = "MyStrongPassword123!"  # Min 8 chars, uppercase, lowercase, number, symbol

# GitHub Repository
app_github_repo = "https://github.com/YOUR_ORG/plur-rfp-tracker-v2.git"
app_github_branch = "deployment/lightsail"

# Domain (optional)
domain_name = ""  # Leave empty for IP-based access
# OR set to your domain:
# domain_name = "rfp-tracker.example.com"

# Enable HTTPS
enable_https = true  # Will auto-configure Let's Encrypt
```

### 2.3 Initialize & Validate
```bash
# Initialize Terraform
terraform init

# Validate configuration
terraform validate
# Expected: Success! The configuration is valid.

# Plan deployment
terraform plan -out=tfplan

# Expected: ~15 resources to be created
```

---

## Phase 3: Deploy Infrastructure (6 minutes)

### 3.1 Apply Terraform
```bash
# Apply the plan
terraform apply tfplan

# Watch the output...
# This will take ~5-6 minutes total
```

**What happens:**
1. ✓ Lightsail instance created (2 min)
2. ✓ Static IP assigned
3. ✓ RDS PostgreSQL created (3-4 min) ⏳ **Main wait here**
4. ✓ S3 bucket created
5. ✓ Firewall rules configured
6. ✓ IAM roles created

### 3.2 Get Deployment Info
```bash
# Show outputs
terraform output

# Get application URL
terraform output application_url

# Get SSH command
terraform output ssh_command
```

---

## Phase 4: Verify Deployment (1 minute)

### 4.1 Check Application Status
```bash
# Get the IP address
IP=$(terraform output -raw lightsail_public_ip)

# SSH into instance
ssh ec2-user@$IP

# Inside instance:
# Check Docker containers
docker ps

# Check application logs
docker-compose logs -f

# Test health endpoint
curl http://localhost:8081/api/health

# Exit
exit
```

### 4.2 Access Application
```bash
# Get URL
URL=$(terraform output -raw application_url)

# Open in browser
open $URL
# or on Windows:
# start $URL
```

You should see the **Dashboard** with sample data!

---

## Cost Breakdown

| Component | Spec | Cost/Month |
|-----------|------|-----------|
| Lightsail Instance | small_2_0 (1GB RAM, 1CPU, 40GB SSD) | $5 |
| Static IP | 1 Static IP | $2 |
| RDS PostgreSQL | db.t3.micro (1GB RAM, 20GB SSD) | $16 |
| Data Transfer | Estimated 10GB | $1 |
| S3 Storage | ~5GB backup data | $0.12 |
| **Total** | | **~$24/month** |

✅ **Production-ready at ~$24/month!**

---

## Troubleshooting

### Application not responding
```bash
# SSH into instance
ssh ec2-user@$(terraform output -raw lightsail_public_ip)

# Check containers
docker-compose ps

# View logs
docker-compose logs app

# Restart if needed
docker-compose restart
```

### RDS connection failed
```bash
# Check RDS status
aws rds describe-db-instances \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --query 'DBInstances[0].DBInstanceStatus'

# Expected: "available"
```

### HTTPS not working
```bash
# Check certificate
certbot certificates

# Renew certificate
certbot renew --force-renewal

# Check Nginx
nginx -t
systemctl status nginx
```

### Terraform state locked
```bash
# Force unlock (use LOCK_ID from error)
terraform force-unlock <LOCK_ID>
```

---

## Backup & Recovery

### Automated Backups
- **RDS**: Daily snapshots (30-day retention)
- **Application**: Daily backups to S3 (via cron job at 2 AM)

### Manual Backup
```bash
# SSH into instance
ssh ec2-user@$(terraform output -raw lightsail_public_ip)

# Run backup script
/usr/local/bin/backup-rfp-tracker.sh
```

### Restore from Backup
```bash
# Get backup from S3
aws s3 cp s3://$(terraform output -raw s3_backup_bucket)/backups/rfp_db_BACKUP_NAME.sql.gz .

# Decompress
gunzip rfp_db_BACKUP_NAME.sql.gz

# Restore to RDS
PGPASSWORD="$(terraform output -raw rds_password | sed 's/"/\\"/g')" \
psql -h $(terraform output -raw rds_address) \
     -U rfpAdmin \
     -d rfptracker \
     < rfp_db_BACKUP_NAME.sql
```

---

## Scaling Up

### Upgrade Lightsail Instance
```bash
# Change in terraform.tfvars
lightsail_bundle_id = "medium_2_0"  # 2GB RAM, 2 CPUs, 60GB SSD (~$10/month)

# Apply
terraform apply
```

### Upgrade RDS Database
```bash
# Change in terraform.tfvars
db_instance_class = "db.t3.small"  # 2GB RAM, better performance (~$30/month)

# Apply
terraform apply
```

---

## Account Transfer (One-Time Setup)

### Export from Account A
```bash
# 1. Create RDS snapshot
aws rds create-db-snapshot \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --db-snapshot-identifier plur-rfp-tracker-backup-$(date +%Y%m%d)

# 2. Share snapshot with Account B (in AWS Console)
# Go to RDS → Snapshots → Select snapshot → "Share Snapshot"
# Enter Account B ID

# 3. Copy S3 bucket contents (or create new bucket in Account B)
aws s3 sync \
  s3://$(terraform output -raw s3_backup_bucket) \
  s3://ACCOUNT_B_BUCKET_NAME --region us-east-1
```

### Import in Account B
```bash
# 1. In Account B AWS Console:
# RDS → Snapshots → "Copy Snapshot"
# Select snapshot, name it plur-rfp-tracker-restored

# 2. Run Terraform in Account B
cd lightsail
terraform init  # New backend in Account B
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with Account B settings
terraform apply

# 3. Database will be recreated from snapshot
# All data preserved!
```

---

## Monitoring

### CloudWatch Logs
```bash
# View Lightsail logs
aws logs tail /aws/lightsail/$(terraform output -raw lightsail_instance_id) --follow

# View application logs (SSH into instance)
docker-compose logs -f
```

### Basic Health Check
```bash
# Check application is running
curl $(terraform output -raw application_url)/api/health

# Expected response:
# {"status": "healthy", ...}
```

---

## Production Checklist

- [x] Lightsail instance deployed
- [x] RDS PostgreSQL running
- [x] Static IP assigned
- [x] HTTPS configured (Let's Encrypt)
- [x] Automated backups enabled
- [x] Firewall rules configured
- [x] Application running
- [x] Health checks passing
- [x] S3 bucket for backups
- [x] Transferable to another account

---

## Cleanup (Stop Paying)

If you want to destroy everything:

```bash
# Warning: This deletes everything!
terraform destroy

# You'll be prompted to confirm - type 'yes'
```

All data backed up to S3 first!

---

## Quick Reference

| Task | Command |
|------|---------|
| Deploy | `cd lightsail && terraform apply` |
| Show outputs | `terraform output` |
| Get URL | `terraform output application_url` |
| SSH into instance | `ssh ec2-user@$(terraform output -raw lightsail_public_ip)` |
| View logs | `docker-compose logs -f` (after SSH) |
| Backup now | `/usr/local/bin/backup-rfp-tracker.sh` (on instance) |
| Destroy | `terraform destroy` |

---

**That's it! You're live in 10 minutes.** 🚀

Next: Setup domain name (optional) or share the IP address.
