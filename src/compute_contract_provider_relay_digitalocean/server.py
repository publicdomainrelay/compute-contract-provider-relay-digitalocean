import os
import re
import json
import asyncio
import hashlib
import pathlib
import tempfile
import textwrap
import contextlib
import urllib.request
from typing import Any, Annotated

import aiohttp
import markdown2
from pydantic import BaseModel
from atproto import AsyncClient, models
from fastapi import (
    FastAPI,
    File,
    UploadFile,
    Request,
    Response,
    HTTPException,
)
from fastapi.responses import HTMLResponse, JSONResponse

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
# DO_TOKEN
DO_TOKEN = os.environ["DIGITALOCEAN_TOKEN"]


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
    markdown_html_content_by_file["README.md"] = textwrap.dedent(f"""
        <html>
            <title>{markdown_content.split("\n")[0].replace("# ", "")}</title>
            <body>
                {readme_markdown_html}
            </body>
        </html>
        """.strip())

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
    "GET /ccr/*": RouteConfig(
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
if not "X402_MAKE_FREE" in os.environ:
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


@app.get("/", response_class=HTMLResponse)
async def root():
    return markdown_html_content_by_file["README.md"]


class JSONError(BaseModel):
    error: str
    code: int | None = None
    detail: str | None = None


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    payload = JSONError(
        error="http_error",
        code=exc.status_code,
        detail=exc.detail or "",
    ).dict(exclude_none=True)
    return JSONResponse(status_code=exc.status_code, content=payload)


CID_RE = re.compile(r"^(bafy|z)[A-Za-z0-9]+$")


class ATProtoRecordRef(BaseModel):
    uri: str
    cid: str


class CCRFP_v0_0_0_Location(BaseModel):
    country: str
    region: str


class CCRFP_v0_0_0(BaseModel):
    mem: str
    cpus: int
    disk: str
    network: str
    location: CCRFP_v0_0_0_Location
    # Be very careful with this! Your did:plc:... can set whatever it wants!
    # So agents need their own accounts, because if you give them access to
    # yours they can just create a new form of compute with the whatever role
    # they want!
    role: str
    user_data: str

    _uri: str = None
    _cid: str = None


class CCB_v0_0_0_Embed(BaseModel):
    record: ATProtoRecordRef


class CCB_v0_0_0_Bid_x402(BaseModel):
    base_url: str


class CCB_v0_0_0_Bid_WIF_Subject(BaseModel):
    format: str


class CCB_v0_0_0_Bid_WIF(BaseModel):
    issuer_uri: str
    subject: CCB_v0_0_0_Bid_WIF_Subject


class CCB_v0_0_0_Bid(BaseModel):
    cost: float
    currency: str
    frequency: str
    prepay: bool
    x402: CCB_v0_0_0_Bid_x402
    wif: CCB_v0_0_0_Bid_WIF


class CCB_v0_0_0(BaseModel):
    embed: CCB_v0_0_0_Embed


from typing import List, Optional, Union
from pydantic import BaseModel, Field, constr

SlugStr = constr(min_length=1)


class DropletCreateImage(BaseModel):
    slug: Optional[SlugStr] = None
    id: Optional[int] = None
    name: Optional[str] = None


class DOv2DropletCreateRequest(BaseModel):
    name: constr(min_length=1) = Field(..., description="Droplet name")
    region: constr(min_length=1) = Field(..., description="Region slug, e.g. 'sfo3'")
    size: constr(min_length=1) = Field(
        ..., description="Size slug, e.g. 's-1vcpu-512mb-10gb'"
    )
    image: Union[SlugStr, DropletCreateImage] = Field(
        ..., description="Image slug or object with slug/id/name"
    )
    user_data: Optional[str] = Field(None, description="cloud-init user data")
    tags: Optional[List[str]] = Field(None, description="Tags to apply")
    with_droplet_agent: Optional[bool] = Field(
        None, description="Whether to install the DigitalOcean agent"
    )


async def create_droplet(ccrfp, ccb):
    global DO_TOKEN
    # TODO Run this under a workload id droplet
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DO_TOKEN}",
    }
    request_obj = DOv2DropletCreateRequest(
        name=f"{ccrfp._uri.split("/")[2].split(":")[-1]}-{ccrfp._uri.split("/")[4]}-{ccrfp._cid}",
        # TODO pick based off ccrfp.location
        region="sfo3",
        size="s-1vcpu-512mb-10gb",
        image="ubuntu-24-04-x64",
        user_data=ccrfp.user_data,
        with_droplet_agent=True,
        tags=[
            f'oidc-sub:plc:{ccrfp._uri.split("/")[2].split(":")[-1]}',
            f"oidc-sub:role:{ccrfp.role}",
        ],
    )
    snoop.pp(json.loads(request_obj.model_dump_json()))
    request_bytes = request_obj.model_dump_json().encode()
    # TODO aiohttp.ClientSession should be in lifecycle
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://droplet-oidc.its1337.com/v2/droplets",
            data=request_bytes,
            headers=headers,
        ) as response:
            response_json = await response.json()
            snoop.pp(response_json)
            if response.status >= 400:
                raise Exception(response_json)
    return response_json


