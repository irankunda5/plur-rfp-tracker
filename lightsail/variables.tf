variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "plur-rfp-tracker"
}

variable "lightsail_instance_name" {
  description = "Lightsail instance name"
  type        = string
  default     = "plur-rfp-tracker-app"
}

variable "lightsail_availability_zone" {
  description = "Lightsail availability zone (e.g., us-east-1a)"
  type        = string
  default     = "us-east-1a"
}

variable "lightsail_blueprint_id" {
  description = "Lightsail blueprint (amazon_linux_2)"
  type        = string
  default     = "amazon_linux_2"
}

variable "lightsail_bundle_id" {
  description = "Lightsail bundle (small = 1GB RAM, 1 CPU, 40GB SSD)"
  type        = string
  default     = "small_2_0"
}

variable "db_instance_class" {
  description = "RDS instance class (db.t3.micro for cheap, db.t3.small for better)"
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 20
}

variable "db_backup_retention_days" {
  description = "RDS backup retention period in days"
  type        = number
  default     = 30
}

variable "db_username" {
  description = "RDS master username"
  type        = string
  default     = "rfpAdmin"
  sensitive   = true
}

variable "db_password" {
  description = "RDS master password (min 8 chars, uppercase, lowercase, number, symbol)"
  type        = string
  sensitive   = true
}

variable "app_port" {
  description = "Application port"
  type        = number
  default     = 8081
}

variable "domain_name" {
  description = "Domain name for the application (optional)"
  type        = string
  default     = ""
}

variable "enable_https" {
  description = "Enable HTTPS with Let's Encrypt (true) or HTTP only (false)"
  type        = bool
  default     = true
}

variable "app_github_repo" {
  description = "GitHub repository URL for application code"
  type        = string
  default     = "https://github.com/YOUR_ORG/plur-rfp-tracker-v2.git"
}

variable "app_github_branch" {
  description = "GitHub branch to deploy"
  type        = string
  default     = "deployment/lightsail"
}

variable "backup_s3_bucket_name" {
  description = "S3 bucket name for backups (must be globally unique)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}
