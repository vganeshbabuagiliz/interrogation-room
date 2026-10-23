# Deploying on AWS

The hackathon needs the agent to run on AWS. Decider runs on the hosted AWS User Group Madurai API,
so a small CPU instance is enough (no GPU).

1. **Bedrock access:** in the Bedrock console, make sure the models you want (fast and strong tiers) work in your
   region, e.g. send a prompt in the playground. Note the model or inference-profile ids.
2. **IAM role:** create a role for EC2 with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`
   on those models (and the inference profiles if the ids start with `us.`).
3. **Launch:** EC2, Amazon Linux 2023, `t3.small`, 20 GB, attach the role. Security group: TCP 8000 from your IP only
   (there is no login on the demo server).
4. **User data:** open `deploy/ec2-userdata.sh`, fill the CONFIG block (repo URL, Decider key, two model ids,
   region) and paste it as user data. The key is written to `.env` on the box (mode 600), never into the repo.
5. **Check:** `curl http://<public-ip>:8000/api/state`, then open `http://<public-ip>:8000` and play a turn.
   Logs: `journalctl -u interrogation-room -f`.
6. Record the demo video from this instance so it shows the agent running on AWS.

Hosted-tier limits to know: 4 questions per request (the client splits larger batches), 10 requests a minute,
1,024 output tokens per request.
