import asyncio
import websockets
import json
from collections import defaultdict

connected_clients = set()
vote_queue = []
score = {"red": 0, "blue": 0}

warn = {"red": 0, "blue": 0}

vote_timer_task = None
vote_lock = asyncio.Lock()

match_state = {
    "current_round": 1,
    "round_time": 120,  # 2 phút mỗi hiệp
    "rest_time": 30,    # 30 giây nghỉ
    "status": "paused",  # paused | playing | resting | done
    "time_left": 120,
    "max_rounds": 3
}
timer_task = None
timer_started = False
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
        await asyncio.sleep(2)
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

    if referee_id == "main_Ref":
        await handle_control_vote(data)
        return  
    
    # Nếu trọng tài này đã vote, không cho vote tiếp trong tình huống này
    if any(v["data"]["referee_id"] == referee_id for v in vote_queue):
        await error_message(websocket, "Bạn đã vote rồi, vui lòng chờ tình huống mới.")
        return

    for client, role in role_mapping.items():
        if role in ("score", "main_Ref"):
            await client.send(json.dumps(data))


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

async def error_message(websocket, message):
    await websocket.send(json.dumps({"type": "error", "data": message}))

async def broadcast_match_state():
    for client, role in role_mapping.items():
        if role in ("score","main_Ref"):
            await client.send(json.dumps({
                "type": "match_state",
                "data": match_state
            }))

async def timer_loop():
    while True:
        await asyncio.sleep(1)
        if match_state["status"] == "playing":
            match_state["time_left"] -= 1
            if match_state["time_left"] <= 0:
                await broadcast({"type": "round_result", "data": {"score_red":score["red"],"score_blue":score["blue"], "round": match_state["current_round"]}})
                if match_state["current_round"] >= match_state["max_rounds"]:
                    match_state["status"] = "done"
                    match_state["time_left"] = 0
                else:
                    match_state["status"] = "resting"
                    match_state["time_left"] = match_state["rest_time"]
                score["red"] = 0
                score["blue"] = 0
                await broadcast({"type": "score_result", "data": score})
        elif match_state["status"] == "resting":
            match_state["time_left"] -= 1
            if match_state["time_left"] <= 0:
                match_state["current_round"] += 1
                if match_state["current_round"] > match_state["max_rounds"]:
                    match_state["status"] = "done"
                    match_state["time_left"] = 0
                else:
                    match_state["status"] = "paused"
                    match_state["time_left"] = match_state["round_time"]
        await broadcast_match_state()

# ==== Control Vote ====
async def handle_control_vote(data):
    # Xử lý điều khiển vote từ trọng tài máy
    side = data["data"]["side"]
    point = data["data"]["point"]
    print(f"📥 Phiếu từ trọng tài máy: {side} +{point} ")
    score[side] += point
    await broadcast_score()

async def handle_warn(data,client):
    side = data["data"]["side"]
    if side in warn:  # nếu side tồn tại trong dict
        warn[side] += 1
    await client.send(json.dumps({"type": "warn", "data": {"side": side, "count": warn[side]}}))

# ==== WebSocket Server ====
connected_clients = set()
role_mapping = {}  # websocket -> role

async def handle_client(websocket):
    print(f"🔌 Client kết nối: {websocket.remote_address}")
    connected_clients.add(websocket)

    try:
        # Chờ nhận message định danh đầu tiên
        identify_msg = await websocket.recv()
        try:
            identify_data = json.loads(identify_msg)
            if identify_data.get("type") == "identify":
                role = identify_data.get("role")
                role_mapping[websocket] = role
                print(f"✅ Client xác định vai trò: {role}")
        except Exception as e:
            print("❌ Không thể phân tích định danh:", e)

        # Nhận các message sau đó
        async for message in websocket:
            try:
                global timer_task, timer_started
                data = json.loads(message)
                if data["type"] == "vote":
                    await handle_vote(data, websocket)
                elif data["type"] == "control":
                    cmd = data["data"].get("command")
                    sender_role = role_mapping.get(websocket)

                    if sender_role in ["score", "main_Ref"]:
                        if cmd == "start" and match_state["status"] in ["paused", "resting"]:
                            match_state["status"] = "playing"
                        elif cmd == "pause" and match_state["status"] == "playing":
                            match_state["status"] = "paused"
                        elif cmd in ( "reset"):
                            if timer_task:
                                timer_task.cancel()
                                timer_task = None
                                timer_started = False
                            match_state["current_round"] = 1
                            match_state["status"] = "paused"
                            match_state["time_left"] = match_state["round_time"]
                            score["red"] = 0
                            score["blue"] = 0
                            await broadcast({"type": "score_result", "data": score})
                            warn["red"] = 0
                            warn["blue"]: 0
                        elif cmd == "end":
                            match_state["status"] = "paused"
                            await broadcast({"type": "round_result", "data": {"score_red":score["red"],"score_blue":score["blue"], "round": match_state["current_round"]}})
                            if( match_state["current_round"] >= match_state["max_rounds"]):
                                match_state["status"] = "done"
                                match_state["time_left"] = 0
                            else:
                                match_state["status"] = "resting"
                                match_state["time_left"] = match_state["rest_time"]
                                match_state["current_round"] += 1
                            score["red"] = 0
                            score["blue"] = 0
                            await broadcast({"type": "score_result", "data": score})
                        await broadcast_match_state()
                elif data["type"] == "send_info":
                    match_state["max_rounds"] = int(data["data"].get("round", match_state["max_rounds"]))
                    match_state["round_time"] = int(data["data"].get("time", match_state["round_time"]))
                    match_state["time_left"] = int(data["data"].get("time", match_state["time_left"]))
                    # Gửi chỉ cho client có role = score
                    for client, role in role_mapping.items():
                        if role == "score":
                            await client.send(json.dumps(data))
                        # Nếu chưa chạy timer thì khởi động
                    if not timer_started:
                        timer_task = asyncio.create_task(timer_loop())
                        timer_started = True
                elif data["type"] == "warn":
                    for client, role in role_mapping.items():
                        if role == "score":
                            await handle_warn(data, client)
            except Exception as e:
                print("❌ Lỗi xử lý dữ liệu:", e)

    finally:
        connected_clients.remove(websocket)
        role_mapping.pop(websocket, None)
        print(f"❌ Client ngắt kết nối: {websocket.remote_address}")


async def main():
    server = await websockets.serve(handle_client, "0.0.0.0", 8765)
    print("🚀 Server đang chạy tại ws://localhost:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
