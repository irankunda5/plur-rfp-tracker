resource "aws_iam_role" "lightsail_role" {
  name               = "${var.app_name}-lightsail-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.app_name}-lightsail-role"
  }
}

resource "aws_iam_role_policy" "s3_backup" {
  name   = "${var.app_name}-s3-backup-policy"
  role   = aws_iam_role.lightsail_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.backup.arn,
          "${aws_s3_bucket.backup.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "cloudwatch" {
  name   = "${var.app_name}-cloudwatch-policy"
  role   = aws_iam_role.lightsail_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "lightsail_profile" {
  name = "${var.app_name}-lightsail-profile"
  role = aws_iam_role.lightsail_role.name
}
