import boto3
import os
import json
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv('REGION', 'us-east-1')
APP_NAME = 'jbnu-game-client' # Different from server
BUCKET_NAME = f"{APP_NAME}-{int(os.path.getmtime(__file__))}" # Unique name

s3 = boto3.client('s3', region_name=REGION)

def create_bucket():
    print(f"📦 Creating S3 Bucket: {BUCKET_NAME}...")
    try:
        if REGION == 'us-east-1':
            s3.create_bucket(Bucket=BUCKET_NAME)
        else:
            s3.create_bucket(
                Bucket=BUCKET_NAME,
                CreateBucketConfiguration={'LocationConstraint': REGION}
            )
        print(f"✅ Bucket Created: {BUCKET_NAME}")
        return BUCKET_NAME
    except ClientError as e:
        print(f"❌ Error creating bucket: {e}")
        return None

def configure_static_website(bucket_name):
    print("🌐 Configuring Static Website Hosting...")
    try:
        s3.put_bucket_website(
            Bucket=bucket_name,
            WebsiteConfiguration={
                'ErrorDocument': {'Key': 'index.html'},
                'IndexDocument': {'Suffix': 'index.html'},
            }
        )
        print("✅ Static Website Hosting Enabled")
    except Exception as e:
        print(f"❌ Error configuring website: {e}")

def disable_block_public_access(bucket_name):
    print("🔓 Disabling Block Public Access...")
    try:
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )
        print("✅ Public Access Allowed")
    except Exception as e:
        print(f"❌ Error disabling public access block: {e}")

def add_bucket_policy(bucket_name):
    print("📜 Adding Bucket Policy (Public Read)...")
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*"
            }
        ]
    }
    try:
        s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(bucket_policy))
        print("✅ Bucket Policy Applied")
    except Exception as e:
        print(f"❌ Error adding bucket policy: {e}")

if __name__ == "__main__":
    print("🚀 Starting S3 Deployment Setup...")
    
    bucket_name = create_bucket()
    if bucket_name:
        disable_block_public_access(bucket_name)
        add_bucket_policy(bucket_name)
        configure_static_website(bucket_name)
        
        website_url = f"http://{bucket_name}.s3-website-{REGION}.amazonaws.com"
        print(f"\n✨ S3 Setup Complete!")
        print(f"🌍 Website URL: {website_url}")
        
        # Save Bucket Name for Deploy Script
        config = {'bucket_name': bucket_name, 'region': REGION, 'url': website_url}
        with open('s3_config.json', 'w') as f:
            json.dump(config, f)
        print("💾 Saved configuration to s3_config.json")
        
        print(f"\n⚠️ NEXT STEP: Run 'python3 aws_s3_deploy.py' to build and upload the frontend.")
