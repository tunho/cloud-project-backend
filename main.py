# main.py
# 🔥 [CRITICAL] Do NOT import gevent or eventlet.
# We are using 'threading' mode to ensure compatibility with Firebase (gRPC).

import os
# 🔥 [FIX] gRPC Stability Settings for Gunicorn/Linux
# Prevent gRPC from trying to handle forking logic (since we lazy load post-fork)
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"
# Force standard polling to avoid epoll deadlocks in some environments
os.environ["GRPC_POLL_STRATEGY"] = "poll"

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

# 🔥 [NEW] Leaderboard API
from flask import jsonify
try:
    from firebase_admin_config import get_db
    from firebase_admin import firestore as admin_firestore
    FIREBASE_AVAILABLE = True
except Exception as e:
    FIREBASE_AVAILABLE = False
    print(f"⚠️ Firebase Admin not available for leaderboard: {e}")

@app.route("/api/leaderboard", methods=["GET"])
@app.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    # 🔥 [FIX] Use subprocess to avoid gRPC hang in Gunicorn
    import subprocess
    import json
    import sys
    
    try:
        # Run the standalone script
        script_path = os.path.join(os.path.dirname(__file__), 'check_leaderboard.py')
        
        # Use the same python interpreter
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=10 # 10 seconds timeout
        )
        
        if result.returncode != 0:
            print(f"❌ Subprocess error: {result.stderr}")
            return jsonify({"error": "Failed to fetch leaderboard"}), 500
            
        # Parse JSON output
        # The script might print other things (like initialization logs), so we need to find the JSON part
        # But our modified script only prints JSON at the end ideally.
        # Let's assume the script output is pure JSON or the last line is JSON.
        output = result.stdout.strip()
        
        # Filter out potential initialization logs if any (simple heuristic: find start of list)
        json_start = output.find('[')
        if json_start != -1:
            output = output[json_start:]
            
        data = json.loads(output)
        return jsonify(data)
        
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout fetching leaderboard"}), 504
    except Exception as e:
        print(f"❌ Leaderboard error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("🚀 서버 실행 (http://localhost:5000)")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)