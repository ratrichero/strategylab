import asyncio
import websockets
import json

async def test():
    url = 'wss://fstream.binance.com/ws/!markPrice@arr@1s'
    print(f'Connecting to {url}...')
    async with websockets.connect(url) as ws:
        print('Connected!')
        msg = await ws.recv()
        data = json.loads(msg)
        print(f'Received {len(data)} symbols')

asyncio.run(test())