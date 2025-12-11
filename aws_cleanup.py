import boto3
import time

# AWS Configuration (Must match setup script)
REGION = 'ap-northeast-2' # or 'us-east-1' for Student Account
APP_NAME = 'davinci-game-server'
ASG_NAME = f'{APP_NAME}-asg'
ALB_NAME = f'{APP_NAME}-alb'
TG_NAME = f'{APP_NAME}-tg'

autoscaling = boto3.client('autoscaling', region_name=REGION)
elbv2 = boto3.client('elbv2', region_name=REGION)

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

if __name__ == "__main__":
    print("⚠️ STARTING RESOURCE CLEANUP (Saving Money!) ⚠️")
    
    # 1. Delete ASG (Terminates Instances)
    delete_auto_scaling_group()
    
    # 2. Delete ALB (Stops Hourly Billing)
    delete_load_balancer()
    
    # 3. Delete Target Group
    # Wait a bit for ALB to release the TG
    time.sleep(10)
    delete_target_group()
    
    print("✨ Cleanup Complete! You are safe from billing.")
