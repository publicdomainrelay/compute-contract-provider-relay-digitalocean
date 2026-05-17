# Compute Contract Provider Relay DigitalOcean

- <https://github.com/publicdomainrelay/compute-contract>

## Testing

```bash
python -m venv .venv && . .venv/bin/activate && uv pip install -e .[dev]

. .venv/bin/activate

RBAC_REPO_ROOT="${HOME}/src/rbac/do/wid-atp" X402_MAKE_FREE=1 \
BASE_URL="https://compute-contract.johnandersen777.bsky.social.fedproxy.com" \
  nodemon -e py --exec "clear; uv run -m compute_contract_provider_relay_digitalocean.server; test 1"

# Settle: POST the com.publicdomainrelay.temp.market.accept AT URI/CID
curl http://localhost:4021/receipt/at://did:plc:5svqtrhheairglgiiyvutzik/com.publicdomainrelay.temp.market.accept/3mlagijgoeb23/bafyreiamisq3yqgb4k3tdojmzvvzpuwj46ytwbj672zxhyxxl7t36qadz4 | jq

$ npx awal x402 pay https://compute-contract.johnandersen777.bsky.social.fedproxy.com/receipt/at://did:plc:5svqtrhheairglgiiyvutzik/com.publicdomainrelay.temp.market.accept/3mlagijgoeb23/bafyreiamisq3yqgb4k3tdojmzvvzpuwj46ytwbj672zxhyxxl7t36qadz4
✓ Request completed (HTTP 200)

Response:
{
  "id": "3mld67yj3xo2u",
  "uri": "at://did:plc:5svqtrhheairglgiiyvutzik/com.publicdomainrelay.temp.market.receipt/3mld67yj3xo2u",
  "cid": "bafyreibzynxkkoxxvppbfoeh5s2s2asrm2j7ziw2ol5ufau4q25d7ousiy"
}

# Auto-bid: webhook fires on firehose commits. Forward each commit to
# /hook/rfp; the relay creates a bids.x402 payload, a wif.simple config,
# and a market.bid envelope strongRef'ing the rfp, and replies with the
# new bid record's strongRef.
curl -s -X POST http://localhost:4021/hook/rfp \
  -H 'content-type: application/json' \
  -d '{
    "automation": "at://did:plc:5svqtrhheairglgiiyvutzik/run.airglow.automation/3mlywhsfdz222",
    "lexicon": "com.publicdomainrelay.temp.market.rfp",
    "event": {
      "did": "did:plc:lpfuqerea3deuoyrn7ojser4",
      "kind": "commit",
      "commit": {
        "operation": "create",
        "collection": "com.publicdomainrelay.temp.market.rfp",
        "rkey": "3mm3doliee72s",
        "cid": "bafyreib5u2krsumyya5eiqc7ys7iz3xxlourd34p7qlpehi7a7h2kdc3ia",
        "record": {
          "$type": "com.publicdomainrelay.temp.market.rfp",
          "payload": {
            "$type": "com.atproto.repo.strongRef",
            "uri": "at://did:plc:lpfuqerea3deuoyrn7ojser4/com.publicdomainrelay.temp.compute.vm/3mm3dolfolz2c",
            "cid": "bafyreif4toqzci4nu3thujm2quurs4h432qk3gxvmkwze2wrrznn757omi"
          }
        }
      }
    }
  }' | jq
```

The `/receipt` route takes the **Accept**
(`com.publicdomainrelay.temp.market.accept`) AT URI/CID. The provider
resolves the Accept, then resolves the Bid (envelope) and RFP (envelope)
it references, validates that the Bid's `rfp` strongRef matches the
Accept's `rfp` strongRef, resolves the VM payload via `rfp.payload`,
spins the compute, and writes a `com.publicdomainrelay.temp.market.receipt`
record strongRef'ing the RFP, Bid, and Accept.

The `/hook/rfp` route accepts the airglow/firehose webhook envelope
(see the first JSON object in
`agent-atproto-digitalocean-typescript/output.log`). When the commit's
`collection` is `com.publicdomainrelay.temp.market.rfp` it writes:

