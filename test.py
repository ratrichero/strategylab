import asyncio
import websockets
import json
import traceback

async def test():
    try:
        print('--- BẮT ĐẦU KẾT NỐI ---')
        ws = await websockets.connect(
            'wss://fstream.binance.com/ws/!markPrice@arr@1s',
            ping_interval=10
        )
        print('--- KẾT NỐI THÀNH CÔNG! ĐANG ĐỢI DỮ LIỆU... ---')
        
        # Đợi message
        msg = await asyncio.wait_for(ws.recv(), timeout=15)
        print(f'Đã nhận tin nhắn, độ dài: {len(msg)}')
        
        data = json.loads(msg)
        print(f'Dữ liệu nhận được là: {type(data)}')
        print('--- THÀNH CÔNG ---')
        await ws.close()
        
    except Exception:
        print('--- XẢY RA LỖI ---')
        traceback.print_exc() # In chi tiết lỗi ra màn hình

if __name__ == "__main__":
    asyncio.run(test())