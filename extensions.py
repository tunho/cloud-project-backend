# extensions.py
from flask_socketio import SocketIO
try:
    from firebase_admin_config import get_db
    FIREBASE_AVAILABLE = True
except ImportError:
    def get_db(): return None
    FIREBASE_AVAILABLE = False

# SocketIO 객체를 생성
# 🔥 [FIX] Force threading mode to ensure compatibility with threading.Timer (no gevent)
# 🔥 [NEW] Redis Message Queue Support for Auto Scaling
import os
redis_url = os.environ.get('REDIS_URL')
if redis_url:
    print(f"🚀 Using Redis Message Queue: {redis_url}")
    socketio = SocketIO(async_mode='threading', message_queue=redis_url)
else:
    print("⚠️ No REDIS_URL found. Using in-memory mode (Not suitable for multi-instance).")
    socketio = SocketIO(async_mode='threading')