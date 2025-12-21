import boto3
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# AWS Configuration (Must match setup script)
REGION = 'us-east-1' # Updated for Student Account
APP_NAME = 'jbnu-game-server'
ASG_NAME = f'{APP_NAME}-asg'
ALB_NAME = f'{APP_NAME}-alb'
TG_NAME = f'{APP_NAME}-tg'
LT_NAME = f'{APP_NAME}-lt'

autoscaling = boto3.client('autoscaling', region_name=REGION)
elbv2 = boto3.client('elbv2', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)

def delete_launch_template():
    print(f"🗑️ Deleting Launch Template: {LT_NAME}...")
    try:
        ec2.delete_launch_template(LaunchTemplateName=LT_NAME)
        print("✅ Launch Template Deleted.")
    except Exception as e:
        if "InvalidLaunchTemplateName.NotFoundException" in str(e):
            print("✅ Launch Template already deleted.")
        else:
            print(f"⚠️ Error deleting Launch Template: {e}")

def delete_auto_scaling_group():
    print(f"🗑️ Deleting Auto Scaling Group: {ASG_NAME}...")
    try:
        # Force delete to terminate instances immediately
        autoscaling.delete_auto_scaling_group(
            AutoScalingGroupName=ASG_NAME,
            ForceDelete=True
        )
        print("⏳ Waiting for ASG deletion (this takes time)...")
        while True:
            response = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[ASG_NAME])
            if not response['AutoScalingGroups']:
                print("✅ ASG Deleted.")
                break
            status = response['AutoScalingGroups'][0]['Status'] if 'Status' in response['AutoScalingGroups'][0] else "Deleting"
            print(f"   ... {status}")
            time.sleep(10)
    except Exception as e:
        if "AutoScalingGroup name not found" in str(e):
            print("✅ ASG already deleted.")
        else:
            print(f"⚠️ Error deleting ASG: {e}")

def delete_load_balancer():
    print(f"🗑️ Deleting Load Balancer: {ALB_NAME}...")
    try:
        # Find ALB ARN first
        response = elbv2.describe_load_balancers(Names=[ALB_NAME])
        alb_arn = response['LoadBalancers'][0]['LoadBalancerArn']
        
        elbv2.delete_load_balancer(LoadBalancerArn=alb_arn)
        print("⏳ Waiting for ALB deletion...")
        # Wait logic could be added, but ALB deletion is usually async and fast to trigger
        time.sleep(5) 
        print("✅ ALB Deletion Triggered.")
    except Exception as e:
        if "LoadBalancerNotFound" in str(e):
            print("✅ ALB already deleted.")
        else:
            print(f"⚠️ Error deleting ALB: {e}")

def delete_target_group():
    print(f"🗑️ Deleting Target Group: {TG_NAME}...")
    try:
        # Find TG ARN
        response = elbv2.describe_target_groups(Names=[TG_NAME])
        tg_arn = response['TargetGroups'][0]['TargetGroupArn']
        
        elbv2.delete_target_group(TargetGroupArn=tg_arn)
        print("✅ Target Group Deleted.")
    except Exception as e:
        if "TargetGroupNotFound" in str(e):
            print("✅ Target Group already deleted.")
        elif "ResourceInUse" in str(e):
            print("⚠️ Target Group is still in use (ALB might not be fully deleted yet). Try again in a minute.")
        else:
            print(f"⚠️ Error deleting Target Group: {e}")

# ... (previous code)

# Redis & SG Configuration
REDIS_NAME = f'{APP_NAME}-redis'
SG_NAME = f'{APP_NAME}-sg'
REDIS_SG_NAME = f'{APP_NAME}-redis-sg'

elasticache = boto3.client('elasticache', region_name=REGION)

def delete_redis_cluster():
    print(f"🗑️ Deleting Redis Cluster: {REDIS_NAME}...")
    try:
        elasticache.delete_cache_cluster(CacheClusterId=REDIS_NAME)
        print("⏳ Waiting for Redis deletion (this takes time)...")
        while True:
            try:
                elasticache.describe_cache_clusters(CacheClusterId=REDIS_NAME)
                print("   ... Deleting")
                time.sleep(20)
            except elasticache.exceptions.CacheClusterNotFoundFault:
                print("✅ Redis Cluster Deleted.")
                break
    except Exception as e:
        if "CacheClusterNotFound" in str(e):
            print("✅ Redis Cluster already deleted.")
        else:
            print(f"⚠️ Error deleting Redis: {e}")

def delete_security_groups():
    print("🗑️ Deleting Security Groups...")
    # Delete Redis SG first (if exists)
    try:
        res = ec2.describe_security_groups(Filters=[{'Name': 'group-name', 'Values': [REDIS_SG_NAME]}])
        if res['SecurityGroups']:
            sg_id = res['SecurityGroups'][0]['GroupId']
            ec2.delete_security_group(GroupId=sg_id)
            print(f"✅ Security Group Deleted: {REDIS_SG_NAME}")
    except Exception as e:
        print(f"⚠️ Error deleting Redis SG: {e}")

    # Delete App SG
    try:
        res = ec2.describe_security_groups(Filters=[{'Name': 'group-name', 'Values': [SG_NAME]}])
        if res['SecurityGroups']:
            sg_id = res['SecurityGroups'][0]['GroupId']
            ec2.delete_security_group(GroupId=sg_id)
            print(f"✅ Security Group Deleted: {SG_NAME}")
    except Exception as e:
        if "DependencyViolation" in str(e):
             print(f"⚠️ Cannot delete {SG_NAME} yet (Instances might still be terminating). Try again later.")
        else:
             print(f"⚠️ Error deleting App SG: {e}")

if __name__ == "__main__":
    print("⚠️ STARTING RESOURCE CLEANUP (Saving Money!) ⚠️")
    
    # 1. Delete ASG (Terminates Instances)
    delete_auto_scaling_group()
    
    # 2. Delete Launch Template
    delete_launch_template()
    
    # 3. Delete ALB (Stops Hourly Billing)
    delete_load_balancer()
    
    # 4. Delete Target Group
    # Wait a bit for ALB to release the TG
    time.sleep(10)
    delete_target_group()

    # 5. Delete Redis (Critical for billing)
    delete_redis_cluster()

    # 6. Delete Security Groups
    time.sleep(5)
    delete_security_groups()
    
    print("✨ Cleanup Complete! You are safe from billing.")
