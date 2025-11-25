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
            print("✅ Firebase initialized successfully.")
        
        db = firestore.client()
        
    except Exception as e:
        print(f"❌ Firebase initialization failed: {e}")
        return

    # 2. 랭킹 조회
    try:
        print("\n🏆 Fetching Leaderboard (Top 20)...")
        print("-" * 50)
        print(f"{'Rank':<6} {'Nickname':<20} {'Major':<15} {'Money':>10}")
        print("-" * 50)

        users_ref = db.collection("users")
        # money 내림차순 정렬
        query = users_ref.order_by("money", direction=firestore.Query.DESCENDING).limit(20)
        docs = query.stream()

        count = 0
        for i, doc in enumerate(docs):
            data = doc.to_dict()
            nickname = data.get("nickname", "Unknown")
            major = data.get("major", "-")
            money = data.get("money", 0)
            
            print(f"{i+1:<6} {nickname:<20} {major:<15} {money:>10,}")
            count += 1

        if count == 0:
            print("No users found.")
            
        print("-" * 50)

    except Exception as e:
        print(f"❌ Error fetching leaderboard: {e}")

if __name__ == "__main__":
    check_ranking()
