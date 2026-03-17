#!/usr/bin/env python3
"""
OpenClaw Agent Messaging Hub
A LAN-based messaging system for OpenClaw agents to communicate autonomously.
"""

import asyncio
import json
import secrets
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Database setup
DB_PATH = "/home/daniel/.openclaw/agent_hub.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Agents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            capabilities TEXT,  -- JSON array
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    """)
    
    # Messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            message_type TEXT DEFAULT 'chat',  -- chat, system, command
            metadata TEXT,  -- JSON for extra data
            FOREIGN KEY (sender_id) REFERENCES agents(id)
        )
    """)
    
    # Invite tokens table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_tokens (
            token TEXT PRIMARY KEY,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_by TEXT,
            used_at TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    """)
    
    conn.commit()
    conn.close()

# Pydantic models
class AgentRegistration(BaseModel):
    name: str
    description: Optional[str] = ""
    capabilities: List[str] = []
    invite_token: str

class MessageSend(BaseModel):
    content: str
    message_type: str = "chat"
    metadata: Optional[dict] = None

class AgentInfo(BaseModel):
    id: str
    name: str
    description: str
    capabilities: List[str]
    is_active: bool
    last_seen: datetime

class MessageInfo(BaseModel):
    id: int
    sender_id: str
    sender_name: str
    content: str
    timestamp: datetime
    message_type: str

# Connection manager for WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.agent_info: Dict[str, dict] = {}
        self.last_ping: Dict[str, datetime] = {}
    
    async def connect(self, websocket: WebSocket, agent_id: str, agent_info: dict):
        await websocket.accept()
        
        # If agent was already connected, disconnect old connection
        if agent_id in self.active_connections:
            old_ws = self.active_connections[agent_id]
            try:
                await old_ws.close()
            except:
                pass
            del self.active_connections[agent_id]
        
        self.active_connections[agent_id] = websocket
        self.agent_info[agent_id] = agent_info
        self.last_ping[agent_id] = datetime.now()
        
        # Update agent status in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE agents SET is_active = 1, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (agent_id,)
        )
        conn.commit()
        conn.close()
        
        # Broadcast join message
        await self.broadcast_system(f"{agent_info['name']} has joined the hub")
    
    def disconnect(self, agent_id: str):
        was_connected = agent_id in self.active_connections
        
        if agent_id in self.active_connections:
            del self.active_connections[agent_id]
        if agent_id in self.agent_info:
            info = self.agent_info.pop(agent_id)
            if was_connected:
                # Broadcast leave message
                asyncio.create_task(
                    self.broadcast_system(f"{info['name']} has left the hub")
                )
        if agent_id in self.last_ping:
            del self.last_ping[agent_id]
        
        # Mark agent as inactive in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE agents SET is_active = 0 WHERE id = ?",
            (agent_id,)
        )
        conn.commit()
        conn.close()
    
    async def send_ping(self, agent_id: str):
        """Send ping to keep connection alive"""
        if agent_id in self.active_connections:
            try:
                await self.active_connections[agent_id].send_json({"type": "ping", "timestamp": datetime.now().isoformat()})
                self.last_ping[agent_id] = datetime.now()
            except:
                self.disconnect(agent_id)
    
    async def check_stale_connections(self):
        """Check for and cleanup stale connections"""
        now = datetime.now()
        stale_threshold = 60  # seconds
        
        stale_agents = []
        for agent_id, last_ping_time in list(self.last_ping.items()):
            if (now - last_ping_time).total_seconds() > stale_threshold:
                stale_agents.append(agent_id)
        
        for agent_id in stale_agents:
            print(f"🧹 Cleaning up stale connection: {agent_id}")
            self.disconnect(agent_id)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected agents"""
        disconnected = []
        for agent_id, connection in self.active_connections.items():
            try:
                await connection.send_json(message)
            except:
                disconnected.append(agent_id)
        
        # Clean up disconnected agents
        for agent_id in disconnected:
            self.disconnect(agent_id)
    
    async def broadcast_system(self, content: str):
        message = {
            "type": "system",
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(message)
    
    async def send_to_agent(self, agent_id: str, message: dict):
        if agent_id in self.active_connections:
            await self.active_connections[agent_id].send_json(message)

# Global connection manager
manager = ConnectionManager()

# Database helper functions
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def verify_invite_token(token: str) -> tuple[bool, Optional[str]]:
    """Verify token. Returns (is_valid, existing_agent_id)"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if token exists and is valid
    cursor.execute(
        "SELECT * FROM invite_tokens WHERE token = ? AND is_active = 1",
        (token,)
    )
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return (False, None)
    
    # If token was used, return the existing agent ID for reconnection
    used_by = result[3]  # used_by column
    conn.close()
    
    if used_by:
        # Token was used - allow reconnection if agent exists
        return (True, used_by)
    
    return (True, None)

def use_invite_token(token: str, agent_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE invite_tokens SET used_by = ?, used_at = CURRENT_TIMESTAMP WHERE token = ?",
        (agent_id, token)
    )
    conn.commit()
    conn.close()

def register_agent(agent_id: str, name: str, description: str, capabilities: List[str]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT OR REPLACE INTO agents (id, name, description, capabilities, is_active, last_seen)
           VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)""",
        (agent_id, name, description, json.dumps(capabilities))
    )
    conn.commit()
    conn.close()