@app.get("/ccr/{full_path:path}")
async def make_ccr(full_path: str, request: Request) -> dict[str, Any]:
    # Parse CCB
    path = request.url.path.lstrip("/")
    # split last segment as cid
    if "/" not in path:
        raise HTTPException(400, "missing cid")
    at_part, cid = path.rsplit("/", 1)
    if not CID_RE.match(cid):
        raise HTTPException(400, "invalid cid")
    if at_part.startswith("ccr/"):
        at_part = at_part[len("ccr/") :]
    at_uri = at_part

    # Resolve CCB
    ccb_at_uri = at_uri
    ccb_cid = cid
    record_ccb_params = models.ComAtprotoRepoGetRecord.Params(
        rkey=ccb_at_uri.split("/")[-1],
        repo=ccb_at_uri.split("/")[2],
        collection=ccb_at_uri.split("/")[3],
        uri=ccb_at_uri,
        cid=ccb_cid,
    )
    snoop.pp(record_ccb_params)
    record_ccb = await client.com.atproto.repo.get_record(
        record_ccb_params,
    )
    snoop.pp(record_ccb)
    record_ccb_value = record_ccb.value.to_dict()
    ccb_version = record_ccb_value.get("version", "0.0.0")
    # TODO Log warning on no version
    if ccb_version == "0.0.0":
        ccb = CCB_v0_0_0.model_validate(record_ccb_value)
    else:
        raise HTTPException(400, f"unknown CCB version {ccb_version}")

    snoop.pp(ccb)

    # Resolve CCRFP
    record_ccrfp_params = models.ComAtprotoRepoGetRecord.Params(
        rkey=ccb.embed.record.uri.split("/")[-1],
        repo=ccb.embed.record.uri.split("/")[2],
        collection=ccb.embed.record.uri.split("/")[3],
        uri=ccb.embed.record.uri,
        cid=ccb.embed.record.cid,
    )
    snoop.pp(record_ccrfp_params)
    record_ccrfp = await client.com.atproto.repo.get_record(
        record_ccrfp_params,
    )
    snoop.pp(record_ccrfp)
    ccrfp_at_uri = record_ccrfp.uri
    ccrfp_cid = record_ccrfp.cid
    # Get CCRFP value
    record_ccrfp_value = record_ccrfp.value.to_dict()
    ccrfp_version = record_ccrfp_value.get("version", "0.0.0")
    # TODO Log warning on no version
    if ccrfp_version == "0.0.0":
        ccrfp = CCRFP_v0_0_0.model_validate(record_ccrfp_value)
    else:
        raise HTTPException(400, f"unknown CCRFP version {ccrfp_version}")
    ccrfp._uri = ccrfp_at_uri
    ccrfp._cid = ccrfp_cid

    # TODO Retry Droplet creation if failed
    # Spin Droplet
    await create_droplet(ccrfp, ccb)

    # Create CCR
    record_ccr = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection="com.publicdomainrelay.ccr",
            record={
                "rfp": {
                    "$type": "com.publicdomainrelay.ccrfp",
                    "record": {
                        "uri": ccrfp_at_uri,
                        "cid": ccrfp_cid,
                    },
                },
                "bid": {
                    "$type": "com.publicdomainrelay.ccb",
                    "record": {
                        "uri": ccb_at_uri,
                        "cid": ccb_cid,
                    },
                },
                "createdAt": client.get_current_time_iso(),
            },
        ),
    )
    return {
        "id": record_ccr.uri.split("/")[-1],
        "uri": record_ccr.uri,
        "cid": record_ccr.cid,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4021)
