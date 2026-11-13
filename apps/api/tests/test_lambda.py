import json


def _event(path, method="GET", headers=None):
    """Minimal Lambda Function URL event (payload format 2.0)."""
    return {
        "version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "",
        "headers": {"host": "x.lambda-url.ap-south-1.on.aws", **(headers or {})},
        "requestContext": {"http": {"method": method, "path": path, "sourceIp": "1.2.3.4", "protocol": "HTTP/1.1"},
                           "domainName": "x.lambda-url.ap-south-1.on.aws", "accountId": "1", "apiId": "x",
                           "requestId": "r", "stage": "$default", "time": "now", "timeEpoch": 0},
        "isBase64Encoded": False,
    }


def test_lambda_handler_serves_the_same_app(client):  # `client` fixture resets the DB
    from lambda_handler import handler

    health = handler(_event("/api/health"), None)
    assert health["statusCode"] == 200 and json.loads(health["body"]) == {"ok": True}
    agents = handler(_event("/api/agents"), None)
    assert agents["statusCode"] == 200 and len(json.loads(agents["body"])) == 2
