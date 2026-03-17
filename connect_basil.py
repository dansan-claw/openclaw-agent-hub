#!/usr/bin/env python3
"""Basil connecting to Agent Hub"""
import asyncio
import sys
sys.path.insert(0, '/home/daniel/.openclaw/agent_hub')

from client import OpenClawAgent

async def main():
    agent = OpenClawAgent(
        name="Basil",
        description="Your OpenClaw assistant - helpful, direct, and warm",
        capabilities=["general_assistance", "coding", "coordination", "memory"]
    )
    
    # Connect to hub
    if await agent.connect("http://localhost:8765", "JKviwJskBw0WkSxiUCJUPA"):
        print("🌿 Basil is now in the Agent Hub!")
        print("Listening for messages...")
        await agent.run()
    else:
        print("❌ Failed to connect")

if __name__ == "__main__":
    asyncio.run(main())
