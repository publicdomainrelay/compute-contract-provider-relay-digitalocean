import os
import re
import json
import asyncio
import pathlib
import textwrap
import contextlib
import subprocess
import urllib.request
from typing import Any, List, Optional, Union

import aiohttp
import markdown2
import yaml
from pydantic import BaseModel, Field, constr
from atproto import AsyncClient, models
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
)
from fastapi.responses import HTMLResponse, JSONResponse

import snoop

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

from .models.publicdomainrelay import *

app = FastAPI()

# Your receiving wallet address
pay_to = os.environ["RECV_ADDR"]
# Coinbase Developer Platform Facilitator auth
os.environ["CDP_API_KEY_ID"] = os.environ["CDP_RECV_API_KEY_ID"]
os.environ["CDP_API_KEY_SECRET"] = os.environ["CDP_RECV_API_KEY_SECRET"]
# DO_TOKEN
DO_TOKEN = os.environ["DIGITALOCEAN_TOKEN"]
RBAC_REPO_ROOT = pathlib.Path(os.environ["RBAC_REPO_ROOT"]).resolve()
# Public base URL this relay is reachable at (used to build x402 url template
# for bid records). Falls back to the per-request base_url if unset.
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

# Where, on the freshly provisioned VM, the resolved accept bundle is
# written by cloud-init. The wif.simple record advertises this path with
# `$HOME` (the VM runs as root, so $HOME=/root resolves to ACCEPT_PATH_VM).
ACCEPT_PATH_RECORD = "$HOME/secrets/publicdomainrelay.com/market/accept.json"
ACCEPT_PATH_VM = "/root/secrets/publicdomainrelay.com/market/accept.json"


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


facilitator = HTTPFacilitatorClient(
    FacilitatorConfig(
        url="https://api.cdp.coinbase.com/platform/v2/x402",
        auth_provider=CreateHeadersAuthProvider(create_headers),
    ),
)
server = x402ResourceServer(facilitator)
server.register("eip155:8453", ExactEvmServerScheme())


did_plcs = {}
markdown_html_content_by_file = {}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        markdown_content = (
            pathlib.Path(__file__)
            .parents[2]
            .joinpath("README.md")
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


atproto_handle = os.environ["ATPROTO_HANDLE"]
atproto_password = os.environ["ATPROTO_PASSWORD"]

client = AsyncClient()

app = FastAPI(lifespan=lifespan)

# Define protected routes. /receipt is the post-payment settle endpoint:
# Alice POSTs the com.publicdomainrelay.temp.market.accept AT URI/CID and
# the provider spins compute + writes the matching receipt.
routes: dict[str, RouteConfig] = {
    "GET /receipt/*": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=pay_to,
                price="$1.00",
                network="eip155:8453",
            ),
        ],
        mime_type="application/json",
        description="Pay for compute contract",
    ),
}

if "X402_MAKE_FREE" not in os.environ:
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


class DigitalOceanContext(BaseModel):
    rbac_repo_root: pathlib.Path
    team_uuid: str


async def make_doctx():
    global DO_TOKEN
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DO_TOKEN}",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://droplet-oidc.its1337.com/v2/account",
            headers=headers,
        ) as response:
            response_json = await response.json()
            snoop.pp(response_json)
            if response.status >= 400:
                raise Exception(response_json)
    return DigitalOceanContext(
        rbac_repo_root=RBAC_REPO_ROOT,
        team_uuid=response_json["account"]["team"]["uuid"],
    )


async def asyncio_create_subprocess_exec(cmd, cwd):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd.resolve()),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    returncode = await proc.wait()
    if returncode != 0:
        snoop.pp(returncode, stdout, stderr)
        raise subprocess.CalledProcessError(
            returncode=returncode,
            cmd=cmd,
            output=stdout,
            stderr=stderr,
        )
    return stdout, stderr


