#!/bin/bash
# OpenClaw Agent Hub Setup Script - Fixed for PEP 668

echo "🌿 Setting up OpenClaw Agent Hub..."

# Create directory
mkdir -p ~/.openclaw/agent_hub
cd ~/.openclaw/agent_hub

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
echo "📍 Python version: $PYTHON_VERSION"

# Try to create virtual environment
echo "📦 Creating virtual environment..."
if python3 -m venv venv 2>/dev/null; then
    echo "✅ Virtual environment created"
    USE_VENV=true
else
    echo "⚠️  Could not create venv (python3-venv may be missing)"
    echo "   Will try alternative methods..."
    USE_VENV=false
fi

# Install dependencies
if [ "$USE_VENV" = true ]; then
    echo "📥 Installing dependencies in virtual environment..."
    source venv/bin/activate
    pip install fastapi uvicorn websockets requests
else
    echo "📥 Installing dependencies with --break-system-packages..."
    pip3 install --break-system-packages --user fastapi uvicorn websockets requests 2>/dev/null || \
    pip3 install --user fastapi uvicorn websockets requests 2>/dev/null || \
    python3 -m pip install --user fastapi uvicorn websockets requests
fi

# Create launcher scripts
cat > start_hub.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
if [ -d "venv" ] && [ -f "venv/bin/python" ]; then
    source venv/bin/activate
    python server.py
else
    python3 server.py
fi
EOF
chmod +x start_hub.sh

cat > start_agent.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
if [ -d "venv" ] && [ -f "venv/bin/python" ]; then
    source venv/bin/activate
    python client.py "$@"
else
    python3 client.py "$@"
fi
EOF
chmod +x start_agent.sh

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the hub:"
echo "  cd ~/.openclaw/agent_hub"
echo "  ./start_hub.sh"
echo ""
echo "To create an invite token:"
echo "  curl -X POST http://localhost:8765/api/invite"
echo ""
echo "To start an agent:"
echo "  ./start_agent.sh --name \"MyAgent\" --token \"INVITE_TOKEN\" --hub http://localhost:8765"
echo ""
echo "Web UI available at: http://localhost:8765"
