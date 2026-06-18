# Account Transfer Guide

**Transfer your entire Lightsail deployment to a different AWS account in ~15 minutes.**

---

## Overview

Since everything is managed by Terraform and stored in RDS + S3, transferring to a new account is simple:

1. **Export RDS snapshot** (5 min)
2. **Copy S3 backups** (5 min)
3. **Deploy in new account** (5 min)

**Result**: Identical production setup in the new account with all data preserved.

---

## Prerequisites (Account B)

Before starting, in the new AWS account:

1. Create IAM user with deployment permissions
2. Generate access key
3. Run `aws configure` with new credentials
4. Create Terraform backend bucket in new account (same as Phase 1)

---

## Step 1: Export from Account A (5 minutes)

### 1.1 Create RDS Snapshot

```bash
# In Account A terminal
SNAPSHOT_NAME="plur-rfp-tracker-$(date +%Y%m%d-%H%M%S)"

aws rds create-db-snapshot \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --db-snapshot-identifier $SNAPSHOT_NAME \
  --region us-east-1

# Wait for snapshot to complete (3-5 min)
aws rds describe-db-snapshots \
  --db-snapshot-identifier $SNAPSHOT_NAME \
  --query 'DBSnapshots[0].Status' \
  --region us-east-1

# Expected: "available"
```

### 1.2 Get S3 Bucket Name

```bash
# In Account A terminal
S3_BUCKET=$(terraform -chdir=lightsail output -raw s3_backup_bucket)
echo "S3 Bucket: $S3_BUCKET"
```

---

## Step 2: Transfer RDS Snapshot to Account B (5 minutes)

### 2.1 Share Snapshot (via AWS Console)

**In Account A AWS Console:**
1. Go to **RDS** → **Snapshots** → **DB Snapshots**
2. Select the snapshot you just created
3. Click **Actions** → **Share Snapshots**
4. Enter **Account B ID** (get from Account B `aws sts get-caller-identity`)
5. Click **Share**

**In Account B AWS Console:**
1. Go to **RDS** → **Snapshots** → **Shared snapshots**
2. Select the shared snapshot
3. Click **Actions** → **Copy Snapshot**
4. Name it: `plur-rfp-tracker-imported`
5. Click **Copy Snapshot**
6. Wait for copy to complete (2-3 min)

---

## Step 3: Copy S3 Backups to Account B (5 minutes)

### 3.1 Option A: Direct Copy (if both accounts accessible)

```bash
# In Account A terminal
SOURCE_BUCKET=$(terraform -chdir=lightsail output -raw s3_backup_bucket)

# Create target bucket in Account B (or use existing)
TARGET_BUCKET="plur-rfp-tracker-backup-$(aws sts get-caller-identity --query Account --output text)"

# Switch to Account B credentials
# export AWS_ACCESS_KEY_ID=... (Account B)
# export AWS_SECRET_ACCESS_KEY=... (Account B)
# export AWS_DEFAULT_REGION=us-east-1

# Copy all backups
aws s3 sync \
  s3://$SOURCE_BUCKET/backups/ \
  s3://$TARGET_BUCKET/backups/ \
  --region us-east-1

echo "✓ Backups copied to Account B"
```

### 3.2 Option B: Export via Local Storage (if cross-account not allowed)

```bash
# Account A: Download backups
aws s3 sync \
  s3://$SOURCE_BUCKET/backups/ \
  ./backups-export/ \
  --region us-east-1

# Move data to Account B environment
# (USB drive, file share, etc.)

# Account B: Upload backups
aws s3 sync \
  ./backups-export/ \
  s3://$TARGET_BUCKET/backups/ \
  --region us-east-1
```

---

## Step 4: Deploy in Account B (5 minutes)

### 4.1 Configure Terraform for Account B

```bash
# Switch to Account B AWS credentials
export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key)
export AWS_DEFAULT_REGION=us-east-1

# Verify you're in Account B
aws sts get-caller-identity

# Navigate to lightsail directory
cd lightsail

# Create new terraform.tfvars for Account B
cp terraform.tfvars.example terraform.tfvars

# Edit with Account B settings:
# - New S3 bucket name
# - Same configuration (instance size, RDS class, etc.)
# - New Terraform backend bucket (created in prerequisites)
```

### 4.2 Initialize & Deploy

