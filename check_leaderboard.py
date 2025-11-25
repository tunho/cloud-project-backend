import firebase_admin
from firebase_admin import credentials, firestore
import os
import sys

def check_ranking():
    # 1. Firebase 초기화
    try:
        # 현재 디렉토리의 서비스 키 파일 찾기
        current_dir = os.path.dirname(os.path.abspath(__file__))
        key_file = 'cloud-project-backend-firebase-adminsdk-fbsvc-b6e9105306.json'
        service_key_path = os.path.join(current_dir, key_file)
        
        if not os.path.exists(service_key_path):
            print(f"❌ Error: Service key file not found at {service_key_path}")
            return

        # 이미 초기화되어 있는지 확인
        if not firebase_admin._apps:
            cred = credentials.Certificate(service_key_path)
            firebase_admin.initialize_app(cred)
            # print("✅ Firebase initialized successfully.")
        
        db = firestore.client()
        
    except Exception as e:
        print(f"❌ Firebase initialization failed: {e}")
        return

    # 2. 랭킹 조회
    try:
        users_ref = db.collection("users")
        # money 내림차순 정렬
        query = users_ref.order_by("money", direction=firestore.Query.DESCENDING).limit(20)
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

        import json
        print(json.dumps(leaderboard))

    except Exception as e:
        import json
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    check_ranking()
