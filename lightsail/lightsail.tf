resource "aws_lightsail_instance" "app" {
  name              = var.lightsail_instance_name
  availability_zone = var.lightsail_availability_zone
  blueprint_id      = var.lightsail_blueprint_id
  bundle_id         = var.lightsail_bundle_id

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    app_name           = var.app_name
    rds_endpoint       = aws_db_instance.main.address
    rds_port           = aws_db_instance.main.port
    rds_username       = var.db_username
    rds_password       = var.db_password
    rds_database       = aws_db_instance.main.db_name
    app_port           = var.app_port
    s3_bucket          = aws_s3_bucket.backup.id
    app_github_repo    = var.app_github_repo
    app_github_branch  = var.app_github_branch
    domain_name        = var.domain_name
    enable_https       = var.enable_https
  }))

  tags = {
    Name = "${var.app_name}-instance"
  }

  depends_on = [aws_db_instance.main]
}

resource "aws_lightsail_static_ip" "app" {
  name       = "${var.app_name}-static-ip"
  depends_on = [aws_lightsail_instance.app]
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name    = aws_lightsail_static_ip.app.name
  instance_name     = aws_lightsail_instance.app.name
  depends_on        = [aws_lightsail_instance.app]
}

resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    from_port = 80
    to_port   = 80
    protocol  = "tcp"
  }

  port_info {
    from_port = 443
    to_port   = 443
    protocol  = "tcp"
  }

  port_info {
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
  }

  depends_on = [aws_lightsail_instance.app]
}