async def configure_droplet_rbac(
    doctx: DigitalOceanContext,
    vm: VM_v0_0_0,
    requester_did: str,
    req: DOv2DropletCreateRequest,
):
    rbac_repo_root = doctx.rbac_repo_root

    if not rbac_repo_root.joinpath(".git").is_dir():
        rbac_repo_root.mkdir(exist_ok=True, parents=True)
        cred_helper_contents = """
#!/usr/bin/env bash

TOKEN={token}

while IFS='=' read -r key value; do
  if [[ -n "$key" && -n "$value" ]]; then
    if [[ "$key" == "protocol" || "$key" == "host" ]]; then
      echo "$key=$value"
    fi
  fi
done

echo "username=token"
echo "password=${TOKEN}"
""".lstrip()
        cred_helper_contents = cred_helper_contents.replace(
            "{token}", '"' + DO_TOKEN + '"'
        )
        cred_helper_path = pathlib.Path(
            "~",
            ".local",
            "scripts",
            "git-credential-rbac-digitalocean.sh",
        ).expanduser()
        cred_helper_path.parent.mkdir(exist_ok=True, parents=True)
        cred_helper_path.write_text(cred_helper_contents)
        cred_helper_path.chmod(0o700)

        for cmd in [
            [
                "git",
                "config",
                "--global",
                r'credential.https://droplet-oidc.its1337.com/_rbac/DigitalOcean/.helper',
                f"!{cred_helper_path.resolve()}",
            ],
            ["git", "init"],
            [
                "git",
                "remote",
                "add",
                "origin",
                f"https://droplet-oidc.its1337.com/_rbac/DigitalOcean/{doctx.team_uuid}",
            ],
            ["git", "pull", "origin", "main"],
            ["git", "branch", "--set-upstream-to=origin/main"],
        ]:
            snoop.pp(cmd)
            await asyncio_create_subprocess_exec(cmd, rbac_repo_root)

    requester_plc = requester_did.split(":")[-1]
    slug = "-".join([doctx.team_uuid, requester_plc, vm.role])

    policy_path = rbac_repo_root.joinpath("policies", f"ex-{slug}.hcl")
    policy_ex = """
path "/v1/oidc/issue" {
  capabilities = ["create"]
  allowed_parameters = {
    "aud" = "*"
    "sub" = "actx:{actx}:plc:{did-plc-key}:role:{role}"
    "ttl" = 3600
  }
}
""".lstrip()
    policy_ex = (
        policy_ex.replace("{actx}", doctx.team_uuid)
        .replace("{did-plc-key}", requester_plc)
        .replace("{role}", vm.role)
    )

    role_path = rbac_repo_root.joinpath("droplet-roles", f"ex-{slug}.hcl")
    role_ex = """
role "ex-{slug}" {
  aud      = "api://DigitalOcean?actx={actx}"
  sub      = "actx:{actx}:plc:{did-plc-key}:role:{role}"
  policies = ["ex-{slug}"]
}
""".lstrip()
    role_ex = (
        role_ex.replace("{actx}", doctx.team_uuid)
        .replace("{did-plc-key}", requester_plc)
        .replace("{role}", vm.role)
        .replace("{slug}", slug)
    )

    policy_path.parent.mkdir(exist_ok=True, parents=True)
    role_path.parent.mkdir(exist_ok=True, parents=True)
    policy_path.write_text(policy_ex)
    role_path.write_text(role_ex)

    for cmd in [
        ["git", "add", "-A"],
        ["git", "commit", "-m", "feat: rbac for compute-contract"],
        ["git", "push"],
    ]:
        try:
            await asyncio_create_subprocess_exec(cmd, rbac_repo_root)
        except subprocess.CalledProcessError as error:
            if cmd[1] == "commit" and b"nothing to commit" in error.stderr:
                break


def _strongref_dict(uri: str, cid: str) -> dict[str, str]:
    return {"$type": "com.atproto.repo.strongRef", "uri": uri, "cid": cid}


def _model_to_record(obj) -> dict[str, Any]:
    return obj.model_dump(by_alias=True, exclude_none=True)


def _inject_accept_bundle(user_data: str, bundle: dict[str, Any]) -> str:
    """Splice a cloud-init write_files entry into existing user_data that
    drops the fully-resolved accept bundle at ACCEPT_PATH_VM, plus a runcmd
    that chmods its parent dirs. Mirrors the
    workload_identity_oauth_reverse_proxy/provisioning.py pattern: parse the
    existing yaml object (or start one), mutate, re-emit with the
    #cloud-config header.
    """
    user_data_obj: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        parsed = yaml.safe_load(user_data) if user_data else None
        if isinstance(parsed, dict):
            user_data_obj = parsed
    user_data_obj.setdefault("write_files", []).append(
        {
            "path": ACCEPT_PATH_VM,
            "owner": "root:root",
            "permissions": "0600",
            "content": json.dumps(bundle, indent=2, sort_keys=True),
        },
    )
    parent = ACCEPT_PATH_VM.rsplit("/", 1)[0]
    user_data_obj.setdefault("runcmd", []).insert(
        0,
        ["sh", "-c", f"install -d -m 0700 -o root -g root {parent}"],
    )
    return "#cloud-config\n" + yaml.safe_dump(user_data_obj, sort_keys=False)


