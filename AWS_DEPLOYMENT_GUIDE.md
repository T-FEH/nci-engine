# Complete AWS EC2 Deployment Guide - No-Code Intelligence Engine

**Duration:** ~2-3 hours for complete setup  
**Difficulty:** Beginner-friendly with step-by-step instructions  
**Cost:** ~$20-50/month (using t3.medium + RDS)

---

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [AWS Account Setup](#aws-account-setup)
3. [Database Setup (RDS PostgreSQL)](#database-setup)
4. [EC2 Instance Setup](#ec2-instance-setup)
5. [Domain & SSL Configuration](#domain-ssl)
6. [Backend Deployment](#backend-deployment)
7. [Frontend Deployment](#frontend-deployment)
8. [Nginx Configuration (Single URL)](#nginx-configuration)
9. [Environment Variables](#environment-variables)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before starting, ensure you have:
- [ ] AWS Account (with credit card for verification)
- [ ] Domain name (optional but recommended - can use Namecheap, GoDaddy, etc.)
- [ ] Your project code on GitHub (or ready to upload)
- [ ] SSH client (Terminal on Mac/Linux, PuTTY on Windows)

---

## 1. AWS Account Setup

### Step 1.1: Create AWS Account
1. Go to https://aws.amazon.com/
2. Click "Create an AWS Account"
3. Follow the registration process
4. **Important:** Set up MFA (Multi-Factor Authentication) for security

### Step 1.2: Create IAM User (Security Best Practice)
1. Login to AWS Console → Search "IAM"
2. Click "Users" → "Add user"
3. Username: `nci-deployer`
4. Enable "Provide user access to AWS Management Console"
5. Attach policies:
   - `AmazonEC2FullAccess`
   - `AmazonRDSFullAccess`
   - `AmazonVPCFullAccess`
6. Download credentials (keep safe!)

### Step 1.3: Set Up Billing Alerts
1. AWS Console → "Billing Dashboard"
2. Click "Budgets" → "Create budget"
3. Set alert for $50/month (adjust as needed)

---

## 2. Database Setup (RDS PostgreSQL)

### Step 2.1: Create RDS PostgreSQL Instance

1. **Navigate to RDS:**
   - AWS Console → Search "RDS" → Click "Databases" → "Create database"

2. **Choose Database Creation Method:**
   - Select: **Standard create**

3. **Engine Options:**
   - Engine type: **PostgreSQL**
   - Version: **PostgreSQL 15.x** (latest stable)

4. **Templates:**
   - Select: **Free tier** (or Dev/Test for better performance)

5. **Settings:**
   ```
   DB instance identifier: nci-engine-db
   Master username: nci_admin
   Master password: [Create strong password - SAVE THIS!]
   Confirm password: [Same password]
   ```

6. **Instance Configuration:**
   - DB instance class: **db.t3.micro** (Free tier) or **db.t3.small** (better performance)

7. **Storage:**
   - Storage type: General Purpose SSD (gp2)
   - Allocated storage: 20 GB
   - ✅ Enable storage autoscaling (max: 100 GB)

8. **Connectivity:**
   - Virtual Private Cloud (VPC): **Default VPC**
   - Public access: **Yes** (we'll secure with security groups)
   - VPC security group: Create new → Name: `nci-db-sg`

9. **Database Authentication:**
   - Select: **Password authentication**

10. **Additional Configuration:**
    - Initial database name: `nci_engine`
    - ✅ Enable automated backups
    - Backup retention: 7 days

11. **Click "Create database"** (takes 5-10 minutes)

### Step 2.2: Configure Security Group for RDS

1. While database is creating, go to **EC2 Console → Security Groups**
2. Find security group: `nci-db-sg`
3. Click "Edit inbound rules" → "Add rule"
4. Configure:
   ```
   Type: PostgreSQL
   Protocol: TCP
   Port: 5432
   Source: Custom → 0.0.0.0/0 (temporary - we'll restrict later)
   Description: Temporary PostgreSQL access
   ```
5. Click "Save rules"

### Step 2.3: Get Database Connection Details

1. Go to RDS → Databases → Click `nci-engine-db`
2. **Copy these values (you'll need them):**
   ```
   Endpoint: nci-engine-db.xxxxx.us-east-1.rds.amazonaws.com
   Port: 5432
   Username: nci_admin
   Password: [your password]
   Database name: nci_engine
   ```

### Step 2.4: Test Database Connection (Optional but Recommended)

From your local machine:
```bash
# Install PostgreSQL client (if not installed)
# Mac: brew install postgresql
# Ubuntu: sudo apt install postgresql-client

# Test connection
psql -h nci-engine-db.xxxxx.us-east-1.rds.amazonaws.com \
     -U nci_admin \
     -d nci_engine

# You should get a psql prompt. Type \q to exit
```

---

## 3. EC2 Instance Setup

### Step 3.1: Launch EC2 Instance

1. **AWS Console → EC2 → Launch Instance**

2. **Name and Tags:**
   ```
   Name: nci-engine-server
   ```

3. **Application and OS Images:**
   - Quick Start: **Ubuntu**
   - Ubuntu Server 22.04 LTS (Free tier eligible)

4. **Instance Type:**
   - **t3.medium** (2 vCPU, 4 GB RAM) - Recommended
   - OR **t2.micro** (Free tier - may be slow for NCI Engine)

5. **Key Pair:**
   - Click "Create new key pair"
   - Key pair name: `nci-engine-key`
   - Key pair type: RSA
   - Private key format: `.pem` (Mac/Linux) or `.ppk` (Windows/PuTTY)
   - **Download and SAVE THIS FILE** - you can't download it again!
   - Move to safe location:
     ```bash
     # Mac/Linux
     mv ~/Downloads/nci-engine-key.pem ~/.ssh/
     chmod 400 ~/.ssh/nci-engine-key.pem
     ```

6. **Network Settings:**
   - VPC: Default VPC
   - Auto-assign public IP: **Enable**
   - Firewall (security groups): Create new
     - Security group name: `nci-engine-sg`
     - Description: NCI Engine web server
     - Inbound rules:
       - ✅ SSH (port 22) from My IP
       - ✅ HTTP (port 80) from Anywhere
       - ✅ HTTPS (port 443) from Anywhere
       - Add custom rule:
         - Type: Custom TCP
         - Port: 8000
         - Source: Anywhere (0.0.0.0/0)
         - Description: FastAPI backend

7. **Configure Storage:**
   - 30 GB gp3 (general purpose SSD)

8. **Advanced Details (optional but recommended):**
   - Monitoring: ✅ Enable detailed monitoring

9. **Click "Launch Instance"**

### Step 3.2: Connect to EC2 Instance

1. **Get Public IP:**
   - EC2 Console → Instances → Click `nci-engine-server`
   - Copy "Public IPv4 address" (e.g., 54.123.45.67)

2. **Connect via SSH:**
   ```bash
   # Mac/Linux
   ssh -i ~/.ssh/nci-engine-key.pem ubuntu@54.123.45.67
   
   # Windows (using PuTTY or Windows Terminal)
   # Use your .ppk file in PuTTY configuration
   ```

3. **If you get a warning about host authenticity, type "yes"**

---

## 4. Server Setup on EC2

### Step 4.1: Update System

```bash
# Update package lists
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y git curl wget vim htop build-essential
```

### Step 4.2: Install Python 3.11

```bash
# Add deadsnakes PPA for latest Python
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# Make Python 3.11 default
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install pip
curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.11

# Verify
python3 --version  # Should show Python 3.11.x
pip3 --version
```

### Step 4.3: Install PostgreSQL Client

```bash
sudo apt install -y postgresql-client
```

### Step 4.4: Install Node.js (for Frontend)

```bash
# Install Node.js 20.x LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verify
node --version  # Should show v20.x.x
npm --version   # Should show 10.x.x
```

### Step 4.5: Install Nginx (Reverse Proxy)

```bash
sudo apt install -y nginx

# Start and enable Nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Check status
sudo systemctl status nginx
```

### Step 4.6: Install Redis (for Caching)

```bash
sudo apt install -y redis-server

# Start and enable Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Test Redis
redis-cli ping  # Should return "PONG"
```

---

## 5. Deploy the Application

### Step 5.1: Clone Your Repository

```bash
# Navigate to home directory
cd ~

# Clone your project (replace with your GitHub URL)
git clone https://github.com/YOUR_USERNAME/nci-engine.git

# Enter project directory
cd nci-engine
```

### Step 5.2: Set Up Backend Environment

```bash
# Create Python virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Install additional production dependencies
pip install gunicorn uvicorn[standard]
```

### Step 5.3: Configure Environment Variables

```bash
# Create .env file
nano .env
```

**Copy and paste this (replace with your actual values):**

```env
# Database Configuration (RDS PostgreSQL)
DATABASE_URL=postgresql://nci_admin:YOUR_PASSWORD@nci-engine-db.xxxxx.us-east-1.rds.amazonaws.com:5432/nci_engine

# API Keys (replace with your actual keys)
OPENAI_API_KEY=sk-your-openai-key-here

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Environment
ENVIRONMENT=production

# CORS Origins (your domain - update after getting domain)
CORS_ORIGINS=["http://YOUR_DOMAIN.com","https://YOUR_DOMAIN.com"]

# Logging
LOG_LEVEL=INFO

# Security
SECRET_KEY=your-secret-key-generate-with-openssl-rand-hex-32
```

**Save and exit (Ctrl+X, then Y, then Enter)**

### Step 5.4: Initialize Database

```bash
# Test database connection
psql $DATABASE_URL -c "SELECT version();"

# Run migrations (if using Alembic)
alembic upgrade head

# Or run your database setup script
python3 -c "from src.database.db_pg import ToolDatabase; db = ToolDatabase(); print('Database initialized')"
```

### Step 5.5: Ingest Tool Data

```bash
# If you have the CSV data file
python3 scripts/fresh_ingest_from_csv.py

# This will:
# - Create tables
# - Load tool data
# - Generate embeddings
# - Store in PostgreSQL
```

---

## 6. Backend Deployment with Systemd

### Step 6.1: Create Systemd Service File

```bash
sudo nano /etc/systemd/system/nci-backend.service
```

**Copy this configuration:**

```ini
[Unit]
Description=NCI Engine Backend API
After=network.target postgresql.service

[Service]
Type=notify
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/nci-engine
Environment="PATH=/home/ubuntu/nci-engine/.venv/bin"
ExecStart=/home/ubuntu/nci-engine/.venv/bin/gunicorn src.api.main:app \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile /home/ubuntu/nci-engine/logs/access.log \
    --error-logfile /home/ubuntu/nci-engine/logs/error.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save and exit**

### Step 6.2: Create Log Directory

```bash
mkdir -p ~/nci-engine/logs
```

### Step 6.3: Start Backend Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable nci-backend

# Start service
sudo systemctl start nci-backend

# Check status
sudo systemctl status nci-backend

# View logs
tail -f ~/nci-engine/logs/error.log
```

### Step 6.4: Test Backend

```bash
# Should return JSON
curl http://localhost:8000/api/v1/health
```

---

## 7. Frontend Deployment

### Step 7.1: Build Frontend

```bash
cd ~/nci-engine/frontend

# Install dependencies
npm install

# Create production .env
nano .env.production
```

**Add this:**

```env
NEXT_PUBLIC_API_URL=http://YOUR_EC2_PUBLIC_IP
```

**Save and exit**

```bash
# Build for production
npm run build

# Test production build locally
npm start &

# Test (from another terminal)
curl http://localhost:3000
```

### Step 7.2: Create Frontend Systemd Service

```bash
sudo nano /etc/systemd/system/nci-frontend.service
```

**Configuration:**

```ini
[Unit]
Description=NCI Engine Frontend
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/nci-engine/frontend
Environment="NODE_ENV=production"
Environment="PORT=3000"
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save and exit**

### Step 7.3: Start Frontend Service

```bash
# Stop test instance first
pkill -f "npm start"

# Start service
sudo systemctl daemon-reload
sudo systemctl enable nci-frontend
sudo systemctl start nci-frontend
sudo systemctl status nci-frontend
```

---

## 8. Nginx Configuration (Single URL)

### Step 8.1: Configure Nginx as Reverse Proxy

```bash
sudo nano /etc/nginx/sites-available/nci-engine
```

**Copy this configuration:**

```nginx
# Redirect HTTP to HTTPS (after SSL setup)
server {
    listen 80;
    server_name YOUR_DOMAIN.com www.YOUR_DOMAIN.com;
    
    # For initial setup, serve directly:
    # Comment out this section after SSL is configured
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # API routes
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

**Save and exit**

### Step 8.2: Enable Site and Restart Nginx

```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/nci-engine /etc/nginx/sites-enabled/

# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx

# Check status
sudo systemctl status nginx
```

---

## 9. Domain Configuration (Optional but Recommended)

### Step 9.1: Point Domain to EC2

1. **Get EC2 Elastic IP (Permanent IP):**
   - EC2 Console → Elastic IPs → "Allocate Elastic IP address"
   - Click "Actions" → "Associate Elastic IP address"
   - Select your instance → Associate

2. **Configure DNS:**
   - Go to your domain registrar (Namecheap, GoDaddy, etc.)
   - Add A record:
     ```
     Type: A
     Host: @ (or www)
     Value: YOUR_ELASTIC_IP
     TTL: 300 (5 minutes)
     ```

3. **Wait for DNS propagation (5-30 minutes)**

### Step 9.2: Set Up SSL with Let's Encrypt (Free HTTPS)

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d YOUR_DOMAIN.com -d www.YOUR_DOMAIN.com

# Follow prompts:
# - Enter email
# - Agree to terms
# - Choose redirect HTTP to HTTPS (option 2)

# Test auto-renewal
sudo certbot renew --dry-run
```

**Certbot will automatically update your Nginx config for HTTPS!**

---

## 10. Final Testing

### Step 10.1: Test All Endpoints

```bash
# Test frontend
curl https://YOUR_DOMAIN.com

# Test backend health
curl https://YOUR_DOMAIN.com/api/v1/health

# Test a query (from local browser)
# Go to: https://YOUR_DOMAIN.com
```

### Step 10.2: Monitor Logs

```bash
# Backend logs
tail -f ~/nci-engine/logs/error.log

# Frontend logs
sudo journalctl -u nci-frontend -f

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## 11. Post-Deployment Tasks

### Step 11.1: Secure RDS Security Group

```bash
# Now that EC2 is running, restrict RDS access to only EC2

# 1. Get EC2 private IP
curl http://169.254.169.254/latest/meta-data/local-ipv4

# 2. AWS Console → EC2 → Security Groups → nci-db-sg
# 3. Edit inbound rules
# 4. Change source from 0.0.0.0/0 to EC2 security group (nci-engine-sg)
```

### Step 11.2: Set Up Monitoring

```bash
# Install CloudWatch agent (optional)
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb
```

### Step 11.3: Automated Backups

```bash
# Create backup script
nano ~/backup.sh
```

**Add:**

```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=~/backups

mkdir -p $BACKUP_DIR

# Backup database
PGPASSWORD=YOUR_PASSWORD pg_dump \
    -h nci-engine-db.xxxxx.us-east-1.rds.amazonaws.com \
    -U nci_admin \
    -d nci_engine \
    -F c \
    -f $BACKUP_DIR/nci_db_$DATE.dump

# Keep only last 7 days
find $BACKUP_DIR -name "*.dump" -mtime +7 -delete

echo "Backup completed: $DATE"
```

**Make executable:**

```bash
chmod +x ~/backup.sh

# Add to crontab (daily at 2 AM)
crontab -e

# Add this line:
0 2 * * * /home/ubuntu/backup.sh >> /home/ubuntu/backup.log 2>&1
```

---

## 12. Troubleshooting

### Issue: Backend won't start

```bash
# Check logs
sudo journalctl -u nci-backend -n 50

# Common fixes:
# 1. Check .env file exists
ls -la ~/nci-engine/.env

# 2. Check database connection
psql $DATABASE_URL -c "SELECT 1;"

# 3. Restart service
sudo systemctl restart nci-backend
```

### Issue: Frontend shows "API Error"

```bash
# Check backend is running
curl http://localhost:8000/api/v1/health

# Check Nginx config
sudo nginx -t

# Check frontend .env.production has correct API URL
cat ~/nci-engine/frontend/.env.production
```

### Issue: High Latency

```bash
# Check EC2 CPU/Memory
htop

# Check database connections
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"

# Consider upgrading instance type to t3.large
```

### Issue: SSL Certificate Issues

```bash
# Renew certificate manually
sudo certbot renew

# Check certificate status
sudo certbot certificates
```

---

## 13. Cost Optimization Tips

1. **Use Reserved Instances:** Save 30-50% on EC2 if you commit to 1 year
2. **Stop EC2 when not needed:** Turn off at night if demo-only
3. **Use RDS Free Tier:** db.t3.micro is free for 12 months
4. **Monitor with Billing Alerts:** Set up $50/month alert
5. **Use Elastic IP only when needed:** It's free when attached, $0.005/hour when not

**Estimated Monthly Cost:**
- EC2 t3.medium: $30-40
- RDS db.t3.micro: Free tier (then ~$15)
- Data transfer: ~$5
- **Total: ~$35-60/month**

---

## 14. Quick Commands Reference

```bash
# Restart all services
sudo systemctl restart nci-backend nci-frontend nginx

# View all logs
sudo journalctl -u nci-backend -u nci-frontend -f

# Check service status
sudo systemctl status nci-backend nci-frontend nginx

# Update code from Git
cd ~/nci-engine
git pull
sudo systemctl restart nci-backend nci-frontend

# Monitor resources
htop
df -h  # disk space
free -h  # memory
```

---

## 15. Next Steps After Deployment

✅ **Your app is now live at:** `https://YOUR_DOMAIN.com`

1. Test all features thoroughly
2. Set up Google Analytics (optional)
3. Add error monitoring (Sentry)
4. Create demo data for presentation
5. Share URL with your supervisor!

**Congratulations! 🎉 Your No-Code Intelligence Engine is deployed on AWS!**

---

## Support & Resources

- **AWS Documentation:** https://docs.aws.amazon.com/
- **Nginx Docs:** https://nginx.org/en/docs/
- **Let's Encrypt:** https://letsencrypt.org/docs/
- **Troubleshooting:** Check logs first, then Google error messages

**Need help?** Most errors are in the logs:
- Backend: `~/nci-engine/logs/error.log`
- Frontend: `sudo journalctl -u nci-frontend`
- Nginx: `/var/log/nginx/error.log`
