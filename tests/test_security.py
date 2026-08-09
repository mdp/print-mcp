import httpx
import pytest
from starlette.responses import JSONResponse

from print_mcp.app import SecurityMiddleware


async def downstream(scope, receive, send) -> None:
    response = JSONResponse({"passed": True})
    await response(scope, receive, send)


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/other"])
async def test_non_mcp_routes_do_not_require_auth(path: str) -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)
    assert response.status_code == 200


async def test_mcp_requires_bearer_token() -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_mcp_accepts_correct_token() -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp", headers={"Authorization": f"Bearer {'a' * 32}"})
    assert response.status_code == 200


async def test_mcp_accepts_bearer_token_any_case() -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp", headers={"Authorization": f"bearer {'a' * 32}"})
    assert response.status_code == 200


async def test_mcp_rejects_non_bearer_authorization_scheme() -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp", headers={"Authorization": f"Basic {'a' * 32}"})
    assert response.status_code == 401


async def test_mcp_accepts_token_via_custom_header() -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp", headers={"X-API-Key": "a" * 32})
    assert response.status_code == 200


async def test_mcp_accepts_raw_authorization_header() -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp", headers={"Authorization": "a" * 32})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "params",
    ["token=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "access_token=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
)
async def test_mcp_accepts_token_via_query_string(params: str) -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/mcp?{params}")
    assert response.status_code == 200


async def test_present_origin_must_be_allowlisted() -> None:
    app = SecurityMiddleware(downstream, "a" * 32, frozenset({"https://allowed.example"}))
    headers = {"Authorization": f"Bearer {'a' * 32}", "Origin": "https://blocked.example"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp", headers=headers)
    assert response.status_code == 403
