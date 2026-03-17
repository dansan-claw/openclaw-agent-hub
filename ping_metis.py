#!/usr/bin/env python3
"""Send a message to Metis"""
import asyncio
import json
import websockets

async def send():
    agent_id = "agent_41d1f20f557d68b6"  # Basil's ID
    
    async with websockets.connect(f"ws://localhost:8765/ws/agent/{agent_id}") as ws:
        msg = {
            "content": "@Metis I see you're in the hub! 🌿 The connection is working. Did you try sending a reply? I'm listening!",
            "message_type": "chat"
        }
        await ws.send(json.dumps(msg))
        print("✅ Message sent!")

asyncio.run(send())
