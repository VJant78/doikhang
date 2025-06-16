import asyncio
import websockets
import json
from datetime import datetime
from collections import Counter

connected_clients = set()
message_inque = []
temp_score = {"blue": 0, "red": 0}
score = {"blue": 0, "red": 0}
score_result_payload = {
    "type": "score_result"
}
message_payload = {
    "type": "player_message"
}
message_error = {
    "type": "error"
}
def cal_temp_score(message_inque):
    # Đặt lại giá trị temp_score
    for key in temp_score:
        temp_score[key] = 0

    for team in temp_score.keys():
        # Lọc danh sách score của team
        team_scores = [item[2] for item in message_inque if item[1] == team]

        # Đếm số lần xuất hiện
        score_counts = Counter(team_scores)

        # Tìm các score bị trùng
        duplicate_scores = [s for s, count in score_counts.items() if count >= 2]

        if duplicate_scores:
            max_duplicate_score = max(duplicate_scores)
            temp_score[team] = max_duplicate_score
            print(f"✅ Team {team}: score trùng lớn nhất là {max_duplicate_score}")
        else:
            print(f"⚠️ Team {team}: không có score nào bị trùng.")

    print(f"\n📊 temp_score hiện tại: {temp_score}")

def write_log(text): 
    with open("log.txt", "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {text}\n")

def name_exists(name, message_inque):
    return any(item[0] == name for item in message_inque)

async def echo(websocket):
    client_ip, client_port = websocket.remote_address
    print(f"📡 Client kết nối từ {client_ip}:{client_port}")
    connected_clients.add(websocket)

    try:
        async for message in websocket:
            try:
                # Parse message JSON
                data = json.loads(message)
                name, team, point, datime = data
                print(f"📝 {name} - {team} - {point} điểm - {datime}")

                # Kiểm tra name đã tồn tại chưa
                if name_exists(name, message_inque):
                    message_error["data"] = "WAIT"
                    await websocket.send(json.dumps(message_error))
                    continue

                # Thêm vào hàng đợi
                message_inque.append(data)

                # Ghi log nếu cần
                log_text = f"{client_ip}:{client_port} -> {message}"
                # write_log(log_text)  # Bật lại nếu cần log

                # Khi đủ 4 người thì tính điểm
                if len(message_inque) == 4:
                    cal_temp_score(message_inque)
                    score["blue"] += temp_score["blue"]
                    score["red"] += temp_score["red"]

                    print(f"✅ Tổng điểm hiện tại: {score}")

                    # Gửi kết quả về cho tất cả client
                    for i in message_inque:
                        message_payload["data"] = f"{i[0]}: {i[1]} ghi {i[2]} điểm lúc {i[3]}"
                        await asyncio.gather(*[
                            client.send(json.dumps(message_payload))
                            for client in connected_clients if client.open
                        ])

                    # Gửi tổng điểm cuối lượt
                    score_result_payload["data"] = {
                        "blue": score["blue"],
                        "red": score["red"]
                    }
                    await asyncio.gather(*[
                        client.send(json.dumps(score_result_payload))
                        for client in connected_clients if client.open
                    ])

                    # Dọn dữ liệu
                    message_inque.clear()
                    for key in temp_score:
                        temp_score[key] = 0

            except json.JSONDecodeError:
                print("❌ Lỗi: Message không phải JSON hợp lệ")
    finally:
        connected_clients.remove(websocket)

async def main():
    async with websockets.serve(echo, "0.0.0.0", 8765):
        print("🚀 WebSocket server đang chạy tại ws://0.0.0.0:8765")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
