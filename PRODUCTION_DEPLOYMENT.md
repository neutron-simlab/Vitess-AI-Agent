# Production Deployment Guide

This guide covers deploying Vitess AI Agent to a production server with secure API key management and optional CI/CD.

## Quick Start

1. **Set up GitHub Secrets** (Repository Settings → Secrets → Actions), if using CI/CD:
   - `OPENAI_API_KEY` - Your OpenAI API key
   - `BLABLADOR_API_KEY` - Your Blablador API key (if used)
   - `LANGSMITH_API_KEY` - Your LangSmith API key (if used)
   - `DEPLOY_HOST` - Your server IP or hostname
   - `DEPLOY_USER` - SSH username (e.g. `root` or `ubuntu`)
   - `DEPLOY_SSH_KEY` - Private SSH key for server access

2. **Set up production server** (any Ubuntu 22.04 host):
   ```bash
   # Run setup script on fresh Ubuntu 22.04 server
   curl -fsSL https://raw.githubusercontent.com/your-org/vitess-ai-agent/main/scripts/setup-production-env.sh | sudo bash
   ```

3. **Deploy** (if using CI/CD):
   - Push to `main` or `production` branch
   - GitHub Actions runs tests, builds images, and deploys to your server

## Initial Server Setup

### Automated Setup (Recommended)

Run the setup script:
```bash
curl -fsSL https://raw.githubusercontent.com/your-org/vitess-ai-agent/main/scripts/setup-production-env.sh | sudo bash
```

This installs Docker, configures firewall, and creates necessary directories.

### Manual Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo apt install docker-compose-plugin -y

# Configure firewall
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 8000/tcp  # FastAPI
sudo ufw allow 8501/tcp  # Streamlit
sudo ufw allow 9001:9005/tcp  # MCP servers
sudo ufw enable

# Create directories
sudo mkdir -p /opt/vitess-ai /etc/vitess-ai /data/projects /data/logs

# Clone repository
cd /opt/vitess-ai
git clone https://github.com/your-org/vitess-ai-agent.git .
```

## Environment Variables

### Production Environment File

Create `/etc/vitess-ai/.env` on your server:

```bash
sudo nano /etc/vitess-ai/.env
sudo chmod 600 /etc/vitess-ai/.env
sudo chown root:root /etc/vitess-ai/.env
```

**Required variables** (see `env.production.example` for full template):
```bash
OPENAI_API_KEY=sk-your-key-here
BLABLADOR_API_KEY=your-key-here
LANGSMITH_API_KEY=your-key-here
DEFAULT_PROVIDER=openai
ENVIRONMENT=production
LOG_LEVEL=INFO
```

The GitHub Actions workflow automatically creates this file from secrets during deployment.

## Deployment

### Automated (Recommended)

1. Push code to `main` or `production` branch
2. GitHub Actions runs:
   - Tests
   - Docker image builds
   - Deployment to server
   - Health checks

### Manual Deployment

```bash
# SSH to server
ssh root@your-server-ip

# Navigate to app
cd /opt/vitess-ai

# Update code
git pull origin main

# Update environment (if needed)
sudo nano /etc/vitess-ai/.env
sudo chmod 600 /etc/vitess-ai/.env

# Deploy
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

## Security Best Practices

1. **File Permissions**: Always set `/etc/vitess-ai/.env` to 600
   ```bash
   sudo chmod 600 /etc/vitess-ai/.env
   ```

2. **Never Commit Secrets**: `.env` files are in `.gitignore` - keep them out of git

3. **Rotate Keys**: Update API keys every 90 days

4. **Firewall**: Only open necessary ports (22, 8000, 8501, 9001-9005)

5. **SSH Keys**: Use SSH keys only, disable password authentication

## Troubleshooting

### Deployment Fails: Permission Denied
```bash
# Test SSH connection
ssh -i ~/.ssh/your-key root@your-server-ip
# Verify SSH key in GitHub Secrets
```

### Environment Variables Not Loading
```bash
# Check file exists and permissions
ls -la /etc/vitess-ai/.env
sudo chmod 600 /etc/vitess-ai/.env

# Verify docker-compose loads it
docker-compose config | grep OPENAI_API_KEY
```

### Health Check Fails
```bash
# Check container logs
docker-compose logs vitess-ai-agent

# Check container status
docker-compose ps

# Verify service is running
curl http://localhost:8000/health
```

### API Key Invalid
```bash
# Verify key in container
docker-compose exec vitess-ai-agent env | grep OPENAI_API_KEY

# Test API key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

## Files Reference

- **`docker-compose.yml`** - Single Docker Compose file (works for both dev and prod)
- **`env.production.example`** - Production environment template
- **`.github/workflows/deploy.yml`** - CI/CD pipeline
- **`scripts/setup-production-env.sh`** - Initial setup script

## Quick Checklist

**Initial Setup**:
- [ ] Provision a server (Ubuntu 22.04 recommended)
- [ ] Run setup script or configure manually
- [ ] Set up GitHub Secrets (if using CI/CD)
- [ ] Push to `main` branch (triggers deployment if CI/CD is configured)

**Regular Maintenance**:
- [ ] Rotate API keys every 90 days
- [ ] Monitor deployment logs
- [ ] Update dependencies regularly
- [ ] Backup environment file securely

For detailed troubleshooting or advanced configuration, see the inline comments in the workflow and script files.
