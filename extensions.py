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
socketio = SocketIO(async_mode='threading')