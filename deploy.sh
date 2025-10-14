#!/bin/bash

# Telegram Taxi Bot - Deploy Script
# Usage: ./deploy.sh [render|docker|vps]

set -e

echo "🚀 Telegram Taxi Bot - Deploy Script"
echo "======================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Check if .env exists
check_env() {
    if [ ! -f .env ]; then
        warn ".env file not found"
        if [ -f .env.example ]; then
            info "Creating .env from .env.example..."
            cp .env.example .env
            warn "Please edit .env and add your BOT_TOKEN"
            nano .env
        else
            error ".env.example not found"
        fi
    fi
    
    # Check if BOT_TOKEN is set
    if ! grep -q "BOT_TOKEN=.*[a-zA-Z0-9]" .env; then
        error "BOT_TOKEN not set in .env file"
    fi
    
    info "✅ .env file configured"
}

# Deploy to Render.com
deploy_render() {
    info "Deploying to Render.com..."
    
    # Check if git repo exists
    if [ ! -d .git ]; then
        warn "Git repository not initialized"
        read -p "Initialize git repository? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            git init
            git add .
            git commit -m "Initial commit: Telegram Taxi Bot"
            info "Git repository initialized"
        else
            error "Git repository required for Render deployment"
        fi
    fi
    
    # Check if remote exists
    if ! git remote get-url origin > /dev/null 2>&1; then
        warn "Git remote 'origin' not configured"
        read -p "Enter GitHub repository URL: " repo_url
        git remote add origin "$repo_url"
        info "Remote added: $repo_url"
    fi
    
    # Push to GitHub
    info "Pushing to GitHub..."
    git add .
    git commit -m "Deploy: $(date +'%Y-%m-%d %H:%M:%S')" || info "No changes to commit"
    git push -u origin main || git push -u origin master
    
    info "✅ Code pushed to GitHub"
    echo ""
    echo "Next steps:"
    echo "1. Go to https://render.com"
    echo "2. Click 'New +' → 'Blueprint'"
    echo "3. Connect your GitHub repository"
    echo "4. Add environment variables (BOT_TOKEN, GOOGLE_MAPS_API_KEY)"
    echo "5. Deploy!"
    echo ""
    echo "📖 Full guide: DEPLOY.md"
}

# Deploy with Docker
deploy_docker() {
    info "Deploying with Docker..."
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        error "Docker not installed. Install from https://docker.com"
    fi
    
    # Check if docker-compose is installed
    if ! command -v docker-compose &> /dev/null; then
        warn "docker-compose not installed, using 'docker compose' instead"
    fi
    
    check_env
    
    info "Building Docker image..."
    docker build -t telegram-taxi-bot .
    
    info "Starting container..."
    if command -v docker-compose &> /dev/null; then
        docker-compose up -d
    else
        docker compose up -d
    fi
    
    info "✅ Bot deployed with Docker"
    echo ""
    echo "View logs: docker-compose logs -f"
    echo "Stop bot: docker-compose down"
    echo "Restart: docker-compose restart"
}

# Deploy to VPS
deploy_vps() {
    info "Setting up for VPS deployment..."
    
    check_env
    
    # Check if Python is installed
    if ! command -v python3 &> /dev/null; then
        error "Python3 not installed"
    fi
    
    # Check Python version
    py_version=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    if (( $(echo "$py_version < 3.10" | bc -l) )); then
        error "Python 3.10+ required (found $py_version)"
    fi
    
    info "Creating virtual environment..."
    python3 -m venv venv
    
    info "Activating virtual environment..."
    source venv/bin/activate
    
    info "Installing dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    
    info "Creating data directory..."
    mkdir -p data
    
    info "✅ Bot configured for VPS"
    echo ""
    echo "To run the bot:"
    echo "  source venv/bin/activate"
    echo "  python -m app.main"
    echo ""
    echo "For production (systemd service):"
    echo "  sudo cp telegram-taxi-bot.service /etc/systemd/system/"
    echo "  sudo systemctl enable telegram-taxi-bot"
    echo "  sudo systemctl start telegram-taxi-bot"
    echo ""
    echo "📖 Full guide: DEPLOY.md"
}

# Main
main() {
    case "$1" in
        render)
            deploy_render
            ;;
        docker)
            deploy_docker
            ;;
        vps)
            deploy_vps
            ;;
        *)
            echo "Usage: $0 [render|docker|vps]"
            echo ""
            echo "Options:"
            echo "  render  - Deploy to Render.com (recommended)"
            echo "  docker  - Deploy with Docker locally or on VPS"
            echo "  vps     - Setup for VPS deployment"
            echo ""
            echo "Example: $0 docker"
            exit 1
            ;;
    esac
}

main "$@"
