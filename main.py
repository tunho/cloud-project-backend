# main.py
from flask import Flask
from extensions import socketio

# --- 이벤트 핸들러 임포트 ---
# (중요) 이 파일들이 임포트되면서 정의된 핸들러(@socketio.on...)가 등록됩니다.
import general_events
import lobby_events
import game_events
# -------------------------

app = Flask(__name__)
# TODO: 실제 배포 시에는 강력한 시크릿 키로 변경하세요
app.config['SECRET_KEY'] = 'dev_secret_key' 

# socketio 객체에 app을 연결
socketio.init_app(app, cors_allowed_origins="*")

if __name__ == "__main__":
    print("🚀 서버 실행 (http://localhost:5000)")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)