# Deploy yaprr

```
Browser ─► Vercel (web) ──/api/* rewrite──► AWS Lambda (API, Function URL) ─► Neon Postgres
                                                 ▲
LiveKit Cloud room ◄──► LiveKit Cloud Agents (worker) ─┘ (fetches agent config, posts call records)
```

Why this split:
- **Web on Vercel:** static files on a CDN, free.
- **API on AWS Lambda:** the same FastAPI app, wrapped by Mangum (`lambda_handler.py`).
  It scales to zero, and Lambda's always-free tier (1M requests/month) covers a
  portfolio's traffic even after the 6-month AWS free plan.
- **Worker on LiveKit Cloud:** a long-running process holding a connection to
  LiveKit, which suits LiveKit's own agent hosting. The Build plan includes
  1,000 agent minutes. A small VM running `docker run` also works.
- **Neon:** managed Postgres with a free tier and no server to babysit.
- Not GCP: the only GCP access was an employer account, and personal projects stay off company infrastructure.

Do the steps in order. Each one gives you a value the next step needs.

## 0. Secrets you'll create
| Name | Where it's used | Make it with |
|---|---|---|
| `ADMIN_TOKEN` | API + you (dashboard login) | `python -c "import secrets;print(secrets.token_urlsafe(24))"` |
| `WORKER_TOKEN` | API + worker (same value) | same command |

## 1. Database: Neon
1. neon.tech → New project → pick the AWS region closest to Mumbai that Neon lists
   (`ap-south-1` if offered, else Singapore). Keep the API's Lambda region close to it.
2. Copy the connection string and change the scheme for SQLAlchemy:
   `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require`

Tables are created by Alembic when the API starts.

## 2. API: AWS Lambda (container image)
Needs: AWS CLI v2 (`aws configure` with your personal account) and Docker Desktop. Region: **the same as your Neon DB** (ap-southeast-1 / Singapore here).

1. **Env file.** Copy `apps/api/deploy/aws/lambda-env.example.json` to
   `apps/api/deploy/aws/lambda-env.json` (gitignored) and fill it in. Use Neon's
   **pooled** connection string (host contains `-pooler`): every Lambda instance
   opens its own connection, and the pooler keeps that from exhausting Postgres.

2. **Build and push the image, then create the function** (PowerShell, from `apps/api`):
```powershell
$REGION="ap-southeast-1"   # same region as your Neon DB (Singapore); keeps every DB query short
$ACCOUNT=(aws sts get-caller-identity --query Account --output text)
$REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/yaprr-api"

aws ecr create-repository --repository-name yaprr-api --region $REGION
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
docker build --platform linux/amd64 --provenance=false -f Dockerfile.lambda -t "${REPO}:v1" .
docker push "${REPO}:v1"

aws iam create-role --role-name yaprr-api-lambda --assume-role-policy-document file://deploy/aws/trust-policy.json
aws iam attach-role-policy --role-name yaprr-api-lambda --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
# wait ~10 s for the role to propagate, then:
aws lambda create-function --function-name yaprr-api --package-type Image --code ImageUri="${REPO}:v1" `
  --role "arn:aws:iam::${ACCOUNT}:role/yaprr-api-lambda" --timeout 30 --memory-size 1024 `
  --environment file://deploy/aws/lambda-env.json --region $REGION
```