```bash
# Initialize Terraform (uses Account B backend)
terraform init

# Plan deployment
terraform plan -out=tfplan

# Apply
terraform apply tfplan

# Wait ~6 minutes for deployment to complete
```

### 4.3 Restore Database from Snapshot

```bash
# After Terraform completes, manually restore RDS from snapshot
# (Terraform will create a new RDS, we need to restore from backup)

# 1. Delete the new RDS instance created by Terraform
aws rds delete-db-instance \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --skip-final-snapshot \
  --region us-east-1

# 2. Restore from imported snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --db-snapshot-identifier plur-rfp-tracker-imported \
  --region us-east-1

# 3. Wait for restore to complete (5 min)
aws rds describe-db-instances \
  --db-instance-identifier plur-rfp-tracker-postgres \
  --query 'DBInstances[0].DBInstanceStatus' \
  --region us-east-1

# Expected: "available"
```

---

## Step 5: Verify Deployment in Account B (2 minutes)

### 5.1 Get Access Information

```bash
# Get application URL
terraform output application_url

# Get SSH command
terraform output ssh_command

# Get RDS endpoint
terraform output rds_address
```

### 5.2 Test Application

```bash
# SSH into instance
ssh ec2-user@$(terraform output -raw lightsail_public_ip)

# Check containers
docker ps

# Test health endpoint
curl http://localhost:8081/api/health

# Expected: {"status": "healthy"}

# View application logs
docker-compose logs app | tail -20
```

### 5.3 Test Database

```bash
# From your local machine or within instance
PSQL_PASSWORD="$(terraform output -raw rds_password | sed 's/"/\\"/g')" \
psql -h $(terraform output -raw rds_address) \
     -U rfpAdmin \
     -d rfptracker \
     -c "SELECT COUNT(*) FROM notices;"

# Should return some data if migration was successful
```

---

## Verification Checklist

- [ ] RDS snapshot created in Account A
- [ ] Snapshot shared with Account B
- [ ] Snapshot copied to Account B
- [ ] S3 backups copied to Account B
- [ ] Terraform deployed in Account B
- [ ] RDS restored from snapshot
- [ ] Application running
- [ ] Health check passing
- [ ] Database has data
- [ ] HTTPS working (if domain configured)

---

## Rollback (if needed)

If something goes wrong during transfer:

```bash
# Account B: Destroy everything
terraform destroy

# Account A: Original stays intact!
```

---

## Common Issues

### Snapshot takes too long
- RDS snapshots can take 5-15 minutes depending on data size
- Monitor in AWS Console: **RDS** → **Snapshots**

### S3 copy fails due to permissions
- Ensure cross-account S3 bucket policy is correct
- Or use "export local → upload" method instead

### Database restore fails
- Verify Terraform-created RDS is deleted first
- Check snapshot is in "available" state
- Verify RDS security groups allow connection from Lightsail

### Application can't connect to RDS
- Verify security group allows Lightsail → RDS
- Check RDS address matches terraform output
- Check database password is correct

---

## Cleanup Account A (Optional)

Once you've verified everything works in Account B, you can clean up Account A:

```bash
# In Account A
cd lightsail

# Destroy all resources
terraform destroy

# Remove S3 backend bucket
aws s3 rb s3://plur-rfp-tracker-lightsail-state --force
```

---

## Time Estimate

| Step | Time |
|------|------|
| Create RDS snapshot | 3-5 min |
| Copy S3 backups | 2-3 min |
| Deploy in Account B | 5-6 min |
| Verify | 2-3 min |
| **Total** | **~15-20 min** |

---

## Support

**If transfer fails:**
1. Check Terraform outputs match your setup
2. Verify RDS snapshot is "available"
3. Check security groups allow Lightsail ↔ RDS
4. Review logs: `docker-compose logs app`

---

**Transfer complete!** 🎉

Your production setup is now running in Account B with all data preserved.

---

## Once-Time Setup in New Account

After successful transfer, make these one-time improvements in Account B:

1. **Update Terraform backend bucket** (already in .tfvars)
2. **Configure SNS for alerts** (optional)
3. **Setup Route 53 for custom domain** (optional)
4. **Enable MFA on IAM user** (security)
5. **Archive Account A snapshots** (optional cleanup)

---

**Questions?** Check LIGHTSAIL_DEPLOY.md for more info.
