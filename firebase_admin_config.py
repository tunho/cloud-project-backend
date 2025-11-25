import firebase_admin
from firebase_admin import credentials, firestore
import os

# 🔥 [FIX] TRUE LAZY LOADING - Don't initialize on import!
_db_client = None

def get_db():
    """Get Firestore database client with lazy initialization"""
    global _db_client
    
    # Return cached client if already initialized
    if _db_client is not None:
        return _db_client
    
    # 🔥 [FIX] Force Disable Firebase to prevent Eventlet/gRPC crash
    print("⚠️ Firebase disabled for server stability.")
    return None

    # Initialize Firebase Admin ONLY when first needed
    # if not firebase_admin._apps:
    #     try:
    #         service_key_path = os.path.join(
    #             os.path.dirname(__file__), 
    #             'cloud-project-backend-firebase-adminsdk-fbsvc-b6e9105306.json'
    #         )
    #         
    #         if os.path.exists(service_key_path):
    #             print("🔥 Firebase initializing (lazy)...")
    #             cred = credentials.Certificate(service_key_path)
    #             firebase_admin.initialize_app(cred)
    #             _db_client = firestore.client()
    #             print("✅ Firebase initialized successfully")
    #         else:
    #             print(f"⚠️ Service account key not found: {service_key_path}")
    #             return None
    #     except Exception as e:
    #         print(f"❌ Firebase initialization failed: {e}")
    #         return None
    # else:
    #     # Already initialized, just get client
    #     _db_client = firestore.client()
    # 
    # return _db_client