3. **Public HTTPS URL** (the API's own tokens do the auth):
```powershell
aws lambda create-function-url-config --function-name yaprr-api --auth-type NONE --region $REGION
aws lambda add-permission --function-name yaprr-api --statement-id public-url `
  --action lambda:InvokeFunctionUrl --principal "*" --function-url-auth-type NONE --region $REGION
```
Open `https://<id>.lambda-url.ap-south-1.on.aws/api/health`. It should return
`{"ok":true}`. The first call is slower because of the cold start plus migrations.

If you get **403 Forbidden**, newer accounts also need `lambda:InvokeFunction`:
run the same `add-permission` again with `--statement-id public-invoke --action lambda:InvokeFunction`.

4. **Ship a new version** later:
```powershell
docker build --platform linux/amd64 --provenance=false -f Dockerfile.lambda -t "${REPO}:v2" .
docker push "${REPO}:v2"
aws lambda update-function-code --function-name yaprr-api --image-uri "${REPO}:v2" --region $REGION
```

5. **Safety:** set an AWS Budgets alert (e.g. $5). It also earns $20 of free-plan credit.
   Logs: CloudWatch → Log groups → `/aws/lambda/yaprr-api`.

## 3. Worker: LiveKit Cloud Agents
Create `apps/worker/secrets.prod.env` (gitignored). Leave out the `LIVEKIT_*`
values: LiveKit Cloud injects those itself.
```
DEEPGRAM_API_KEY=...
GOOGLE_API_KEY=...
CARTESIA_API_KEY=...
GROQ_API_KEY=...
OPENAI_API_KEY=...
YAPRR_API_URL=https://<id>.lambda-url.ap-south-1.on.aws
YAPRR_WORKER_TOKEN=<same as WORKER_TOKEN>
WORKER_AGENT_NAME=yaprr-agent
PREEMPTIVE_GENERATION=false
STT_LANGUAGE=hi
```
Then (install the CLI: `winget install LiveKit.LiveKitCLI`):
```powershell
cd C:\business\yaprr\apps\worker
lk cloud auth
lk agent create --secrets-file=secrets.prod.env
lk agent status
lk agent logs
```
`lk agent create` builds `apps/worker/Dockerfile`, writes `livekit.toml`, and
deploys. Later code changes go out with `lk agent deploy` (check `lk agent --help`
for your CLI version). Secret changes use `lk agent update-secrets`, which also
triggers a rolling restart.

## 4. Web: Vercel
1. Put your Lambda Function URL host into `apps/web/vercel.json`, replacing `REPLACE-WITH-YOUR-LAMBDA-URL-HOST` (e.g. `abc123.lambda-url.ap-south-1.on.aws`).
2. vercel.com → Add New Project → import the GitHub repo → **Root Directory: `apps/web`**.
   Framework: Vite. Build command `npm run build`. Output folder `dist`.
3. Deploy, open the URL, and sign in with `ADMIN_TOKEN`.

The rewrite makes the browser call `/api/...` on the Vercel domain, and Vercel
forwards it to Lambda. Same origin means no CORS setup and no API URL baked into the JS.

## 4b. Web on Netlify (what the live site uses)
`apps/web/netlify.toml` does the same job as `vercel.json`: it proxies `/api/*` to Lambda and adds the SPA fallback.
In Netlify, set **Base directory: `apps/web`**. Build `npm run build`, publish `dist`.

## 4c. Public demo and read-only mode
Set these on the Lambda (`aws lambda update-function-configuration --environment file://deploy/aws/lambda-env.json`):

| Var | Meaning |
|---|---|
| `PUBLIC_READ=true` | Visitors can browse agents, calls and dashboards without a token. Writes still need `ADMIN_TOKEN`. |
| `PUBLIC_TRANSCRIPTS` | Default `true`: visitors see transcripts too. Set `false` to show only metrics and outcomes. |
| `DEMO_ENABLED=true` | Turns on `/try`: anyone can call the demo agent. |
| `DEMO_MAX_CALL_SECONDS` | The worker hangs up at this point. The limit is signed into the LiveKit token. |
| `DEMO_CALLS_PER_IP_PER_DAY` | Per visitor, rolling 24 h. Best effort: IPs are shared and VPNs exist. |
| `DEMO_MINUTES_PER_DAY` | The hard cap. Each call reserves its full length, so the worst case is this × ~₹3/day. |

Also put a monthly spend limit on every provider account: Groq, OpenAI, Deepgram, Cartesia and Google AI Studio.
The caps above only protect the demo; leaked keys would bypass them.

## 5. Smoke test (5 min)
1. Dashboard loads after sign-in, and both demo agents are listed.
2. Agent → Talk to agent → Start test call. The agent greets you within ~1 s.
3. Hang up. The call appears in Calls with latency, cost and outcome.
4. `lk agent logs` shows `Call done ... api=True`.

## Costs at rest
- Vercel: free.
- Neon: free tier.
- Lambda: ~₹0 (1M requests/month always free; ECR image storage is a few rupees).
- LiveKit Cloud: free minutes on the Build plan.

You pay per call minute: about ₹2.8/min on the current pipeline.
