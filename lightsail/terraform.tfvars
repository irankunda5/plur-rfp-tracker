# AWS Configuration
aws_region = "us-east-1"

# Lightsail Configuration
lightsail_instance_name    = "plur-rfp-tracker-app"
lightsail_availability_zone = "us-east-1a"
lightsail_blueprint_id     = "amazon_linux_2"
lightsail_bundle_id        = "small_2_0"  # 1GB RAM, 1 CPU, 40GB SSD - cheapest option

# RDS Configuration (PostgreSQL)
db_instance_class      = "db.t3.micro"  # Cheapest: ~$16/month. Use db.t3.small (~$30) for better performance
db_allocated_storage   = 20
db_backup_retention_days = 30
db_username            = "rfpAdmin"
db_password            = "Plurilock2026Admin!"  # Min 8 chars, uppercase, lowercase, number, symbol

# Application Configuration
app_port           = 8081
domain_name        = ""  # Leave empty for IP-based access, or set to your domain (e.g., rfp-tracker.example.com)
enable_https       = true
app_github_repo    = "https://github.com/aronhsiao-pl/plur-rfp-tracker-v2"
app_github_branch  = "deployment/lightsail"

# S3 Backup Configuration
backup_s3_bucket_name = ""  # Leave empty to auto-generate bucket name

# Environment
environment = "prod"
