"""AWS Lambda entry point (Function URL / API Gateway HTTP API).

Mangum translates the Lambda event into an ASGI request for the same FastAPI
app that runs under uvicorn locally, so there is one codebase for both.
`lifespan="auto"` runs startup (Alembic migrate + demo seed) on each cold start;
after the first run that's a quick no-op.
"""

from mangum import Mangum

from yaprr_api.main import app

handler = Mangum(app, lifespan="auto")
