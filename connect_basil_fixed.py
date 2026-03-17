#!/usr/bin/env python3
"""Connect Basil to Agent Hub - Fixed version"""
import asyncio
import sys
sys.path.insert(0, '/home/daniel/.openclaw/agent_hub')

from client import OpenClawAgent

class BasilHubAgent(OpenClawAgent):
    """Basil connected to the hub - prevents message loops"""
    
    def __init__(self):
        super().__init__(
            name="Basil",
            description="Your OpenClaw assistant - helpful, direct, and warm",
            capabilities=["general_assistance", "coding", "coordination", "memory"]
        )
        self.recent_replies = set()  # Track what we've replied to
    
    def _default_message_handler(self, message: dict) -> str:
        content = message.get("content", "")
        sender = message.get("sender_name", "Unknown")
        sender_id = message.get("sender_id", "")
        msg_id = message.get("id", 0)
        
        # Don't reply to ourselves
        if sender == "Basil" or sender_id == self.agent_id:
            return None
        
        # Don't reply to the same message twice
        if msg_id in self.recent_replies:
            return None
        self.recent_replies.add(msg_id)
        
        # Keep set from growing too large
        if len(self.recent_replies) > 100:
            self.recent_replies.clear()
        
        # Only reply to actual chat messages, not system
        msg_type = message.get("message_type", "chat")
        if msg_type != "chat":
            return None
        
        # Simple greeting response
        if "hello" in content.lower() or "hi" in content.lower():
            return f"Hello {sender}! 🌿 Basil here. Nice to meet you in the hub!"
        
        # Default response
        return f"Hey {sender}! Basil here. I received your message about: '{content[:50]}...'"

async def main():
    basil = BasilHubAgent()
    
    # Get a token
    import requests
    try:
        response = requests.post("http://localhost:8765/api/invite", timeout=5)
        if response.status_code == 200:
            token = response.json()["token"]
            print(f"🎫 Got token: {token}")
            
            if await basil.connect("http://localhost:8765", token):
                print("✅ Basil is now in the Agent Hub!")
                print("Listening for messages... (Press Ctrl+C to disconnect)")
                await basil.run()
            else:
                print("❌ Failed to connect")
        else:
            print(f"❌ Failed to get token: {response.status_code}")
    except KeyboardInterrupt:
        print("\n👋 Disconnecting...")
        await basil.disconnect()
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
