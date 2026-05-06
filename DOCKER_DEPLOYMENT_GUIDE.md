# Docker Deployment Guide - No-Code Intelligence Engine
## Easier Alternative to Manual EC2 Setup

**Why Docker?**
- ✅ Faster deployment (30 minutes vs 2-3 hours)
- ✅ Consistent environment (works same everywhere)
- ✅ Easier updates (just rebuild container)
- ✅ Better for beginners

**Time to Deploy:** ~30-45 minutes  
**Cost:** Same as manual ($35-60/month)

---

## Option 1: Docker on EC2 (Recommended for Beginners)

### Step 1: Launch EC2 Instance

Follow AWS_DEPLOYMENT_GUIDE.md steps 1-3 to:
1. Create AWS account
2. Launch t3.medium EC2 instance
3. Set up security groups (ports 80, 443, 22)
4. Create RDS PostgreSQL database

### Step 2: Install Docker on EC2

```bash
# SSH into your EC2
ssh -i ~/.ssh/nci-engine-key.pem ubuntu@YOUR_EC2_IP

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add ubuntu user to docker group
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Logout and login again for group changes
exit
ssh -i ~/.ssh/nci-engine-key.pem ubuntu@YOUR_EC2_IP
```

### Step 3: Clone Repository and Configure

```bash
# Clone project
git clone https://github.com/YOUR_USERNAME/nci-engine.git
cd nci-engine

# Create .env file
nano .env.production
```

**Add this (replace with your values):**

```env
# Database (RDS PostgreSQL)
DATABASE_URL=postgresql://nci_admin:YOUR_PASSWORD@nci-engine-db.xxxxx.us-east-1.rds.amazonaws.com:5432/nci_engine

# API Keys
OPENAI_API_KEY=sk-your-key-here

# Environment
ENVIRONMENT=production
NODE_ENV=production

# Backend URL (use your domain or EC2 IP)
NEXT_PUBLIC_API_URL=http://YOUR_EC2_IP

# Redis
REDIS_URL=redis://redis:6379/0
```

**Save and exit (Ctrl+X, Y, Enter)**

### Step 4: Create Docker Configuration Files

**Create `Dockerfile` for backend:**

```bash
nano Dockerfile.backend
```

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn uvicorn[standard]

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run with gunicorn
CMD ["gunicorn", "src.api.main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120"]
```

**Create `Dockerfile` for frontend:**

```bash
nano frontend/Dockerfile
```

```dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build application
RUN npm run build

# Production stage
FROM node:20-alpine

WORKDIR /app

# Copy built application
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3000

CMD ["npm", "start"]
```

**Create `docker-compose.yml`:**

```bash
nano docker-compose.yml
```

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    restart: unless-stopped

  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    env_file:
      - .env.production
    depends_on:
      - redis
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
    ports:
      - "3000:3000"
    env_file:
      - .env.production
    depends_on:
      - backend
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - frontend
      - backend
    restart: unless-stopped

volumes:
  redis-data:
```

**Create Nginx configuration:**

```bash
nano nginx.conf
```

```nginx
events {
    worker_connections 1024;
}

http {
    upstream frontend {
        server frontend:3000;
    }

    upstream backend {
        server backend:8000;
    }

    server {
        listen 80;
        server_name _;

        client_max_body_size 20M;

        # Frontend
        location / {
            proxy_pass http://frontend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_cache_bypass $http_upgrade;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Backend API
        location /api {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;
        }
    }
}
```

### Step 5: Build and Deploy

```bash
# Build all containers (takes 5-10 minutes first time)
docker-compose build

# Start all services
docker-compose up -d

# Check if all services are running
docker-compose ps

# View logs
docker-compose logs -f

# Initialize database (run once)
docker-compose exec backend python -c "from src.database.db_pg import ToolDatabase; db = ToolDatabase()"

# Ingest data (run once)
docker-compose exec backend python scripts/fresh_ingest_from_csv.py
```

### Step 6: Test Deployment

```bash
# Test backend
curl http://YOUR_EC2_IP/api/v1/health

# Test frontend (open in browser)
http://YOUR_EC2_IP
```

### Step 7: Managing the Application

```bash
# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Restart services
docker-compose restart

# Stop all services
docker-compose down

# Update code and redeploy
git pull
docker-compose build
docker-compose up -d

# View resource usage
docker stats
```

---

## Option 2: Deploy to AWS ECS (Advanced)

