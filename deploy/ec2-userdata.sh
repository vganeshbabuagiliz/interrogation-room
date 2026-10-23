#!/bin/bash
# EC2 user-data (UNTESTED as of writing): runs the Interrogation Room on a small CPU instance.
# Decider is the hosted AWS User Group Madurai API, so no GPU is needed.
#
# Instance: t3.small (or t3.medium), Amazon Linux 2023, 20 GB disk.
# Instance role: allow bedrock:InvokeModel and bedrock:InvokeModelWithResponseStream on the models below.
# Security group: open TCP 8000 to YOUR IP only. The demo server has no login.
#
# Fill in the four values in the CONFIG block, then paste this script as user data (or run it by hand).
set -euxo pipefail

# ---- CONFIG ---------------------------------------------------------------------------------
REPO_URL="<https://github.com/YOU/interrogation-room.git>"
DECIDER_API_KEY="<paste the hosted Decider key here; never commit it>"
BEDROCK_MODEL_FAST="<fast model or inference profile id, e.g. us.anthropic.claude-haiku-4-5-20251001-v1:0>"
BEDROCK_MODEL_STRONG="<strong model or inference profile id>"
AWS_REGION_NAME="us-east-1"
# ---------------------------------------------------------------------------------------------

dnf install -y git python3.11 python3.11-pip
cd /home/ec2-user
sudo -u ec2-user git clone "$REPO_URL" interrogation-room
cd interrogation-room
sudo -u ec2-user python3.11 -m venv .venv
sudo -u ec2-user .venv/bin/pip install -r requirements.txt

# Settings live in .env (gitignored, readable only by the service user).
cat > .env <<ENV
DECIDER_MODE=ugmdu
DECIDER_URL=https://da25tnxy06gjk.cloudfront.net
DECIDER_API_KEY=${DECIDER_API_KEY}
AWS_REGION=${AWS_REGION_NAME}
BEDROCK_MODEL_FAST=${BEDROCK_MODEL_FAST}
BEDROCK_MODEL_STRONG=${BEDROCK_MODEL_STRONG}
ENV
chown ec2-user:ec2-user .env && chmod 600 .env

cat > /etc/systemd/system/interrogation-room.service <<UNIT
[Unit]
Description=Interrogation Room
After=network-online.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/interrogation-room
Environment=HOST=0.0.0.0 PORT=8000 PYTHONIOENCODING=utf-8
ExecStart=/home/ec2-user/interrogation-room/.venv/bin/python server.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now interrogation-room
# Check:  curl localhost:8000/api/state   |   logs: journalctl -u interrogation-room -f
