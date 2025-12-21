import boto3
import os
import json
import subprocess
import mimetypes

# Configuration
FRONTEND_DIR = '../jbnu-game-client'
DIST_DIR = os.path.join(FRONTEND_DIR, 'dist')
CONFIG_FILE = 's3_config.json'

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("❌ Configuration file not found. Please run 'aws_s3_setup.py' first.")
        return None
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def build_frontend():
    print("🔨 Building Frontend (npm run build)...")
    try:
        subprocess.run(['npm', 'run', 'build'], cwd=FRONTEND_DIR, check=True)
        print("✅ Build Successful!")
        return True
    except subprocess.CalledProcessError:
        print("❌ Build Failed!")
        return False
    except FileNotFoundError:
        print("❌ npm not found. Is Node.js installed?")
        return False

def upload_to_s3(bucket_name, region):
    s3 = boto3.client('s3', region_name=region)
    print(f"📤 Uploading to S3 Bucket: {bucket_name}...")

    for root, dirs, files in os.walk(DIST_DIR):
        for file in files:
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, DIST_DIR)
            s3_path = relative_path.replace("\\", "/") # Ensure forward slashes

            # Guess MIME type
            content_type, _ = mimetypes.guess_type(local_path)
            if not content_type:
                content_type = 'application/octet-stream'
            
            print(f"   - Uploading: {s3_path} ({content_type})")
            s3.upload_file(
                local_path, 
                bucket_name, 
                s3_path, 
                ExtraArgs={'ContentType': content_type}
            )

    print("✅ Upload Complete!")

if __name__ == "__main__":
    print("🚀 Starting Frontend Deployment...")
    
    config = load_config()
    if config:
        if build_frontend():
            upload_to_s3(config['bucket_name'], config['region'])
            print(f"\n✨ Deployment Complete!")
            print(f"🌍 Access your Game here: {config['url']}")
