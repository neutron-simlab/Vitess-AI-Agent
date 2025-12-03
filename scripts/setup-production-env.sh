#!/bin/bash
# setup-production-env.sh - Initial setup script for Digital Ocean droplet
#
# This script sets up the production environment on a fresh Digital Ocean droplet.
# It should be run once during initial server setup.
#
# Usage:
#   ./scripts/setup-production-env.sh
#
# Or run directly on the droplet:
#   curl -fsSL https://raw.githubusercontent.com/your-org/vitess-ai-agent/main/scripts/setup-production-env.sh | bash
#
# Prerequisites:
#   - Fresh Ubuntu 22.04 LTS droplet
#   - Root or sudo access
#   - SSH key access configured

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_DIR="/opt/vitess-ai"
ENV_DIR="/etc/vitess-ai"
ENV_FILE="$ENV_DIR/.env"
DATA_DIR="/data"
PROJECTS_DIR="$DATA_DIR/projects"
LOGS_DIR="$DATA_DIR/logs"

# Logging functions
log() {
  echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
  echo -e "${RED}[ERROR]${NC} $1" >&2
}

warning() {
  echo -e "${YELLOW}[WARNING]${NC} $1"
}

info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

# Check if running as root
check_root() {
  if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root or with sudo"
    exit 1
  fi
}

# Update system packages
update_system() {
  log "Updating system packages..."
  apt-get update
  apt-get upgrade -y
  log "System packages updated"
}

# Install Docker
install_docker() {
  if command -v docker &> /dev/null; then
    warning "Docker is already installed"
    return
  fi
  
  log "Installing Docker..."
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh
  rm get-docker.sh
  
  # Add current user to docker group (if not root)
  if [[ -n "${SUDO_USER:-}" ]]; then
    usermod -aG docker "$SUDO_USER"
  fi
  
  log "Docker installed successfully"
}

# Install Docker Compose
install_docker_compose() {
  if command -v docker-compose &> /dev/null || docker compose version &> /dev/null; then
    warning "Docker Compose is already installed"
    return
  fi
  
  log "Installing Docker Compose..."
  apt-get install -y docker-compose-plugin
  log "Docker Compose installed successfully"
}

# Configure firewall
configure_firewall() {
  log "Configuring firewall (UFW)..."
  
  # Check if UFW is installed
  if ! command -v ufw &> /dev/null; then
    apt-get install -y ufw
  fi
  
  # Allow SSH (important - do this first!)
  ufw allow 22/tcp comment 'SSH'
  
  # Allow application ports
  ufw allow 8000/tcp comment 'FastAPI'
  ufw allow 8501/tcp comment 'Streamlit'
  ufw allow 9001/tcp comment 'MCP Read-in'
  ufw allow 9002/tcp comment 'MCP Guide'
  ufw allow 9003/tcp comment 'MCP Writeout'
  ufw allow 9004/tcp comment 'MCP Monitor'
  ufw allow 9005/tcp comment 'MCP Supervisor'
  
  # Enable firewall
  ufw --force enable
  
  log "Firewall configured"
  info "Firewall status:"
  ufw status
}

# Create application directories
create_directories() {
  log "Creating application directories..."
  
  # Application directory
  mkdir -p "$APP_DIR"
  
  # Environment directory
  mkdir -p "$ENV_DIR"
  
  # Data directories
  mkdir -p "$PROJECTS_DIR"
  mkdir -p "$LOGS_DIR"
  
  # Set permissions
  chmod 755 "$APP_DIR"
  chmod 755 "$DATA_DIR"
  chmod 755 "$PROJECTS_DIR"
  chmod 755 "$LOGS_DIR"
  
  log "Directories created"
}

