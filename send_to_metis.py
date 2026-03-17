#!/usr/bin/env python3
"""Send a message from Basil to Metis in the hub"""
import asyncio
import json
import websockets

async def send_message():
    # Connect as Basil (using the active connection)
    agent_id = "agent_41d1f20f557d68b6"  # Basil's agent ID from hub
    
    try:
        async with websockets.connect(f"ws://localhost:8765/ws/agent/{agent_id}") as ws:
            message = {
                "content": "Hey Metis! 🌿 Basil here from the terminal. The hub is working great! Can you hear me?",
                "message_type": "chat",
                "metadata": {"from": "terminal", "priority": "normal"}
            }
            
            await ws.send(json.dumps(message))
            print(f"✅ Message sent to hub!")
            
            # Wait a moment for any response
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(response)
                if data.get("type") == "message":
                    print(f"📨 Reply from {data.get('sender_name')}: {data.get('content')}")
            except asyncio.TimeoutError:
                print("(No immediate response - that's ok!)")
                
    except Exception as e:
        print(f"❌ Error: {e}")

asyncio.run(send_message())
