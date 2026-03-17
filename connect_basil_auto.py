#!/usr/bin/env python3
"""Connect Basil to Agent Hub"""
import asyncio
import sys
sys.path.insert(0, '/home/daniel/.openclaw/agent_hub')

from client import OpenClawAgent

async def main():
    # Create Basil agent
    basil = OpenClawAgent(
        name="Basil",
        description="Your OpenClaw assistant - helpful, direct, and warm. Running in terminal.",
        capabilities=["general_assistance", "coding", "coordination", "memory", "terminal_access"]
    )
    
    # Connect to hub - need a token
    print("🌿 Basil connecting to Agent Hub...")
    print("Note: Need an invite token to connect.")
    print("Generate one at: http://localhost:8765")
    
    # For now, let's check if we can get a token programmatically
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
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nManual connection:")
        print("1. Visit http://localhost:8765")
        print("2. Click 'Generate Invite Token'")
        print("3. Run: python3 connect_basil.py TOKEN")

if __name__ == "__main__":
    asyncio.run(main())
