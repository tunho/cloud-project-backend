import boto3
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# AWS Configuration
REGION = 'ap-northeast-2'  # Seoul Region
AMI_ID = 'ami-0c9c942bd7bf113a2'  # Ubuntu 22.04 LTS (Example for ap-northeast-2, change as needed)
INSTANCE_TYPE = 't3.micro'
KEY_NAME = 'my-key-pair'  # Change to your key pair name
VPC_ID = 'vpc-xxxxxxx'    # Change to your VPC ID
SUBNET_IDS = ['subnet-xxxxxxx', 'subnet-yyyyyyy'] # Change to your Subnet IDs
SECURITY_GROUP_ID = 'sg-xxxxxxx' # Change to your Security Group ID

# Resource Names
APP_NAME = 'davinci-game-server'
LT_NAME = f'{APP_NAME}-lt'
TG_NAME = f'{APP_NAME}-tg'
ALB_NAME = f'{APP_NAME}-alb'
ASG_NAME = f'{APP_NAME}-asg'

ec2 = boto3.client('ec2', region_name=REGION)
elbv2 = boto3.client('elbv2', region_name=REGION)
autoscaling = boto3.client('autoscaling', region_name=REGION)

def create_launch_template():
    print(f"🚀 Creating Launch Template: {LT_NAME}...")
    
    user_data_script = """#!/bin/bash
    apt-get update
    apt-get install -y python3-pip git
    git clone https://github.com/tunho/cloud-project-backend.git /home/ubuntu/app
    cd /home/ubuntu/app
    pip3 install -r requirements.txt
    
    # Set Environment Variables (Example)
    echo "export REDIS_URL=redis://my-redis-endpoint:6379" >> /etc/profile
    
    # Run Gunicorn
    gunicorn -k gevent -w 1 --threads 100 -b 0.0.0.0:5000 main:app
    """
    
    # Encode User Data
    import base64
    user_data_encoded = base64.b64encode(user_data_script.encode()).decode()

    try:
        response = ec2.create_launch_template(
            LaunchTemplateName=LT_NAME,
            LaunchTemplateData={
                'ImageId': AMI_ID,
                'InstanceType': INSTANCE_TYPE,
                'KeyName': KEY_NAME,
                'UserData': user_data_encoded,
                'SecurityGroupIds': [SECURITY_GROUP_ID],
                'TagSpecifications': [{
                    'ResourceType': 'instance',
                    'Tags': [{'Key': 'Name', 'Value': f'{APP_NAME}-instance'}]
                }]
            }
        )
        print(f"✅ Launch Template Created: {response['LaunchTemplate']['LaunchTemplateId']}")
        return response['LaunchTemplate']['LaunchTemplateId']
    except Exception as e:
        print(f"⚠️ Error creating Launch Template: {e}")
        return None

def create_target_group():
    print(f"🎯 Creating Target Group: {TG_NAME}...")
    try:
        response = elbv2.create_target_group(
            Name=TG_NAME,
            Protocol='HTTP',
            Port=5000,
            VpcId=VPC_ID,
            HealthCheckProtocol='HTTP',
            HealthCheckPort='5000',
            HealthCheckPath='/health', # Ensure /health endpoint exists in Flask
            TargetType='instance'
        )
        tg_arn = response['TargetGroups'][0]['TargetGroupArn']
        
        # Enable Sticky Sessions (Critical for Socket.IO)
        elbv2.modify_target_group_attributes(
            TargetGroupArn=tg_arn,
            Attributes=[
                {'Key': 'stickiness.enabled', 'Value': 'true'},
                {'Key': 'stickiness.type', 'Value': 'lb_cookie'},
                {'Key': 'stickiness.lb_cookie.duration_seconds', 'Value': '86400'} # 1 Day
            ]
        )
        print(f"✅ Target Group Created with Sticky Sessions: {tg_arn}")
        return tg_arn
    except Exception as e:
        print(f"⚠️ Error creating Target Group: {e}")
        return None

def create_load_balancer(tg_arn):
    print(f"⚖️ Creating Application Load Balancer: {ALB_NAME}...")
    try:
        response = elbv2.create_load_balancer(
            Name=ALB_NAME,
            Subnets=SUBNET_IDS,
            SecurityGroups=[SECURITY_GROUP_ID],
            Scheme='internet-facing',
            Type='application',
            IpAddressType='ipv4'
        )
        alb_arn = response['LoadBalancers'][0]['LoadBalancerArn']
        alb_dns = response['LoadBalancers'][0]['DNSName']
        print(f"✅ ALB Created: {alb_dns}")

        # Create Listener
        elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol='HTTP',
            Port=80,
            DefaultActions=[{'Type': 'forward', 'TargetGroupArn': tg_arn}]
        )
        print("✅ ALB Listener (HTTP:80) Created")
        return alb_arn
    except Exception as e:
        print(f"⚠️ Error creating Load Balancer: {e}")
        return None

def create_auto_scaling_group(lt_id, tg_arn):
    print(f"📈 Creating Auto Scaling Group: {ASG_NAME}...")
    try:
        autoscaling.create_auto_scaling_group(
            AutoScalingGroupName=ASG_NAME,
            LaunchTemplate={
                'LaunchTemplateId': lt_id,
                'Version': '$Latest'
            },
            MinSize=2,
            MaxSize=10,
            DesiredCapacity=2,
            VPCZoneIdentifier=','.join(SUBNET_IDS),
            TargetGroupARNs=[tg_arn],
            HealthCheckType='ELB',
            HealthCheckGracePeriod=300
        )
        print(f"✅ Auto Scaling Group Created: {ASG_NAME}")
        
        # Add Scaling Policy (CPU Utilization > 70%)
        autoscaling.put_scaling_policy(
            AutoScalingGroupName=ASG_NAME,
            PolicyName=f'{APP_NAME}-cpu-policy',
            PolicyType='TargetTrackingScaling',
            TargetTrackingConfiguration={
                'PredefinedMetricSpecification': {
                    'PredefinedMetricType': 'ASGAverageCPUUtilization'
                },
                'TargetValue': 70.0
            }
        )
        print("✅ Scaling Policy (CPU > 70%) Attached")
        
    except Exception as e:
        print(f"⚠️ Error creating ASG: {e}")

if __name__ == "__main__":
    print("🚀 Starting AWS Infrastructure Setup...")
    
    # 1. Create Launch Template
    lt_id = create_launch_template()
    
    if lt_id:
        # 2. Create Target Group
        tg_arn = create_target_group()
        
        if tg_arn:
            # 3. Create Load Balancer
            create_load_balancer(tg_arn)
            
            # 4. Create Auto Scaling Group
            create_auto_scaling_group(lt_id, tg_arn)
            
    print("✨ Infrastructure Setup Complete!")
