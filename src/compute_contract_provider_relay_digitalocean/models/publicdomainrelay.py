from typing import Optional

from pydantic import BaseModel, Field


# NSID / collection name per record type. While pre-stable we use the
# `com.publicdomainrelay.temp.*` namespace; once stable, drop `.temp.`
# and evolve additively. For genuine breaking changes, bump the suffix
# (e.g. `ccrfpV2`).
CCRFP_NSID = "com.publicdomainrelay.temp.ccrfp"
CCB_NSID = "com.publicdomainrelay.temp.ccb"
CCBAP_NSID = "com.publicdomainrelay.temp.ccbap"
CCBA_NSID = "com.publicdomainrelay.temp.ccba"
CCR_NSID = "com.publicdomainrelay.temp.ccr"


class ATProtoRecordRef(BaseModel):
    uri: str
    cid: str


class TypedRecordRef(BaseModel):
    type_: str = Field(alias="$type")
    record: ATProtoRecordRef

    model_config = {"populate_by_name": True}


# CCRFP ----------------------------------------------------------------------


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


# CCB ------------------------------------------------------------------------


class CCB_v0_0_0_Embed(TypedRecordRef):
    pass


class CCB_v0_0_0_Bid_x402(BaseModel):
    base_url: str


class CCB_v0_0_0_Bid_WIF(BaseModel):
    issuer_uri: Optional[str] = None
    to_issue: Optional[str] = None
    token_path: Optional[str] = None
    url_path: Optional[str] = None
    url_route: Optional[str] = None
    subject: Optional[str] = None


class CCB_v0_0_0_Bid(BaseModel):
    cost: float
    currency: str
    frequency: str
    prepay: bool
    x402: CCB_v0_0_0_Bid_x402


class CCB_v0_0_0(BaseModel):
    embed: CCB_v0_0_0_Embed
    bid: Optional[CCB_v0_0_0_Bid] = None
    wif: Optional[CCB_v0_0_0_Bid_WIF] = None

    _uri: str = None
    _cid: str = None


# CCBAP ----------------------------------------------------------------------


class CCBAP_v0_0_0_Embed(TypedRecordRef):
    pass


class CCBAP_v0_0_0(BaseModel):
    embed: CCBAP_v0_0_0_Embed
    txid: Optional[str] = None

    _uri: str = None
    _cid: str = None


# CCBA -----------------------------------------------------------------------


class CCBA_v0_0_0_Payment(BaseModel):
    embed: TypedRecordRef


class CCBA_v0_0_0(BaseModel):
    embed: TypedRecordRef
    bid: TypedRecordRef
    payment: CCBA_v0_0_0_Payment

    _uri: str = None
    _cid: str = None


# Helpers --------------------------------------------------------------------


def parse_at_uri(at_uri: str) -> tuple[str, str, str]:
    """Return (repo, collection, rkey) from an at:// URI."""
    parts = at_uri.split("/")
    # at://<repo>/<collection>/<rkey>
    return parts[2], parts[3], parts[4]
