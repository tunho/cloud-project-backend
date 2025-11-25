# extensions.py
from flask_socketio import SocketIO

# SocketIO 객체를 생성
# 🔥 [FIX] Force threading mode to ensure compatibility with threading.Timer (no gevent)
socketio = SocketIO(async_mode='threading')