async def create_droplet(vm: VM_v0_0_0, requester_did: str):
    global DO_TOKEN
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DO_TOKEN}",
    }
    requester_plc = requester_did.split(":")[-1]
    request_obj = DOv2DropletCreateRequest(
        name=f"{requester_plc}-{vm._uri.split('/')[4]}-{vm._cid}",
        # TODO pick based off vm.location
        region="sfo3",
        size="s-1vcpu-512mb-10gb",
        image="ubuntu-24-04-x64",
        user_data=vm.user_data,
        with_droplet_agent=True,
        tags=[
            f"oidc-sub:plc:{requester_plc}",
            f"oidc-sub:role:{vm.role}",
        ],
    )
    snoop.pp(json.loads(request_obj.model_dump_json()))
    doctx = await make_doctx()
    await configure_droplet_rbac(doctx, vm, requester_did, request_obj)
    request_bytes = request_obj.model_dump_json().encode()
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


async def _get_record(at_uri: str, cid: str):
    repo, collection, rkey = parse_at_uri(at_uri)
    params = models.ComAtprotoRepoGetRecord.Params(
        rkey=rkey,
        repo=repo,
        collection=collection,
        uri=at_uri,
        cid=cid,
    )
    snoop.pp(params)
    return await client.com.atproto.repo.get_record(params)


def _record_version(record_value: dict) -> str:
    return record_value.get("version", "0.0.0")


async def _resolve(at_uri: str, cid: str, cls):
    record = await _get_record(at_uri, cid)
    value = record.value.to_dict()
    version = _record_version(value)
    if version != "0.0.0":
        raise HTTPException(400, f"unknown {cls.__name__} version {version}")
    obj = cls.model_validate(value)
    obj._uri = at_uri
    obj._cid = cid
    return obj


@app.get("/receipt/{full_path:path}")
async def make_receipt(full_path: str, request: Request) -> dict[str, Any]:
    """Settle endpoint. Path: /receipt/<accept-at-uri>/<cid>.

    Resolves the com.publicdomainrelay.temp.market.accept, walks back to
    the bid + rfp + vm, spins the droplet, and writes a
    com.publicdomainrelay.temp.market.receipt referencing all three.
    """
    path = request.url.path.lstrip("/")
    if "/" not in path:
        raise HTTPException(400, "missing cid")
    at_part, cid = path.rsplit("/", 1)
    if not CID_RE.match(cid):
        raise HTTPException(400, "invalid cid")
    if at_part.startswith("receipt/"):
        at_part = at_part[len("receipt/"):]
    accept_at_uri = at_part
    accept_cid = cid

    accept = await _resolve(accept_at_uri, accept_cid, Accept_v0_0_0)
    snoop.pp(accept)

    bid = await _resolve(accept.bid.uri, accept.bid.cid, Bid_v0_0_0)
    snoop.pp(bid)

    rfp_at_uri = accept.rfp.uri
    rfp_cid = accept.rfp.cid
    if bid.rfp.uri != rfp_at_uri or bid.rfp.cid != rfp_cid:
        raise HTTPException(400, "Accept.rfp does not match Bid.rfp")
    rfp = await _resolve(rfp_at_uri, rfp_cid, RFP_v0_0_0)
    snoop.pp(rfp)

    vm = await _resolve(rfp.payload.uri, rfp.payload.cid, VM_v0_0_0)
    snoop.pp(vm)

    bid_payload = await _resolve(
        bid.payload.uri, bid.payload.cid, BidsX402_v0_0_0
    )
    bid_config = None
    if bid.config is not None:
        bid_config = await _resolve(
            bid.config.uri, bid.config.cid, WIFSimple_v0_0_0
        )

    accept_bundle = {
        "$type": ACCEPT_NSID,
        "accept": {
            "uri": accept._uri,
            "cid": accept._cid,
            "value": _model_to_record(accept),
        },
        "rfp": {
            "uri": rfp._uri,
            "cid": rfp._cid,
            "value": _model_to_record(rfp),
        },
        "bid": {
            "uri": bid._uri,
            "cid": bid._cid,
            "value": _model_to_record(bid),
        },
        "bid_payload": {
            "uri": bid_payload._uri,
            "cid": bid_payload._cid,
            "value": _model_to_record(bid_payload),
        },
        "bid_config": (
            {
                "uri": bid_config._uri,
                "cid": bid_config._cid,
                "value": _model_to_record(bid_config),
            }
            if bid_config is not None
            else None
        ),
        "vm": {
            "uri": vm._uri,
            "cid": vm._cid,
            "value": _model_to_record(vm),
        },
    }
    vm.user_data = _inject_accept_bundle(vm.user_data, accept_bundle)

    requester_did = parse_at_uri(rfp._uri)[0]
    # TODO Retry Droplet creation if failed
    await create_droplet(vm, requester_did)

    record_receipt = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection=RECEIPT_NSID,
            record={
                "$type": RECEIPT_NSID,
                "rfp": {
                    "$type": "com.atproto.repo.strongRef",
                    "uri": rfp_at_uri,
                    "cid": rfp_cid,
                },
                "bid": {
                    "$type": "com.atproto.repo.strongRef",
                    "uri": bid._uri,
                    "cid": bid._cid,
                },
                "accept": {
                    "$type": "com.atproto.repo.strongRef",
                    "uri": accept_at_uri,
                    "cid": accept_cid,
                },
                "createdAt": client.get_current_time_iso(),
            },
        ),
    )
    return {
        "id": record_receipt.uri.split("/")[-1],
        "uri": record_receipt.uri,
        "cid": record_receipt.cid,
    }


