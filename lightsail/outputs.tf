output "lightsail_instance_id" {
  description = "Lightsail instance ID"
  value       = aws_lightsail_instance.app.id
}

output "lightsail_instance_name" {
  description = "Lightsail instance name"
  value       = aws_lightsail_instance.app.name
}

output "lightsail_public_ip" {
  description = "Lightsail instance public IP"
  value       = aws_lightsail_static_ip.app.ip_address
}

output "lightsail_private_ip" {
  description = "Lightsail instance private IP"
  value       = aws_lightsail_instance.app.private_ip_address
}

output "rds_endpoint" {
  description = "RDS database endpoint"
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}

output "rds_address" {
  description = "RDS database address (hostname only)"
  value       = aws_db_instance.main.address
  sensitive   = true
}

output "rds_port" {
  description = "RDS database port"
  value       = aws_db_instance.main.port
}

output "rds_database_name" {
  description = "RDS database name"
  value       = aws_db_instance.main.db_name
}

output "s3_backup_bucket" {
  description = "S3 backup bucket name"
  value       = aws_s3_bucket.backup.id
}

output "application_url" {
  description = "Application URL"
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "http://${aws_lightsail_static_ip.app.ip_address}"
}

output "ssh_command" {
  description = "SSH command to connect to instance"
  value       = "ssh ec2-user@${aws_lightsail_static_ip.app.ip_address}"
}

output "deployment_info" {
  description = "Quick deployment reference"
  value = {
    instance_ip  = aws_lightsail_static_ip.app.ip_address
    rds_host     = aws_db_instance.main.address
    s3_bucket    = aws_s3_bucket.backup.id
    app_url      = var.domain_name != "" ? "https://${var.domain_name}" : "http://${aws_lightsail_static_ip.app.ip_address}"
  }
}