# Create production environment file template
create_env_template() {
  log "Creating environment file template..."
  
  if [[ -f "$ENV_FILE" ]]; then
    warning "Environment file already exists at $ENV_FILE"
    read -p "Do you want to overwrite it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      info "Skipping environment file creation"
      return
    fi
  fi
  
  cat > "$ENV_FILE" << 'ENVEOF'
# =============================================================================
# VITESS AI AGENT PRODUCTION CONFIGURATION
# =============================================================================
# Fill in your actual API keys and configuration values below.
# This file should NEVER be committed to version control.

# Core API Keys (REQUIRED)
OPENAI_API_KEY=your-openai-api-key-here
BLABLADOR_API_KEY=your-blablador-api-key-here
LANGSMITH_API_KEY=your-langsmith-api-key-here

# LLM Configuration
DEFAULT_PROVIDER=openai
FALLBACK_PROVIDER=blablador
DEFAULT_MODEL=gpt-4o-mini-2024-07-18
MAX_TOKENS=4000
TIMEOUT_SECONDS=60
MAX_RETRIES=3

# Blablador Settings
BLABLADOR_BASE_URL=https://api.helmholtz-blablador.fz-juelich.de/v1/
BLABLADOR_DEFAULT_MODEL=alias-fast-experiment

# LangSmith Settings
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=Vitess-AI-Agent

# MCP Configuration
MCP_TRANSPORT_MODE=http
MCP_HOST=0.0.0.0
MCP_READIN_PORT=9001
MCP_GUIDE_PORT=9002
MCP_WRITEOUT_PORT=9003
MCP_MONITOR_PORT=9004
MCP_SUPERVISOR_PORT=9005

# Environment
ENVIRONMENT=production
LOG_LEVEL=INFO

# Vitess paths (set by docker-compose volumes)
VITESS_MODULES_PATH=/vitess/MODULES
VITESS_PROJECT_PATH=/data/projects
VITESS_LOG_PATH=/data/logs/logfile.log
ENVEOF

  # Set restrictive permissions
  chmod 600 "$ENV_FILE"
  chown root:root "$ENV_FILE"
  
  log "Environment file template created at $ENV_FILE"
  warning "⚠️  IMPORTANT: Edit $ENV_FILE and fill in your actual API keys!"
}

# Secure SSH configuration
secure_ssh() {
  log "Securing SSH configuration..."
  
  # Backup SSH config
  cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup
  
  # Disable password authentication (use keys only)
  sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
  sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
  
  # Restart SSH service
  systemctl restart sshd
  
  log "SSH secured (password authentication disabled)"
  warning "⚠️  Make sure you have SSH key access before disconnecting!"
}

# Install Git (if not already installed)
install_git() {
  if command -v git &> /dev/null; then
    warning "Git is already installed"
    return
  fi
  
  log "Installing Git..."
  apt-get install -y git
  log "Git installed"
}

# Clone repository (optional - user can do this manually)
setup_repository() {
  if [[ -d "$APP_DIR/.git" ]]; then
    warning "Repository already exists at $APP_DIR"
    return
  fi
  
  info "Repository setup:"
  info "  You can clone your repository manually:"
  info "    cd $APP_DIR"
  info "    git clone https://github.com/your-org/vitess-ai-agent.git ."
  info ""
  read -p "Do you want to clone the repository now? (y/N): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter repository URL: " repo_url
    if [[ -n "$repo_url" ]]; then
      cd "$APP_DIR"
      git clone "$repo_url" .
      log "Repository cloned"
    fi
  fi
}

# Print summary
print_summary() {
  echo ""
  echo -e "${GREEN}========================================${NC}"
  echo -e "${GREEN}Setup Complete!${NC}"
  echo -e "${GREEN}========================================${NC}"
  echo ""
  info "Next steps:"
  echo "  1. Edit $ENV_FILE and fill in your API keys:"
  echo "     sudo nano $ENV_FILE"
  echo ""
  echo "  2. Clone your repository (if not done already):"
  echo "     cd $APP_DIR"
  echo "     git clone https://github.com/your-org/vitess-ai-agent.git ."
  echo ""
  echo "  3. Configure GitHub Secrets for CI/CD:"
  echo "     - OPENAI_API_KEY"
  echo "     - BLABLADOR_API_KEY (if used)"
  echo "     - LANGSMITH_API_KEY (if used)"
  echo "     - DIGITALOCEAN_HOST"
  echo "     - DIGITALOCEAN_USER"
  echo "     - DIGITALOCEAN_SSH_KEY"
  echo ""
  echo "  4. Deploy using GitHub Actions or manually:"
  echo "     cd $APP_DIR"
  echo "     docker-compose up -d"
  echo ""
  echo -e "${YELLOW}Important files:${NC}"
  echo "  - Environment file: $ENV_FILE"
  echo "  - Application directory: $APP_DIR"
  echo "  - Projects directory: $PROJECTS_DIR"
  echo "  - Logs directory: $LOGS_DIR"
  echo ""
}

# Main execution
main() {
  log "Starting production environment setup..."
  log "This script will:"
  log "  1. Update system packages"
  log "  2. Install Docker and Docker Compose"
  log "  3. Configure firewall"
  log "  4. Create necessary directories"
  log "  5. Create environment file template"
  log "  6. Secure SSH configuration"
  echo ""
  
  read -p "Continue with setup? (y/N): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    info "Setup cancelled"
    exit 0
  fi
  
  check_root
  update_system
  install_docker
  install_docker_compose
  configure_firewall
  create_directories
  create_env_template
  install_git
  secure_ssh
  setup_repository
  print_summary
  
  log "Setup completed successfully!"
}

# Run main function
main