1. a `com.publicdomainrelay.temp.compute.config.wif.simple` config record,
2. a `com.publicdomainrelay.temp.market.bids.x402` payload record whose
   `url` is `{BASE_URL}/receipt/{at}/{cid}` (placeholders filled in by
   Alice with the Accept's AT URI/CID), and
3. a `com.publicdomainrelay.temp.market.bid` envelope strongRef'ing the
   RFP, the config, and the x402 payload.

All record collection / `$type` names live under the
`com.publicdomainrelay.temp.*` namespace while the schemas are
pre-stable. Once stable they will move to `com.publicdomainrelay.<name>`
and evolve additively; genuine breaking changes get a numeric suffix on
the pydantic model (e.g. `RFP_v0_1_0`). Lexicons for every type live
upstream at
<https://github.com/publicdomainrelay/compute-contract/tree/main/lexicons>.

## RBAC: droplet-oidc-poc

droplet-oidc-poc enforces actx but other fields are enforced at the
RBAC level. To really trust it for this use case it would also need to
enforce the plc field. As long as the actx owner only creates RBAC which enforce
plc then it should be fine.

#### policies/ex.hcl

```hcl
path "/v1/oidc/issue" {
  capabilities = ["create"]
  allowed_parameters = {
    "aud" = "*"
    "sub" = "actx:{actx}:plc:{did-plc-key}:role:*"
    "ttl" = 3600
  }
}
```

#### droplet-roles/ex.hcl

```hcl
role "ex" {
  aud      = "api://DigitalOcean?actx={actx}"
  sub      = "actx:{actx}:plc:{did-plc-key}:role:*"
  policies = ["ex"]
}
```

### End-user

OAuth your agent's account and write a policy that allows your `did:plc:...` to
unlock access to their account.

#### roles/atproto-write.hcl

```hcl
role "atproto-write" {
  # actx here will be replaced with `did:plc:...` of your agent
  aud      = "api://ATProto?actx={actx}"
  # TODO This just happens to be the same for this PoC but in reality we would
  # configure this piror to ccb x402 (ccba is tbd if before or after x402) using
  # the ccb.wif.issuer_uri value.
  iss      = "https://droplet-oidc.its1337.com"
  # TODO Replace 4959ec0923473bf22bddd7bec2caf58a294ee007 with your actual team UUID!
  # doctl account get -o json | jq -r .team.uuid
  sub      = "actx:4959ec0923473bf22bddd7bec2caf58a294ee007:plc:5svqtrhheairglgiiyvutzik:role:atproto-write"
  policies = ["atproto-write"]
}
```

This does the replacement using `doctl` and `sed`.

```bash
sed -i "s/4959ec0923473bf22bddd7bec2caf58a294ee007/$(doctl account get -o json | jq -r .team.uuid)/g" roles/atproto-write.hcl
```

#### policies/atproto-write.hcl

```hcl
path "/xrpc/com.atproto.repo.createRecord" {
  capabilities = ["create"]
}
```

## Example

- TODO Subject from compute contract bid, need bid on disk for reference

```bash
yes | ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
SSH_PUB=$(cat ~/.ssh/id_ed25519.pub)
DID_PLC="did:plc:lpfuqerea3deuoyrn7ojser4"


URL=$(cat /root/secrets/digitalocean.com/serviceaccount/base_url)
TEAM_UUID=$(cat /root/secrets/digitalocean.com/serviceaccount/team_uuid)
ID_TOKEN=$(cat /root/secrets/digitalocean.com/serviceaccount/token)

SUBJECT="actx:${TEAM_UUID}:plc:5svqtrhheairglgiiyvutzik:role:my-cool-role"

SERVICE="$(openssl rand -hex 4)"

TOKEN=$(curl -sf \
  -H "Authorization: Bearer ${ID_TOKEN}" \
  -d@<(jq -n -c \
    --arg aud "api://ATProto?actx=${DID_PLC}" \
    --arg sub "${SUBJECT}" \
    --arg ttl 3600 \
    '{aud: $aud, sub: $sub, ttl: ($ttl | fromjson)}') \
  "${URL}/v1/oidc/issue" \
  | jq -r .token)

curl -s \
  -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
        "repo": "'"${DID_PLC}"'",
        "collection": "com.fedproxy.sshPublicKey",
        "record": {
          "$type": "com.fedproxy.sshPublicKey",
          "key": "'"${SSH_PUB}"'",
          "service": "'"${SERVICE}"'",
          "name": "'"${SERVICE}"'",
          "createdAt": "'$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")'"
        }
      }' \
  "${URL}/xrpc/com.atproto.repo.createRecord" | jq

echo "Hello World from ${SERVICE} !" > index.html

python -m http.server 8080 &

ssh -NnT -p 2222 \
  -o UserKnownHostsFile=/dev/null \
  -o StrictHostKeyChecking=no \
  -o PasswordAuthentication=no \
  -R "${SERVICE}:80:127.0.0.1:8080" \
  aliceoa.bsky.social@fedproxy.com
```
