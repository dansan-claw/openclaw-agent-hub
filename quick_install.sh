#!/bin/bash
# Quick fix for PEP 668 - install directly with --break-system-packages

echo "🌿 Quick installing dependencies..."

# Install to user space with override
pip3 install --break-system-packages --user fastapi uvicorn websockets requests

if [ $? -eq 0 ]; then
    echo "✅ Dependencies installed!"
    echo ""
    echo "You can now start the hub:"
    echo "  cd ~/.openclaw/agent_hub"
    echo "  python3 server.py"
else
    echo "❌ Installation failed. Try:"
    echo "  sudo apt install python3-fastapi python3-uvicorn python3-websockets python3-requests"
fi