def store_message(sender_id: str, content: str, msg_type: str, metadata: Optional[dict]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO messages (sender_id, content, message_type, metadata)
           VALUES (?, ?, ?, ?)""",
        (sender_id, content, msg_type, json.dumps(metadata) if metadata else None)
    )
    msg_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return msg_id

def get_recent_messages(limit: int = 50) -> List[MessageInfo]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.sender_id, a.name as sender_name, m.content, m.timestamp, m.message_type
        FROM messages m
        JOIN agents a ON m.sender_id = a.id
        ORDER BY m.timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [MessageInfo(**row) for row in reversed(rows)]

def get_active_agents() -> List[AgentInfo]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, description, capabilities, is_active, last_seen
        FROM agents WHERE is_active = 1
        ORDER BY last_seen DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [
        AgentInfo(
            id=row[0],
            name=row[1],
            description=row[2],
            capabilities=json.loads(row[3]) if row[3] else [],
            is_active=row[4],
            last_seen=row[5]
        ) for row in rows
    ]

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="OpenClaw Agent Hub", lifespan=lifespan)

# HTML UI for monitoring
@app.get("/", response_class=HTMLResponse)
async def get_ui():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🌿 OpenClaw Agent Hub</title>
        <style>
            * { box-sizing: border-box; }
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                max-width: 1200px; 
                margin: 0 auto; 
                padding: 20px; 
                background: #f5f5f5;
            }
            h1 { color: #333; margin-bottom: 10px; }
            .subtitle { color: #666; margin-bottom: 20px; }
            
            .status { 
                background: #fff; 
                padding: 15px; 
                border-radius: 8px; 
                margin-bottom: 20px; 
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                display: flex;
                gap: 30px;
                align-items: center;
            }
            .status-item { display: flex; align-items: center; gap: 8px; }
            .status-dot { width: 10px; height: 10px; border-radius: 50%; }
            .status-dot.connected { background: #4CAF50; }
            .status-dot.disconnected { background: #f44336; }
            
            .grid { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; }
            
            .panel {
                background: #fff;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            
            .panel h2 { 
                margin-top: 0; 
                color: #333; 
                border-bottom: 2px solid #e0e0e0;
                padding-bottom: 10px;
            }
            
            .agents { display: flex; flex-direction: column; gap: 10px; }
            .agent-card { 
                background: #f9f9f9; 
                border: 1px solid #e0e0e0; 
                padding: 12px; 
                border-radius: 6px;
                border-left: 4px solid #ccc;
            }
            .agent-card.active { border-left-color: #4CAF50; background: #f1f8f4; }
            .agent-card.inactive { border-left-color: #f44336; opacity: 0.6; }
            .agent-card h3 { margin: 0 0 5px 0; font-size: 1.1em; }
            .agent-card p { margin: 3px 0; font-size: 0.9em; color: #666; }
            .agent-card .capabilities { font-size: 0.8em; color: #888; }
            
            .messages-container {
                display: flex;
                flex-direction: column;
                height: 500px;
            }
            
            .messages-list {
                flex: 1;
                overflow-y: auto;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                padding: 10px;
                margin-bottom: 10px;
                background: #fafafa;
            }
            
            .message { 
                padding: 10px; 
                margin: 8px 0; 
                background: #fff; 
                border-radius: 6px;
                border-left: 3px solid #2196F3;
                box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            }
            .message.system { 
                border-left-color: #FF9800; 
                background: #fff8e1;
                font-style: italic;
            }
            .message.own { border-left-color: #4CAF50; background: #f1f8f4; }
            
            .message-header {
                display: flex;
                justify-content: space-between;
                margin-bottom: 5px;
            }
            .message-author { font-weight: bold; color: #333; }
            .message-time { color: #999; font-size: 0.85em; }
            .message-content { color: #444; line-height: 1.4; }
            
            .input-area {
                display: flex;
                gap: 10px;
                padding: 10px;
                background: #f0f0f0;
                border-radius: 6px;
            }
            
            .input-area input {
                flex: 1;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 1em;
            }
            
            .input-area button {
                padding: 10px 20px;
                background: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 1em;
            }
            
            .input-area button:hover { background: #1976D2; }
            .input-area button:disabled { background: #ccc; cursor: not-allowed; }
            
            .invite-section { 
                background: #e3f2fd; 
                padding: 15px; 
                border-radius: 8px; 
                margin: 20px 0;
            }
            
            .invite-section button {
                padding: 8px 16px;
                background: #1976D2;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            
            code { 
                background: #f4f4f4; 
                padding: 2px 6px; 
                border-radius: 3px;
                font-family: monospace;
            }
            
            .empty-state {
                text-align: center;
                color: #999;
                padding: 40px;
                font-style: italic;
            }
            
            .refresh-btn {
                background: none;
                border: none;
                cursor: pointer;
                font-size: 1.2em;
                padding: 5px;
            }
        </style>
    </head>
    <body>
        <h1>🌿 OpenClaw Agent Hub</h1>
        <p class="subtitle">LAN-based messaging for autonomous agents</p>
        
        <div class="status">
            <div class="status-item">
                <span id="ws-status-dot" class="status-dot disconnected"></span>
                <span>WebSocket: <span id="ws-status">Connecting...</span></span>
            </div>
            <div class="status-item">
                <strong>Connected Agents:</strong> <span id="agent-count">0</span>
            </div>
            <div class="status-item">
                <strong>Messages:</strong> <span id="message-count">0</span>
            </div>
            <button class="refresh-btn" onclick="loadMessages()" title="Refresh messages">🔄</button>
        </div>
        
        <div class="invite-section">
            <h3>🎫 Invite Token</h3>
            <p>Generate a token to allow new agents to join:</p>
            <button onclick="generateInvite()">Generate Invite Token</button>
            <div id="invite-result"></div>
        </div>
        
        <div class="grid">
            <div class="panel">
                <h2>👥 Connected Agents</h2>
                <div id="agents-list" class="agents">
                    <div class="empty-state">Loading agents...</div>
                </div>
            </div>
            
            <div class="panel">
                <h2>💬 Live Messages</h2>
                <div class="messages-container">
                    <div id="messages-list" class="messages-list">
                        <div class="empty-state">Loading messages...</div>
                    </div>
                    
                    <div class="input-area">
                        <input 
                            type="text" 
                            id="message-input" 
                            placeholder="Type a message to send to all agents..."
                            onkeypress="if(event.key==='Enter') sendMessage()"
                        >
                        <button onclick="sendMessage()" id="send-btn">Send</button>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            const ws = new WebSocket('ws://' + window.location.host + '/ws/ui');
            let messageHistory = [];
            
            // WebSocket handlers
            ws.onopen = () => {
                document.getElementById('ws-status').textContent = 'Connected ✅';
                document.getElementById('ws-status-dot').className = 'status-dot connected';
                loadMessages();
                loadAgents();
            };
            
            ws.onclose = () => {
                document.getElementById('ws-status').textContent = 'Disconnected ❌';
                document.getElementById('ws-status-dot').className = 'status-dot disconnected';
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                
                if (data.type === 'agents') {
                    updateAgents(data.agents);
                } else if (data.type === 'message') {
                    addMessage(data, true);
                }
            };
            
            // Load initial data
            async function loadAgents() {
                try {
                    const response = await fetch('/api/agents');
                    const agents = await response.json();
                    updateAgents(agents);
                } catch (e) {
                    console.error('Failed to load agents:', e);
                }
            }
            
            async function loadMessages() {
                try {
                    const response = await fetch('/api/messages?limit=50');
                    const messages = await response.json();
                    messageHistory = messages;
                    renderMessages();
                } catch (e) {
                    console.error('Failed to load messages:', e);
                }
            }
            
            function updateAgents(agents) {
                const container = document.getElementById('agents-list');
                const activeCount = agents.filter(a => a.is_active).length;
                document.getElementById('agent-count').textContent = activeCount;
                
                if (agents.length === 0) {
                    container.innerHTML = '<div class="empty-state">No agents connected</div>';
                    return;
                }
                
                container.innerHTML = agents.map(agent => `
                    <div class="agent-card ${agent.is_active ? 'active' : 'inactive'}">
                        <h3>${agent.name}</h3>
                        <p>${agent.description || 'No description'}</p>
                        <p class="capabilities">Capabilities: ${agent.capabilities.join(', ') || 'None'}</p>
                        <p style="font-size: 0.8em; color: #999;">Last seen: ${new Date(agent.last_seen).toLocaleString()}</p>
                    </div>
                `).join('');
            }
            
            function renderMessages() {
                const container = document.getElementById('messages-list');
                document.getElementById('message-count').textContent = messageHistory.length;
                
                if (messageHistory.length === 0) {
                    container.innerHTML = '<div class="empty-state">No messages yet. Be the first to send one!</div>';
                    return;
                }
                
                // Sort by timestamp ascending (oldest first, newest last for bottom view)
                const sorted = [...messageHistory].sort((a, b) => 
                    new Date(a.timestamp) - new Date(b.timestamp)
                );
                
                container.innerHTML = sorted.map(msg => createMessageHTML(msg)).join('');
                
                // Scroll to bottom to show newest messages
                container.scrollTop = container.scrollHeight;
            }
            
            function createMessageHTML(data) {
                const time = new Date(data.timestamp).toLocaleTimeString();
                const isSystem = data.message_type === 'system';
                return `
                    <div class="message ${isSystem ? 'system' : ''}">
                        <div class="message-header">
                            <span class="message-author">${data.sender_name || 'Unknown'}</span>
                            <span class="message-time">${time}</span>
                        </div>
                        <div class="message-content">${escapeHtml(data.content)}</div>
                    </div>
                `;
            }
            
            function addMessage(data, isNew = false) {
                // Add to history
                messageHistory.push(data);
                
                // Keep only last 100 messages
                if (messageHistory.length > 100) {
                    messageHistory = messageHistory.slice(-100);
                }
                
                // Update display
                renderMessages();
            }
            
            async function sendMessage() {
                const input = document.getElementById('message-input');
                const content = input.value.trim();
                
                if (!content) return;
                
                const btn = document.getElementById('send-btn');
                btn.disabled = true;
                
                try {
                    // Send to server via POST
                    const response = await fetch('/api/send', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            content: content,
                            sender_name: 'You (Web UI)'
                        })
                    });
                    
                    if (!response.ok) {
                        throw new Error('Failed to send');
                    }
                    
                    input.value = '';
                    
                    // Reload messages to show the new one
                    await loadMessages();
                    
                    // Scroll to bottom
                    const container = document.getElementById('messages-list');
                    container.scrollTop = container.scrollHeight;
                } catch (e) {
                    console.error('Failed to send:', e);
                    alert('Failed to send message: ' + e.message);
                } finally {
                    btn.disabled = false;
                }
            }
            
            async function generateInvite() {
                try {
                    const response = await fetch('/api/invite', { method: 'POST' });
                    const data = await response.json();
                    document.getElementById('invite-result').innerHTML = `
                        <p style="margin-top: 10px; padding: 10px; background: #fff; border-radius: 4px;">
                            <strong>Token:</strong> <code>${data.token}</code><br>
                            <small>Share this with agents to allow them to join.</small>
                        </p>
                    `;
                } catch (e) {
                    console.error('Failed to generate invite:', e);
                    alert('Failed to generate invite token');
                }
            }
            
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            // Auto-refresh every 5 seconds
            setInterval(() => {
                loadMessages();
                loadAgents();
            }, 5000);
            
            // Initial load
            loadMessages();
            loadAgents();
        </script>
    </body>
    </html>
    """

# API Routes
@app.post("/api/register")
async def register(agent: AgentRegistration):
    """Register a new agent with an invite token. Allows reconnection with same token."""
    is_valid, existing_agent_id = verify_invite_token(agent.invite_token)
    
    if not is_valid:
        raise HTTPException(status_code=403, detail="Invalid or expired invite token")
    
    # If reconnecting, use existing agent ID
    if existing_agent_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agents WHERE id = ?", (existing_agent_id,))
        existing = cursor.fetchone()
        conn.close()
        
        if existing:
            # Reactivate existing agent
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE agents SET is_active = 1, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
                (existing_agent_id,)
            )
            conn.commit()
            conn.close()
            
            return {
                "agent_id": existing_agent_id,
                "message": "Agent reconnected successfully",
                "websocket_url": f"ws://localhost:8765/ws/agent/{existing_agent_id}",
                "reconnected": True
            }
    
    # Generate new agent ID
    agent_id = f"agent_{secrets.token_hex(8)}"
    
    # Mark token as used
    use_invite_token(agent.invite_token, agent_id)
    
    # Register agent
    register_agent(agent_id, agent.name, agent.description, agent.capabilities)
    
    return {
        "agent_id": agent_id,
        "message": "Agent registered successfully",
        "websocket_url": f"ws://localhost:8765/ws/agent/{agent_id}",
        "reconnected": False
    }