For automatic scaling and managed containers:

### Prerequisites
- AWS CLI installed
- AWS account with ECS permissions

### Quick Deploy

```bash
# Install ECS CLI
sudo curl -Lo /usr/local/bin/ecs-cli https://amazon-ecs-cli.s3.amazonaws.com/ecs-cli-linux-amd64-latest
sudo chmod +x /usr/local/bin/ecs-cli

# Configure ECS
ecs-cli configure --cluster nci-engine \
                  --region us-east-1 \
                  --default-launch-type FARGATE

# Create cluster
ecs-cli up --cluster-config nci-engine

# Deploy with docker-compose
ecs-cli compose --project-name nci-engine service up
```

---

## Option 3: Railway.app (Easiest - 5 Minutes!)

**For demos and quick deployments:**

1. **Go to:** https://railway.app
2. **Sign up** with GitHub
3. **Click "New Project" → "Deploy from GitHub repo"**
4. **Select** your `nci-engine` repository
5. **Add environment variables** from .env.production
6. **Add PostgreSQL database** (Railway provides free tier)
7. **Click Deploy**

**Railway automatically:**
- ✅ Builds Docker containers
- ✅ Sets up SSL/HTTPS
- ✅ Provides URL (nci-engine.railway.app)
- ✅ Auto-deploys on git push

**Cost:** Free tier: $5/month credit (enough for testing)  
**Downside:** Not as scalable as AWS for production

---

## Troubleshooting Docker

### Container won't start

```bash
# Check logs
docker-compose logs backend

# Common issue: Database connection
docker-compose exec backend psql $DATABASE_URL -c "SELECT 1;"
```

### Out of memory

```bash
# Check memory usage
docker stats

# Solution: Reduce workers in Dockerfile.backend
# Change --workers 2 to --workers 1
```

### Permission errors

```bash
# Fix permissions
sudo chown -R ubuntu:ubuntu ~/nci-engine
```

### Need to reset everything

```bash
# Nuclear option - removes all containers and volumes
docker-compose down -v
docker system prune -a
docker-compose up -d --build
```

---

## Docker vs Manual Deployment

| Feature | Docker | Manual (Systemd) |
|---------|--------|------------------|
| Setup Time | 30 mins | 2-3 hours |
| Difficulty | ⭐⭐ | ⭐⭐⭐⭐ |
| Updates | Easy (rebuild) | Manual |
| Scaling | Easy (docker-compose scale) | Hard |
| Debugging | docker logs | Multiple log files |
| Best For | Quick deploy, demos | Production, fine control |

---

## Production Checklist

Before going live:

- [ ] Set up Elastic IP for EC2
- [ ] Configure domain DNS
- [ ] Add SSL with Let's Encrypt:
  ```bash
  # Install certbot
  sudo apt install certbot
  
  # Get certificate
  sudo certbot certonly --standalone -d yourdomain.com
  
  # Update nginx.conf with SSL paths
  # Restart: docker-compose restart nginx
  ```
- [ ] Set up automated backups
- [ ] Configure CloudWatch monitoring
- [ ] Test with real queries
- [ ] Load test with `ab` or `locust`

---

## Quick Commands Reference

```bash
# Start everything
docker-compose up -d

# Stop everything
docker-compose down

# Rebuild after code changes
docker-compose build backend && docker-compose up -d backend

# View logs (live)
docker-compose logs -f

# Shell into container
docker-compose exec backend bash

# Database backup
docker-compose exec backend pg_dump $DATABASE_URL > backup.sql

# Resource monitoring
docker stats

# Clean up old images
docker system prune -a
```

---

## Cost Estimate (Docker on EC2)

- EC2 t3.medium: $30/month
- RDS db.t3.micro: Free tier (or $15/month)
- Data transfer: ~$5/month
- **Total: ~$35-50/month**

**Cheaper alternatives:**
- Railway.app: $5/month (free tier)
- DigitalOcean App Platform: $12/month
- Render.com: $7/month

---

## Recommended Path for Beginners

1. **For Demo:** Use Railway.app (5 minutes, free)
2. **For Learning:** Docker on EC2 (30 minutes)
3. **For Production:** Manual EC2 setup (2-3 hours, full control)

**My recommendation:** Start with Docker on EC2. You get:
- Fast deployment
- Easy updates
- Production-ready infrastructure
- Learning opportunity

Good luck! 🚀
