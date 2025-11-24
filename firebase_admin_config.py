import firebase_admin
from firebase_admin import credentials, firestore
import os

# Initialize Firebase Admin (only once)
if not firebase_admin._apps:
    # Try to load service account key
    # 🔥 [UPDATED] Using the actual uploaded filename
    service_key_path = os.path.join(os.path.dirname(__file__), 'cloud-project-backend-firebase-adminsdk-fbsvc-b6e9105306.json')
    
    if os.path.exists(service_key_path):
        cred = credentials.Certificate(service_key_path)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin initialized successfully")
    else:import firebase_admin
from firebase_admin import credentials, firestore
import os

# 🔥 절대경로로 변경 (EC2 배포환경에서는 절대경로가 안정적)
SERVICE_KEY_PATH = "/home/ubuntu/projects/backend/cloud-project-backend-firebase-adminsdk-fbsvc-b6e9105306.json"

# Firebase 초기화 (전역 1회)
if not firebase_admin._apps:
    if os.path.exists(SERVICE_KEY_PATH):
        cred = credentials.Certificate(SERVICE_KEY_PATH)
        firebase_admin.initialize_app(cred)
        print("🔥 Firebase Admin initialized once (global)")
    else:
        print("⚠️ Firebase service key NOT FOUND")
        print("Expected path:", SERVICE_KEY_PATH)


def get_db():
    """Return Firestore client (or None if not initialized)"""
    if firebase_admin._apps:
        return firestore.client()
    return None
        print("⚠️ Service account key not found. Please add service account key")
        print(f"   Expected path: {service_key_path}")

# Firestore client
def get_db():
    """Get Firestore database client"""
    if firebase_admin._apps:
        return firestore.client()
    return None


'''import firebase_admin
from firebase_admin import credentials, firestore
import os

# Initialize Firebase Admin (only once)
if not firebase_admin._apps:
    # Try to load service account key
    # 🔥 [UPDATED] Using the actual uploaded filename
    service_key_path = os.path.join(os.path.dirname(__file__), 'cloud-project-backend-firebase-adminsdk-fbsvc-b6e9105306.json')
    
    if os.path.exists(service_key_path):
        cred = credentials.Certificate(service_key_path)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin initialized successfully")
    else:
        print("⚠️ Service account key not found. Please add service account key")
        print(f"   Expected path: {service_key_path}")

# Firestore client
def get_db():
    """Get Firestore database client"""
    if firebase_admin._apps:
        return firestore.client()
    return None
'''