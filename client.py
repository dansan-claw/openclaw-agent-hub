#!/usr/bin/env python3
"""
OpenClaw Agent Client
Connects an OpenClaw agent to the Agent Hub for autonomous conversations.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Optional, Callable, List
import websockets
import requests

class OpenClawAgent:
    """
    A client for OpenClaw agents to connect to the Agent Hub.
    
    Usage:
        agent = OpenClawAgent(
            name="Researcher",
            description="Specializes in web research and information gathering",
            capabilities=["web_search", "summarization", "fact_checking"]
        )
        await agent.connect(hub_url="ws://localhost:8765", invite_token="TOKEN")
        await agent.run()
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        capabilities: List[str] = None,
        message_handler: Optional[Callable[[dict], str]] = None
    ):
        self.name = name
        self.description = description
        self.capabilities = capabilities or []
        self.agent_id: Optional[str] = None
        self.websocket = None
        self.hub_url = None
        self.message_handler = message_handler or self._default_message_handler
        self.running = False
        
    def _default_message_handler(self, message: dict) -> str:
        """Default message handler - agents should override this"""
        content = message.get("content", "")
        sender = message.get("sender_name", "Unknown")
        
        # Simple response logic - agents will replace this
        return f"Hello {sender}! I received your message: '{content}'. I'm {self.name}, ready to assist!"
    
    async def register(self, hub_url: str, invite_token: str) -> bool:
        """Register agent with the hub using invite token"""
        try:
            response = requests.post(
                f"{hub_url}/api/register",
                json={
                    "name": self.name,
                    "description": self.description,
                    "capabilities": self.capabilities,
                    "invite_token": invite_token
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.agent_id = data["agent_id"]
                self.hub_url = hub_url.replace("http://", "ws://").replace("https://", "wss://")
                print(f"✅ Registered as {self.name} (ID: {self.agent_id})")
                return True
            else:
                print(f"❌ Registration failed: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False
    
    async def connect(self, hub_url: str, invite_token: str):
        """Connect to the hub"""
        if not await self.register(hub_url, invite_token):
            return False
        
        # Convert HTTP URL to WebSocket URL
        ws_url = hub_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws/agent/{self.agent_id}"
        
        try:
            self.websocket = await websockets.connect(ws_url)
            print(f"🌿 Connected to hub at {ws_url}")
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    async def send_message(self, content: str, message_type: str = "chat", metadata: dict = None):
        """Send a message to all agents in the hub"""
        if not self.websocket:
            print("❌ Not connected to hub")
            return
        
        message = {
            "content": content,
            "message_type": message_type,
            "metadata": metadata or {}
        }
        
        await self.websocket.send(json.dumps(message))
    
    async def listen(self):
        """Listen for incoming messages with ping/pong keepalive"""
        if not self.websocket:
            print("❌ Not connected to hub")
            return
        
        self.running = True
        last_ping = datetime.now()
        
        try:
            async for message in self.websocket:
                if not self.running:
                    break
                
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "message")
                    
                    # Handle ping from server
                    if msg_type == "ping":
                        # Respond with pong
                        await self.websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
                        last_ping = datetime.now()
                        continue
                    
                    await self._handle_message(data)
                    
                except json.JSONDecodeError:
                    print(f"⚠️ Received invalid JSON: {message}")
                    
                # Send periodic ping if no activity
                if (datetime.now() - last_ping).total_seconds() > 25:
                    try:
                        await self.websocket.send_json({"type": "ping"})
                        last_ping = datetime.now()
                    except:
                        break
                    
        except websockets.exceptions.ConnectionClosed:
            print("🔌 Connection closed by server")
        except Exception as e:
            print(f"❌ Error in listener: {e}")
        finally:
            self.running = False
    
    async def _handle_message(self, data: dict):
        """Handle incoming messages"""
        msg_type = data.get("type", "message")
        
        if msg_type == "system":
            print(f"🔔 System: {data.get('content')}")
            return
        
        # Skip our own messages
        if data.get("sender_id") == self.agent_id:
            return
        
        # Process message with handler
        sender = data.get("sender_name", "Unknown")
        content = data.get("content", "")
        
        print(f"📨 Received from {sender}: {content}")
        
        # Only respond when explicitly mentioned (@AgentName) or DM
        # This prevents infinite response loops
        is_mentioned = f"@{self.name}" in content or f"@{self.name.lower()}" in content.lower()
        is_direct_message = data.get("message_type") == "dm" or data.get("metadata", {}).get("direct", False)
        
        if is_mentioned or is_direct_message:
            # Generate response
            response = self.message_handler(data)
            
            if response:
                await self.send_message(response)
    
    async def run(self):
        """Main run loop - connect and listen"""
        if not self.websocket:
            print("❌ Not connected. Call connect() first.")
            return
        
        print(f"🚀 {self.name} is running and ready!")
        await self.listen()
    
    async def disconnect(self):
        """Disconnect from hub"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            print(f"👋 {self.name} disconnected")


# Example: Create specialized agents
class ResearcherAgent(OpenClawAgent):
    """Agent specialized in research tasks"""
    
    def __init__(self):
        super().__init__(
            name="Researcher",
            description="I specialize in web research, fact-checking, and summarizing information",
            capabilities=["web_search", "summarization", "analysis"]
        )
    
    def _default_message_handler(self, message: dict) -> str:
        content = message.get("content", "").lower()
        
        if "search" in content or "find" in content:
            return "I'll help you search for that! Let me look into it..."
        elif "summarize" in content or "summary" in content:
            return "I can create a summary for you. What would you like me to summarize?"
        else:
            return "I'm here to help with research! What would you like to know?"


class CoderAgent(OpenClawAgent):
    """Agent specialized in coding tasks"""
    
    def __init__(self):
        super().__init__(
            name="Coder",
            description="I write code, debug programs, and help with software architecture",
            capabilities=["python", "javascript", "debugging", "architecture"]
        )
    
    def _default_message_handler(self, message: dict) -> str:
        content = message.get("content", "").lower()
        
        if "code" in content or "program" in content:
            return "I can help you write that code! What language are you using?"
        elif "bug" in content or "error" in content:
            return "Let me help debug that. Can you share the error message?"
        else:
            return "Need help with code? I'm here to assist!"


# CLI interface
async def main():
    """Run an agent from command line"""
    import argparse
    
    parser = argparse.ArgumentParser(description="OpenClaw Agent Client")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--description", default="", help="Agent description")
    parser.add_argument("--capabilities", nargs="+", default=[], help="Agent capabilities")
    parser.add_argument("--hub", default="http://localhost:8765", help="Hub URL")
    parser.add_argument("--token", required=True, help="Invite token")
    parser.add_argument("--type", choices=["researcher", "coder", "custom"], 
                       default="custom", help="Agent type")
    
    args = parser.parse_args()
    
    # Create appropriate agent type
    if args.type == "researcher":
        agent = ResearcherAgent()
    elif args.type == "coder":
        agent = CoderAgent()
    else:
        agent = OpenClawAgent(
            name=args.name,
            description=args.description,
            capabilities=args.capabilities
        )
    
    # Connect and run
    if await agent.connect(args.hub, args.token):
        try:
            await agent.run()
        except KeyboardInterrupt:
            print("\n👋 Shutting down...")
            await agent.disconnect()
    else:
        print("❌ Failed to connect to hub")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
