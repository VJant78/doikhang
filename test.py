import asyncio
import json
import websockets

clients = set()

match_state = {
    "current_round": 1,
    "round_time": 10,  # 2 phút mỗi hiệp
    "rest_time": 5,    # 30 giây nghỉ
    "status": "paused",  # paused | playing | resting | done
    "time_left": 10,
    "max_rounds": 3
}

async def broadcast():
    if clients:
        msg = json.dumps(match_state)
        await asyncio.gather(*(client.send(msg) for client in clients))

async def timer_loop():
    while True:
        await asyncio.sleep(1)

        if match_state["status"] == "playing":
            match_state["time_left"] -= 1
            if match_state["time_left"] <= 0:
                # Hết hiệp -> nghỉ giữa hiệp
                match_state["status"] = "resting"
                match_state["time_left"] = match_state["rest_time"]

        elif match_state["status"] == "resting":
            match_state["time_left"] -= 1
            if match_state["time_left"] <= 0:
                # Nghỉ xong -> tăng hiệp, chờ bắt đầu thủ công
                match_state["current_round"] += 1
                if match_state["current_round"] > match_state["max_rounds"]:
                    match_state["status"] = "done"
                    match_state["time_left"] = 0
                else:
                    match_state["status"] = "paused"
                    match_state["time_left"] = match_state["round_time"]

        await broadcast()

async def handle_client(websocket):
    clients.add(websocket)
    await websocket.send(json.dumps(match_state))
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("type") == "control":
                cmd = data.get("command")
                if cmd == "start":
                    if match_state["status"] in ["paused", "resting"] and match_state["time_left"] > 0:
                        match_state["status"] = "playing"
                elif cmd == "pause":
                    if match_state["status"] == "playing":
                        match_state["status"] = "paused"
                elif cmd == "reset":
                    match_state["current_round"] = 1
                    match_state["status"] = "paused"
                    match_state["time_left"] = match_state["round_time"]
                await broadcast()
    finally:
        clients.remove(websocket)

async def main():
    print("⚡ Server đang chạy tại ws://localhost:8000")
    async with websockets.serve(handle_client, "localhost", 8000):
        await timer_loop()

if __name__ == "__main__":
    asyncio.run(main())
