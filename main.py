'''# main.py
# import eventlet  # Disabled due to environment constraints
# eventlet.monkey_patch()  # Disabled

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
def get_leaderboard():
    if not FIREBASE_AVAILABLE:
        return jsonify({"error": "Firebase not configured"}), 503
    
    try:
        db = get_db()
        if not db:
            return jsonify({"error": "Database connection failed"}), 500
            
        # money 내림차순 정렬, 상위 20명
        users_ref = db.collection("users")
        query = users_ref.order_by("money", direction=admin_firestore.Query.DESCENDING).limit(20)
        docs = query.stream()
        
        leaderboard = []
        for doc in docs:
            data = doc.to_dict()
            leaderboard.append({
                "uid": doc.id,
                "nickname": data.get("nickname", "Unknown"),
                "major": data.get("major", ""),
                "year": data.get("year", ""),
                "money": data.get("money", 0)
            })
            
        return jsonify(leaderboard)
    except Exception as e:
        print(f"❌ Leaderboard error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("🚀 서버 실행 (http://localhost:5000)")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)'''


# main.py

from flask import Flask, jsonify
from extensions import socketio

# Firebase (import early!)
try:
    from firebase_admin_config import get_db
    from firebase_admin import firestore as admin_firestore
    FIREBASE_AVAILABLE = True
except Exception as e:
    FIREBASE_AVAILABLE = False
    print("⚠️ Firebase Admin load failed:", e)


# --- 이벤트 핸들러 임포트 ---
import general_events
import lobby_events
import game_events
# -------------------------


app = Flask(__name__)
app.config['SECRET_KEY'] = "dev_secret_key"

# SocketIO
socketio.init_app(app, cors_allowed_origins="*")


# ========= Leaderboard API ===========
@app.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    if not FIREBASE_AVAILABLE:
        return jsonify({"error": "Firebase not configured"}), 503
    
    try:
        db = get_db()
        if not db:
            return jsonify({"error": "Database connection failed"}), 500
        
        users_ref = db.collection("users")
        query = users_ref.order_by("money", direction=admin_firestore.Query.DESCENDING).limit(20)
        docs = query.stream()

        leaderboard = []
        for doc in docs:
            d = doc.to_dict()
            leaderboard.append({
                "uid": doc.id,
                "nickname": d.get("nickname", "Unknown"),
                "major": d.get("major", ""),
                "year": d.get("year", ""),
                "money": d.get("money", 0)
            })

        return jsonify(leaderboard)
    except Exception as e:
        print(f"❌ Leaderboard error: {e}")
        return jsonify({"error": str(e)}), 500


# ========== LOCAL TEST MODE ==========
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
