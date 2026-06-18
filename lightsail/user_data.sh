#!/bin/bash
set -e

# Logging
exec > >(tee /var/log/user_data.log)
exec 2>&1

echo "=== Starting PLUR RFP Tracker deployment on Lightsail ==="
echo "Timestamp: $(date)"
echo "User: $(whoami)"

# Update system
echo "Updating system packages..."
yum update -y
yum install -y \
    docker \
    git \
    curl \
    wget \
    python3-pip \
    certbot \
    python3-certbot-dns-route53 \
    postgresql \
    htop

# Start Docker
echo "Starting Docker..."
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# Install Docker Compose
echo "Installing Docker Compose..."
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create app directory
echo "Setting up application directory..."
mkdir -p /app/{data,logs,backups,config}
cd /app

# Clone repository
echo "Cloning repository..."
if [ ! -d "plur-rfp-tracker-v2" ]; then
    git clone --depth 1 --branch ${app_github_branch} ${app_github_repo} plur-rfp-tracker-v2
else
    cd plur-rfp-tracker-v2
    git fetch --all
    git checkout ${app_github_branch}
    git pull origin ${app_github_branch}
    cd ..
fi

cd plur-rfp-tracker-v2

# Create .env file with database configuration
echo "Creating environment file..."
cat > .env << 'ENVEOF'
# Database Configuration
DATABASE_URL=postgresql://${rds_username}:${rds_password}@${rds_endpoint}:5432/${app_name}

# Application Configuration
APP_PORT=${app_port}
ENVIRONMENT=production
DEBUG=false

# AWS S3 Configuration
AWS_S3_BUCKET=${s3_bucket}
AWS_REGION=us-east-1

# Optional: HubSpot Integration
# HUBSPOT_API_KEY=
# HUBSPOT_OBJECT_TYPE_ID=

# Optional: SAM.gov Integration
# SAM_GOV_API_KEY=

# Optional: Slack Notifications
# RFP_SLACK_WEBHOOK_URL=

# Optional: Email Digest
# RFP_SMTP_HOST=
# RFP_SMTP_PORT=587
# RFP_SMTP_USER=
# RFP_SMTP_PASSWORD=
# RFP_DIGEST_RECIPIENTS=
ENVEOF

# Start application with Docker Compose
echo "Starting application..."
docker-compose -f docker-compose.yml up -d

# Wait for app to be ready
echo "Waiting for application to be ready..."
sleep 10

# Check health
if curl -f http://localhost:${app_port}/api/health > /dev/null 2>&1; then
    echo "✓ Application is healthy"
else
    echo "⚠ Application health check failed, but continuing..."
    docker-compose logs | tail -20
fi

# Setup Nginx reverse proxy
echo "Setting up Nginx reverse proxy..."
amazon-linux-extras install -y nginx1

cat > /etc/nginx/conf.d/app.conf << 'NGINXEOF'
upstream app {
    server localhost:${app_port};
    keepalive 64;
}

server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 50M;
    proxy_read_timeout 300s;

    location / {
        proxy_pass http://app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    location /api/health {
        access_log off;
        proxy_pass http://app;
    }
}
NGINXEOF

# Remove default config
rm -f /etc/nginx/conf.d/default.conf

# Test and start Nginx
nginx -t
systemctl start nginx
systemctl enable nginx

echo "✓ Nginx configured and started"

# Setup Let's Encrypt HTTPS (if enabled and domain provided)
if [ "${enable_https}" == "true" ] && [ -n "${domain_name}" ]; then
    echo "Setting up HTTPS with Let's Encrypt..."

    # Stop Nginx temporarily
    systemctl stop nginx

    # Request certificate
    certbot certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --email admin@${domain_name} \
        -d ${domain_name}

    # Update Nginx config for HTTPS
    cat > /etc/nginx/conf.d/app.conf << 'NGINXHTTPSEOF'
upstream app {
    server localhost:${app_port};
    keepalive 64;
}

server {
    listen 80 default_server;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2 default_server;
    server_name ${domain_name};

    ssl_certificate /etc/letsencrypt/live/${domain_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain_name}/privatekey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    client_max_body_size 50M;
    proxy_read_timeout 300s;

    location / {
        proxy_pass http://app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    location /api/health {
        access_log off;
        proxy_pass http://app;
    }
}
NGINXHTTPSEOF

    # Setup auto-renewal cron job
    cat > /etc/cron.d/certbot-renewal << 'CRONEOF'
0 3 * * * root certbot renew --quiet && systemctl reload nginx
CRONEOF

    # Restart Nginx
    nginx -t
    systemctl start nginx

    echo "✓ HTTPS configured with Let's Encrypt"
else
    echo "✓ Running in HTTP mode (HTTPS can be added later)"
fi

# Setup systemd service for Docker Compose auto-restart
echo "Setting up systemd service..."
cat > /etc/systemd/system/plur-rfp-tracker.service << 'SERVICEEOF'
[Unit]
Description=PLUR RFP Tracker Docker Compose Service
After=docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=/app/plur-rfp-tracker-v2
ExecStart=/usr/local/bin/docker-compose up
ExecStop=/usr/local/bin/docker-compose down
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable plur-rfp-tracker

echo "✓ Systemd service configured"

# Setup log rotation
echo "Setting up log rotation..."
cat > /etc/logrotate.d/plur-rfp-tracker << 'LOGROTATEEOF'
/app/plur-rfp-tracker-v2/logs/*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
LOGROTATEEOF

# Setup backup script
echo "Setting up backup script..."
cat > /usr/local/bin/backup-rfp-tracker.sh << 'BACKUPEOF'
#!/bin/bash
BACKUP_DIR="/app/backups"
S3_BUCKET="${s3_bucket}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
echo "Backing up database..."
PGPASSWORD="${rds_password}" pg_dump -h ${rds_endpoint} -U ${rds_username} -d rfptracker | gzip > $BACKUP_DIR/rfp_db_$TIMESTAMP.sql.gz

# Upload to S3
aws s3 cp $BACKUP_DIR/rfp_db_$TIMESTAMP.sql.gz s3://$S3_BUCKET/backups/

echo "Backup complete: rfp_db_$TIMESTAMP.sql.gz"
BACKUPEOF

chmod +x /usr/local/bin/backup-rfp-tracker.sh

# Add daily backup cron job
cat > /etc/cron.d/rfp-tracker-backup << 'CRONEOF'
0 2 * * * root /usr/local/bin/backup-rfp-tracker.sh >> /var/log/rfp-tracker-backup.log 2>&1
CRONEOF

echo "✓ Backup script and cron job configured"

# Final checks
echo ""
echo "=== Deployment Complete ==="
echo "Application started at: $(date)"
echo ""
echo "Access your application at:"
if [ -n "${domain_name}" ]; then
    echo "  → https://${domain_name}"
else
    echo "  → http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):${app_port}"
fi
echo ""
echo "Database endpoint: ${rds_endpoint}"
echo "S3 Backup bucket: ${s3_bucket}"
echo ""
echo "View logs:"
echo "  → docker-compose logs -f"
echo "  → tail -f /var/log/user_data.log"
echo ""

echo "=== Setup Complete ==="