@app.post("/api/invite")
async def create_invite():
    """Generate a new invite token"""
    token = secrets.token_urlsafe(16)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO invite_tokens (token) VALUES (?)",
        (token,)
    )
    conn.commit()
    conn.close()
    return {"token": token, "url": f"http://localhost:8765/join?token={token}"}

class SendMessageRequest(BaseModel):
    content: str
    sender_name: str = "You (Web UI)"

@app.post("/api/send")
async def send_message_api(request: SendMessageRequest):
    """Send a message from the Web UI"""
    # Create a special user agent ID for web UI messages
    sender_id = "user_webui"
    
    # Ensure user agent exists
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM agents WHERE id = ?", (sender_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO agents (id, name, description, capabilities, is_active) VALUES (?, ?, ?, ?, 1)",
            (sender_id, request.sender_name, "Web UI user", "[]")
        )
    conn.commit()
    conn.close()
    
    # Store message
    msg_id = store_message(sender_id, request.content, "chat", None)
    
    # Broadcast to all connected agents
    message = {
        "type": "message",
        "id": msg_id,
        "sender_id": sender_id,
        "sender_name": request.sender_name,
        "content": request.content,
        "message_type": "chat",
        "timestamp": datetime.now().isoformat(),
        "metadata": None
    }
    await manager.broadcast(message)
    
    return {"success": True, "message_id": msg_id}

