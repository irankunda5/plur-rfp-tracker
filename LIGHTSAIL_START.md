# 🚀 Lightsail - Quick Start (10 minutes to production)

## One-Line Summary
Production-grade Lightsail deployment with PostgreSQL, HTTPS, backups, and account transferability - **all in 10 minutes**.

---

## 📊 Quick Stats

| Metric | Value |
|--------|-------|
| **Deploy Time** | ~10 minutes |
| **Monthly Cost** | $24-45 |
| **HTTPS** | ✅ Let's Encrypt (free, auto-renewing) |
| **Database** | ✅ RDS PostgreSQL (managed, automated backups) |
| **Backups** | ✅ Automated daily to S3 |
| **Account Transfer** | ✅ ~15 minutes |
| **Production Ready** | ✅ Yes |

---

## 🏗️ Architecture

```
Lightsail (Amazon Linux 2)
├─ Docker Container (FastAPI app)
├─ Nginx Reverse Proxy
└─ Let's Encrypt HTTPS

↓ (private network)

RDS PostgreSQL
├─ Automated snapshots (30-day retention)
└─ Encrypted storage

↓ (async backups)

S3 Backup Bucket
├─ Daily app data backups
└─ Cross-account transferable
```

---

## 🎯 Deploy in 3 Steps

### Step 1: Setup (2 min)
```bash
cd lightsail

# Copy template
cp terraform.tfvars.example terraform.tfvars

# Edit with your values
vim terraform.tfvars

# Key settings:
# - db_password: Strong password (min 8 chars, mixed case + number + symbol)
# - domain_name: Leave empty for IP-based access
# - app_github_repo: Your repo URL
# - app_github_branch: deployment/lightsail
```

### Step 2: Deploy (6 min)
```bash
# Initialize Terraform backend (one-time)
terraform init

# Plan
terraform plan -out=tfplan

# Deploy
terraform apply tfplan

# Wait ~6 minutes...
```

### Step 3: Verify (2 min)
```bash
# Get application URL
terraform output application_url

# Get SSH command
terraform output ssh_command

# Test health check
curl $(terraform output application_url)/api/health
```

---

## 📋 What Gets Created

✅ **Lightsail Instance** (small_2_0: $5/month)
- 1GB RAM
- 1 CPU
- 40GB SSD storage
- Static IP included
- Auto-restart on crash

✅ **RDS PostgreSQL** (db.t3.micro: $16/month)
- Fully managed database
- Automated daily backups (30-day retention)
- Encrypted storage
- Multi-AZ capable (upgrade anytime)

✅ **S3 Backup Bucket**
- Daily backups from Lightsail
- Versioning enabled
- Auto-archival after 30 days
- Lifecycle policies for cost optimization

✅ **HTTPS** (Let's Encrypt - free!)
- Auto-configured if domain provided
- Auto-renews before expiry
- HTTP → HTTPS redirect

✅ **Security**
- Firewall rules (HTTP, HTTPS, SSH)
- Security groups (database isolation)
- IAM roles (least-privilege)
- Encrypted volumes

---

## 💾 Cost Analysis

**Absolute Minimum:**
```
Lightsail: $5/month
RDS t3.micro: $16/month
S3: $0.50/month
Total: $21.50/month ✨
```

**Recommended (better performance):**
```
Lightsail small_2_0: $5/month
RDS t3.micro: $16/month
S3: $1/month
Backups: $2/month
Total: $24/month 💰
```

**If you scale later:**
```
Lightsail medium: $10/month
RDS t3.small: $30/month
Total: $40/month
```

---

## 🔒 Production Features

✅ **Automated Backups**
- RDS snapshots every 24 hours (30-day retention)
- S3 backups daily via cron job
- Manual backup script available

✅ **Health Monitoring**
- Application health endpoint
- HTTP status checks via ALB (if scaling)
- CloudWatch logs

✅ **High Availability**
- Automated restart on crash (systemd)
- Static IP (no DNS headaches)
- Multi-AZ capable (one command upgrade)

✅ **HTTPS/Security**
- Free Let's Encrypt certificates
- Auto-renewal (30 days before expiry)
- A+ SSL rating
- Nginx reverse proxy

---

## 🔄 Account Transfer

Transfer your entire setup to a different AWS account in ~15 minutes:

```bash
# In Account A:
# 1. Create RDS snapshot
aws rds create-db-snapshot \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --db-snapshot-identifier backup-$(date +%Y%m%d)

# In Account B:
# 2. Copy snapshot (via AWS Console)
# 3. Deploy Terraform
cd lightsail && terraform apply
# 4. Restore database from snapshot
```

**See ACCOUNT_TRANSFER.md for full step-by-step guide.**

---

## 📁 Key Files

**Deployment:**
- `lightsail/main.tf` - Terraform provider & backend
- `lightsail/lightsail.tf` - Lightsail instance configuration
- `lightsail/rds.tf` - PostgreSQL database
- `lightsail/s3.tf` - Backup bucket
- `lightsail/user_data.sh` - Instance initialization script
- `lightsail/terraform.tfvars.example` - Configuration template

**Documentation:**
- `LIGHTSAIL_DEPLOY.md` - Complete deployment guide (10 min)
- `ACCOUNT_TRANSFER.md` - Account migration guide (15 min)

---

## ⚡ Commands Reference

```bash
# Initialize (one-time)
cd lightsail && terraform init

# Deploy
terraform apply

# Show outputs
terraform output

# SSH to instance
ssh ec2-user@$(terraform output -raw lightsail_public_ip)

# View logs (after SSH)
docker-compose logs -f

# Manual backup (on instance)
/usr/local/bin/backup-rfp-tracker.sh

# Destroy (careful!)
terraform destroy
```

---

## 🚀 Next Steps

1. **Read** `LIGHTSAIL_DEPLOY.md` (full 10-minute guide)
2. **Configure** `terraform.tfvars`
3. **Deploy** `terraform apply`
4. **Verify** Health checks passing
5. **Setup domain** (optional, add domain name to tfvars)
6. **Setup monitoring** (optional, CloudWatch alarms)

---

## 🆘 Troubleshooting

**Application not responding:**
```bash
ssh ec2-user@$(terraform output -raw lightsail_public_ip)
docker-compose logs app
```

**RDS won't connect:**
```bash
# Check RDS status
aws rds describe-db-instances \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --query 'DBInstances[0].DBInstanceStatus'
# Should be: "available"
```

**HTTPS not working:**
```bash
certbot certificates  # On instance
systemctl status nginx
```

**See LIGHTSAIL_DEPLOY.md Troubleshooting section for more.**

---

## ✅ Production Checklist

- [ ] Terraform configured with strong DB password
- [ ] Domain name set (or using IP)
- [ ] Terraform deployed successfully
- [ ] Application responding (curl test)
- [ ] Database connected
- [ ] Health checks passing
- [ ] HTTPS working (if domain configured)
- [ ] Backups configured
- [ ] SSH access working
- [ ] Monitoring setup

---

## 🎊 You're Ready!

```bash
cd lightsail
terraform apply
# ~10 minutes later...
# 🎉 Production system running!
```

**That's it!** Questions? See `LIGHTSAIL_DEPLOY.md`.

---

**Cost:** ~$24/month  
**Deploy Time:** ~10 min  
**Production Ready:** ✅ Yes  
**Account Transferable:** ✅ Yes

Now go build something great! 🚀
