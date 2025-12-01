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

# 🔥 [NEW] AWS ALB Health Check Endpoint
@app.route("/health")
def health_check():
    return "OK", 200

# 🔥 [NEW] Leaderboard API
from flask import jsonify
try:
    from firebase_admin_config import get_db
    from firebase_admin import firestore as admin_firestore
    FIREBASE_AVAILABLE = True
except Exception as e:
    FIREBASE_AVAILABLE = False
    print(f"⚠️ Firebase Admin not available for leaderboard: {e}")

# 🔥 [REMOVED] Leaderboard API - Migrated to Frontend Client SDK
# The frontend now fetches leaderboard data directly from Firestore using the Client SDK.
# This avoids gRPC conflicts with the Admin SDK in the Gunicorn environment.

if __name__ == "__main__":
    print("🚀 서버 실행 (http://localhost:5000)")
    # 🔥 [FIX] allow_unsafe_werkzeug=True to prevent "write() before start_response" error
    # 🔥 [FIX] use_reloader=False to prevent thread conflict with Werkzeug
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True, use_reloader=False)