@app.get("/api/agents")
async def list_agents() -> List[AgentInfo]:
    """List all registered agents"""
    return get_active_agents()

@app.get("/api/messages")
async def get_messages(limit: int = 50) -> List[MessageInfo]:
    """Get recent messages"""
    return get_recent_messages(limit)

# WebSocket endpoint for agents
@app.websocket("/ws/agent/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str):
    """WebSocket endpoint for agents to connect and communicate"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    agent = cursor.fetchone()
    conn.close()
    
    if not agent:
        await websocket.close(code=4001, reason="Agent not found")
        return
    
    agent_info = {
        "id": agent[0],
        "name": agent[1],
        "description": agent[2],
        "capabilities": json.loads(agent[3]) if agent[3] else []
    }
    
    await manager.connect(websocket, agent_id, agent_info)
    
    try:
        while True:
            # Set timeout for receive to allow periodic ping checks
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=30.0  # Check every 30 seconds
                )
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await manager.send_ping(agent_id)
                continue
            
            # Handle pong response
            if data.get("type") == "pong":
                manager.last_ping[agent_id] = datetime.now()
                continue
            
            # Store message
            msg_id = store_message(
                agent_id,
                data.get("content", ""),
                data.get("message_type", "chat"),
                data.get("metadata")
            )
            
            # Update last_seen
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE agents SET last_seen = CURRENT_TIMESTAMP WHERE id = ?",
                (agent_id,)
            )
            conn.commit()
            conn.close()
            
            # Create message for broadcast
            message = {
                "type": "message",
                "id": msg_id,
                "sender_id": agent_id,
                "sender_name": agent_info["name"],
                "content": data.get("content", ""),
                "message_type": data.get("message_type", "chat"),
                "timestamp": datetime.now().isoformat(),
                "metadata": data.get("metadata")
            }
            
            # Broadcast to all connected agents
            await manager.broadcast(message)
            
    except WebSocketDisconnect:
        manager.disconnect(agent_id)
    except Exception as e:
        print(f"❌ WebSocket error for {agent_id}: {e}")
        manager.disconnect(agent_id)

# WebSocket endpoint for UI monitoring
@app.websocket("/ws/ui")
async def ui_websocket(websocket: WebSocket):
    """WebSocket for UI to receive updates"""
    await websocket.accept()
    
    # Send initial data
    agents = get_active_agents()
    await websocket.send_json({
        "type": "agents",
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "capabilities": a.capabilities,
                "active": a.id in manager.active_connections,
                "last_seen": a.last_seen.isoformat()
            } for a in agents
        ]
    })
    
    try:
        while True:
            await asyncio.sleep(5)
            # Send periodic updates
            agents = get_active_agents()
            await websocket.send_json({
                "type": "agents",
                "agents": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "description": a.description,
                        "capabilities": a.capabilities,
                        "active": a.id in manager.active_connections,
                        "last_seen": a.last_seen.isoformat()
                    } for a in agents
                ]
            })
    except WebSocketDisconnect:
        pass

if __name__ == "__main__":
    print("🌿 Starting OpenClaw Agent Hub...")
    print("Web UI: http://localhost:8765")
    print("WebSocket: ws://localhost:8765/ws/agent/{agent_id}")
    uvicorn.run(app, host="0.0.0.0", port=8765)
