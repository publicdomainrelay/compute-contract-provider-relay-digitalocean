import os
import json
import asyncio
import hashlib
import pathlib
import tempfile
import textwrap
import contextlib
import urllib.request
from typing import Any, Annotated

import markdown2
from pydantic import BaseModel
from atproto import AsyncClient, models
from fastapi import FastAPI, File, UploadFile, Request, Response, HTTPException
from fastapi.responses import HTMLResponse

import snoop
from fastapi import FastAPI, Request

from x402.http import (
    FacilitatorConfig,
    HTTPFacilitatorClient,
    PaymentOption,
    CreateHeadersAuthProvider,
)
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from cdp.auth.utils.jwt import generate_jwt, JwtOptions

app = FastAPI()

# Your receiving wallet address
pay_to = os.environ["RECV_ADDR"]
# Coinbase Developer Platform Facilitator auth
os.environ["CDP_API_KEY_ID"] = os.environ["CDP_RECV_API_KEY_ID"]
os.environ["CDP_API_KEY_SECRET"] = os.environ["CDP_RECV_API_KEY_SECRET"]


# Generate the JWT using the CDP SDK
# https://docs.cdp.coinbase.com/api-reference/v2/rest-api/x402-facilitator/verify-a-payment
# https://docs.cdp.coinbase.com/api-reference/v2/authentication#python
def mkheaders(host, path, method):
    jwt_token = generate_jwt(
        JwtOptions(
            api_key_id=os.environ["CDP_RECV_API_KEY_ID"],
            api_key_secret=os.environ["CDP_RECV_API_KEY_SECRET"],
            request_method=method,
            request_host=host,
            request_path=path,
            expires_in=120,
        )
    )
    return {
        "Authorization": f"Bearer {jwt_token}",
    }


def create_headers() -> dict[str, dict[str, str]]:
    return {
        "verify": mkheaders(
            "api.cdp.coinbase.com",
            "/platform/v2/x402/verify",
            "POST",
        ),
        "settle": mkheaders(
            "api.cdp.coinbase.com",
            "/platform/v2/x402/settle",
            "POST",
        ),
        "supported": mkheaders(
            "api.cdp.coinbase.com",
            "/platform/v2/x402/supported",
            "GET",
        ),
        "bazaar": {},
    }


# Create facilitator client (testnet)
facilitator = HTTPFacilitatorClient(
    # FacilitatorConfig(url="https://x402.org/facilitator")
    FacilitatorConfig(
        url="https://api.cdp.coinbase.com/platform/v2/x402",
        auth_provider=CreateHeadersAuthProvider(create_headers),
    ),
)

# Create resource server and register EVM scheme
server = x402ResourceServer(facilitator)
server.register("eip155:8453", ExactEvmServerScheme())


did_plcs = {}
markdown_html_content_by_file = {}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # For when in local dev
        markdown_content = (
            pathlib.Path(__file__)
            .parents[2]
            .joinpath(
                "README.md",
            )
            .read_text()
        )
    except:
        markdown_content = (
            urllib.request.urlopen(
                "https://github.com/publicdomainrelay/atprotobin/raw/refs/heads/main/README.md",
            )
            .read()
            .decode()
        )
    readme_markdown_html = markdown2.markdown(
        markdown_content,
        extras=[
            "fenced-code-blocks",
            "code-friendly",
            "highlightjs-lang",
        ],
    )
    markdown_html_content_by_file["README.md"] = textwrap.dedent(
        f"""
        <html>
            <title>{markdown_content.split("\n")[0].replace("# ", "")}</title>
            <body>
                {readme_markdown_html}
            </body>
        </html>
        """.strip()
    )

    profile = await client.login(
        atproto_handle,
        atproto_password,
    )
    did_plcs[atproto_handle] = profile.did
    yield


# atproto_base_url = os.environ["ATPROTO_BASE_URL"]
atproto_handle = os.environ["ATPROTO_HANDLE"]
atproto_password = os.environ["ATPROTO_PASSWORD"]

client = AsyncClient(
    # base_url=atproto_base_url,
)

app = FastAPI(lifespan=lifespan)

# Define protected routes
routes: dict[str, RouteConfig] = {
    "GET /": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=pay_to,
                price="$1.00",  # USDC amount in dollars
                network="eip155:8453",  # Base mainnet
            ),
        ],
        mime_type="application/json",
        description="Pay for compute contract",
    ),
}

# Add payment middleware
# app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


@app.get("/", response_class=HTMLResponse)
async def root():
    return markdown_html_content_by_file["README.md"]


@app.get("/ccr")
async def make_ccr(request: Request) -> dict[str, Any]:
    post = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection="com.publicdomainrelay.ccr",
            record={
                "feed": "face",
                "createdAt": client.get_current_time_iso(),
            },
        ),
    )
    return {
        "id": post.uri.split("/")[-1],
        "uri": post.uri,
        "cid": post.cid,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4021)
