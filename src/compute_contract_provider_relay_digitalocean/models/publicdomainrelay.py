from pydantic import BaseModel


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
