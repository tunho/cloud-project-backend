# main.py

# ========== Eventlet Setup (CRITICAL for production with Gunicorn) ==========
# Must be imported and patched BEFORE any other imports
import eventlet
eventlet.monkey_patch()
# =============================================================================

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

# ========= Health Check Endpoints ===========
from health_check import health_bp
app.register_blueprint(health_bp)


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
