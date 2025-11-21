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
    else:
        print("⚠️ Service account key not found. Please add service account key")
        print(f"   Expected path: {service_key_path}")

# Firestore client
def get_db():
    """Get Firestore database client"""
    if firebase_admin._apps:
        return firestore.client()
    return None
