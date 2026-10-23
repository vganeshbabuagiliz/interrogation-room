# Deploying on AWS

The hackathon needs the agent to run on AWS. Decider runs on the hosted AWS User Group Madurai API,
so a small CPU instance is enough (no GPU).

1. **Bedrock access:** in the Bedrock console, make sure the models you want (fast and strong tiers) work in your
   region, e.g. send a prompt in the playground. Note the model or inference-profile ids.
2. **IAM role:** create a role for EC2 with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`
   on those models (and the inference profiles if the ids start with `us.`).
3. **Launch:** EC2, Amazon Linux 2023, `t3.small`, 20 GB, attach the role. Security group: TCP 80 from your IP only
   while testing.
4. **User data:** open `deploy/ec2-userdata.sh`, fill the CONFIG block (repo URL, Decider key, two model ids,
   region) and paste it as user data. The key is written to `.env` on the box (mode 600), never into the repo.
5. **Check:** `curl http://<public-ip>/api/state`, then open `http://<public-ip>` and play a turn.
   Logs: `journalctl -u interrogation-room -f`.
6. Record the demo video from this instance so it shows the agent running on AWS.

Hosted-tier limits to know: 4 questions per request (the client splits larger batches), 10 requests a minute,
1,024 output tokens per request.

## Sharing the endpoint with judges

Set `ACCESS_CODE` in the user-data CONFIG block (or in `.env`). The browser then shows a login box; the
username can be anything and the password is the access code. Give the code to the judges in the submission
notes, not in the public repo. The server also limits each visitor to 40 turns an hour and everyone to 400 a day
(`MAX_TURNS_PER_HOUR`, `MAX_TURNS_PER_DAY`), runs at most 3 turns at once, and keeps a separate game per
visitor. When the access code is set you can open port 80 to `0.0.0.0/0`; close it again after judging.
Also create an AWS Budgets alert, because Bedrock usage is billed to your account. Use HTTPS (an ALB or CloudFront
in front) if you want the code encrypted in transit; plain HTTP sends it in clear text.
