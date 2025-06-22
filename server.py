import asyncio
import websockets
import json
from collections import defaultdict

connected_clients = set()
vote_queue = []
score = {"red": 0, "blue": 0}

vote_timer_task = None
vote_lock = asyncio.Lock()

# ==== Vote Processing ====
def get_majority_vote(votes):
    counter = defaultdict(int)
    for v in votes:
        key = (v["data"]["side"], v["data"]["point"])
        counter[key] += 1
    for (side, point), count in counter.items():
        if count >= 3:
            return {"side": side, "point": point}
    return None

async def check_and_apply_votes():
    global vote_queue
    decision = get_majority_vote(vote_queue)
    if decision:
        score[decision["side"]] += decision["point"]
        print(f"✅ {decision['side'].upper()} +{decision['point']} (theo đa số phiếu)")
    else:
        print("❌ Không đủ phiếu giống nhau")
    await broadcast_score()
    vote_queue.clear()

async def start_vote_timer():
    try:
        await asyncio.sleep(3)
        async with vote_lock:
            if vote_queue:
                await check_and_apply_votes()
    except asyncio.CancelledError:
        pass

async def handle_vote(data, websocket):
    global vote_timer_task
    referee_id = data["data"]["referee_id"]
    side = data["data"]["side"]
    point = data["data"]["point"]
    
    # Nếu trọng tài này đã vote, không cho vote tiếp trong tình huống này
    if any(v["data"]["referee_id"] == referee_id for v in vote_queue):
        await error_message(websocket, "Bạn đã vote rồi, vui lòng chờ tình huống mới.")
        return

    vote_queue.append(data)
    print(f"📥 Phiếu từ trọng tài {referee_id}: {side.upper()} +{point} (tổng phiếu: {len(vote_queue)})")

    if len(vote_queue) == 5:
        if vote_timer_task:
            vote_timer_task.cancel()
        await check_and_apply_votes()
    else:
        if vote_timer_task:
            vote_timer_task.cancel()
        vote_timer_task = asyncio.create_task(start_vote_timer())

# ==== Broadcasting ====
async def broadcast(message):
    await asyncio.gather(*[
        client.send(json.dumps(message))
        for client in connected_clients if client.open
    ])

async def broadcast_score():
    await broadcast({"type": "score_result", "data": score})

# ✅ Sửa đúng thứ tự tham số
async def error_message(websocket, message):
    await websocket.send(json.dumps({"type": "error", "data": message}))
    
# ==== Control Vote ====
async def handle_control_vote(data):
    # Xử lý điều khiển vote từ trọng tài máy
    side = data["data"]["side"]
    point = data["data"]["point"]
    print(f"📥 Phiếu từ trọng tài máy: {side} +{point} ")
    score[side] += point
    await broadcast_score()

# ==== WebSocket Server ====
async def handle_client(websocket):
    print(f"🔌 Client kết nối: {websocket.remote_address}")
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data["type"] == "vote":
                    await handle_vote(data, websocket) 
                elif data["type"] == "control_vote": 
                    await handle_control_vote(data)    
                elif data["type"] == "control":
                    print(f"📝 Nhận điều khiển từ trọng tài máy: {data['data']}")
                    await broadcast(data)
            except Exception as e:
                print("❌ Lỗi xử lý dữ liệu:", e)
    finally:
        connected_clients.remove(websocket)
        print(f"❌ Client ngắt kết nối: {websocket.remote_address}")

async def main():
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        print("🚀 Server đang chạy tại ws://localhost:8765")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