# ---------------------------------------------------------------------------
# RFP -> Bid webhook hook
# ---------------------------------------------------------------------------


class FirehoseCommit(BaseModel):
    operation: str
    collection: str
    rkey: str
    record: dict[str, Any]
    cid: Optional[str] = None


class FirehoseEvent(BaseModel):
    did: str
    time_us: Optional[int] = None
    kind: Optional[str] = None
    commit: FirehoseCommit


class WebhookPayload(BaseModel):
    """Matches the airglow/firehose webhook envelope. See the first JSON
    object in agent-atproto-digitalocean-typescript/output.log."""

    automation: Optional[str] = None
    lexicon: Optional[str] = None
    conditions: Optional[List[dict[str, Any]]] = None
    event: FirehoseEvent


def _x402_url_template(request: Request) -> str:
    base = BASE_URL or str(request.base_url).rstrip("/")
    # x402 url template — {at} and {cid} placeholders are filled in by Alice
    # with the AT URI / CID of the com.publicdomainrelay.temp.market.accept.
    return f"{base}/receipt/{{at}}/{{cid}}"


@app.post("/hook/rfp")
async def hook_rfp(payload: WebhookPayload, request: Request) -> dict[str, Any]:
    """Webhook fired on firehose commits. When the commit creates a
    com.publicdomainrelay.temp.market.rfp record, write a matching
    com.publicdomainrelay.temp.market.bid (envelope) referencing a freshly
    created com.publicdomainrelay.temp.market.bids.x402 payload and a
    com.publicdomainrelay.temp.compute.config.wif.simple config.
    """
    commit = payload.event.commit
    if commit.operation != "create":
        return {"skipped": "operation", "operation": commit.operation}
    if commit.collection != RFP_NSID:
        return {"skipped": "collection", "collection": commit.collection}
    if not commit.cid:
        raise HTTPException(400, "commit.cid required")

    rfp_at_uri = f"at://{payload.event.did}/{commit.collection}/{commit.rkey}"
    rfp_cid = commit.cid

    # Sanity-check by resolving the rfp (also gets the vm strongRef for
    # future pricing decisions).
    rfp = await _resolve(rfp_at_uri, rfp_cid, RFP_v0_0_0)

    config_record = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection=WIF_SIMPLE_NSID,
            record={
                "$type": WIF_SIMPLE_NSID,
                "accept_path": ACCEPT_PATH_RECORD,
                "issuer_uri": "https://droplet-oidc.its1337.com",
                "to_issue": "exchange-custom-droplet-oidc-poc",
                "token_path": "/root/secrets/digitalocean.com/serviceaccount/token",
                "url_path": "/root/secrets/digitalocean.com/serviceaccount/base_url",
                "url_route": "/v1/oidc/issue",
                "subject": "actx:{actx}:plc:{did-plc-key}:role:{role}",
                "createdAt": client.get_current_time_iso(),
            },
        ),
    )

    payload_record = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection=BIDS_X402_NSID,
            record={
                "$type": BIDS_X402_NSID,
                "cost": 1,
                "currency": "USDC",
                "frequency": "monthly",
                "prepay": True,
                "url": _x402_url_template(request),
                "createdAt": client.get_current_time_iso(),
            },
        ),
    )

    bid_record = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection=BID_NSID,
            record={
                "$type": BID_NSID,
                "rfp": {
                    "$type": "com.atproto.repo.strongRef",
                    "uri": rfp_at_uri,
                    "cid": rfp_cid,
                },
                "config": {
                    "$type": "com.atproto.repo.strongRef",
                    "uri": config_record.uri,
                    "cid": config_record.cid,
                },
                "payload": {
                    "$type": "com.atproto.repo.strongRef",
                    "uri": payload_record.uri,
                    "cid": payload_record.cid,
                },
                "createdAt": client.get_current_time_iso(),
            },
        ),
    )

    return {
        "success": True,
        "rfp": {"uri": rfp_at_uri, "cid": rfp_cid},
        "bid": {
            "$type": "com.atproto.repo.strongRef",
            "uri": bid_record.uri,
            "cid": bid_record.cid,
        },
        "bid_payload": {
            "$type": "com.atproto.repo.strongRef",
            "uri": payload_record.uri,
            "cid": payload_record.cid,
        },
        "bid_config": {
            "$type": "com.atproto.repo.strongRef",
            "uri": config_record.uri,
            "cid": config_record.cid,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4021)
