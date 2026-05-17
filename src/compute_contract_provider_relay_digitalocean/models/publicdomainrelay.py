from typing import Any, Optional

from pydantic import BaseModel, Field


# NSID / collection name per record type. Pre-stable schemas live under
# `com.publicdomainrelay.temp.*`; once stable, drop `.temp.` and evolve
# additively. For genuine breaking changes, bump a numeric suffix on the
# pydantic model (e.g. `RFP_v0_1_0`).
VM_NSID = "com.publicdomainrelay.temp.compute.vm"
WIF_SIMPLE_NSID = "com.publicdomainrelay.temp.compute.config.wif.simple"
RFP_NSID = "com.publicdomainrelay.temp.market.rfp"
BID_NSID = "com.publicdomainrelay.temp.market.bid"
BIDS_X402_NSID = "com.publicdomainrelay.temp.market.bids.x402"
ACCEPT_NSID = "com.publicdomainrelay.temp.market.accept"
RECEIPT_NSID = "com.publicdomainrelay.temp.market.receipt"
AGENT_SKILL_NSID = "com.publicdomainrelay.temp.agent.skill"


class StrongRef(BaseModel):
    """com.atproto.repo.strongRef ({$type, uri, cid})."""

    uri: str
    cid: str
    type_: Optional[str] = Field(
        default="com.atproto.repo.strongRef", alias="$type"
    )

    model_config = {"populate_by_name": True}


# com.publicdomainrelay.temp.compute.vm -------------------------------------


class VM_v0_0_0_Location(BaseModel):
    country: Optional[str] = None
    region: Optional[str] = None


class VM_v0_0_0(BaseModel):
    mem: str
    cpus: int
    disk: str
    network: str
    # Be very careful with this! Your did:plc:... can set whatever it wants!
    # Agents need their own accounts; sharing yours lets them mint roles.
    role: str
    user_data: str
    location: Optional[VM_v0_0_0_Location] = None

    _uri: str = None
    _cid: str = None


# com.publicdomainrelay.temp.market.rfp -------------------------------------


class RFP_v0_0_0(BaseModel):
    payload: StrongRef

    _uri: str = None
    _cid: str = None


# com.publicdomainrelay.temp.market.bids.x402 -------------------------------


class BidsX402_v0_0_0(BaseModel):
    cost: Any
    currency: str
    frequency: str
    prepay: bool
    url: str

    _uri: str = None
    _cid: str = None


# com.publicdomainrelay.temp.compute.config.wif.simple ----------------------


class WIFSimple_v0_0_0(BaseModel):
    issuer_uri: Optional[str] = None
    to_issue: Optional[str] = None
    token_path: Optional[str] = None
    url_path: Optional[str] = None
    url_route: Optional[str] = None
    subject: Optional[str] = None
    accept_path: Optional[str] = None

    _uri: str = None
    _cid: str = None


# com.publicdomainrelay.temp.market.bid -------------------------------------


class Bid_v0_0_0(BaseModel):
    rfp: StrongRef
    payload: StrongRef
    config: Optional[StrongRef] = None

    _uri: str = None
    _cid: str = None


# com.publicdomainrelay.temp.market.accept ----------------------------------


class Accept_v0_0_0(BaseModel):
    rfp: StrongRef
    bid: StrongRef
    payload: Optional[StrongRef] = None

    _uri: str = None
    _cid: str = None


# com.publicdomainrelay.temp.market.receipt ---------------------------------


class Receipt_v0_0_0(BaseModel):
    rfp: StrongRef
    bid: StrongRef
    accept: StrongRef
    payload: Optional[StrongRef] = None

    _uri: str = None
    _cid: str = None


def parse_at_uri(at_uri: str) -> tuple[str, str, str]:
    """Return (repo, collection, rkey) from an at:// URI."""
    parts = at_uri.split("/")
    return parts[2], parts[3], parts[4]
