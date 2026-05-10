# Compute Contract Provider Relay DigitalOcean

- <https://github.com/publicdomainrelay/compute-contract>

## Testing

```bash
python -m venv .venv && . .venv/bin/activate && uv pip install -e .[dev]

. .venv/bin/activate

RBAC_REPO_ROOT="${HOME}/src/rbac/do/wid-atp" X402_MAKE_FREE=1 nodemon -e py --exec "clear; uv run -m compute_contract_provider_relay_digitalocean.server; test 1"

curl http://localhost:4021/ccr/at://did:plc:5svqtrhheairglgiiyvutzik/com.publicdomainrelay.temp.ccba/3mlagijgoeb23/bafyreiamisq3yqgb4k3tdojmzvvzpuwj46ytwbj672zxhyxxl7t36qadz4 | jq

$ npx awal x402 pay https://compute-contract.johnandersen777.bsky.social.fedproxy.com/ccr/at://did:plc:5svqtrhheairglgiiyvutzik/com.publicdomainrelay.temp.ccba/3mlagijgoeb23/bafyreiamisq3yqgb4k3tdojmzvvzpuwj46ytwbj672zxhyxxl7t36qadz4
✓ Request completed (HTTP 200)

Response:
{
  "id": "3mld67yj3xo2u",
  "uri": "at://did:plc:5svqtrhheairglgiiyvutzik/com.publicdomainrelay.temp.ccr/3mld67yj3xo2u",
  "cid": "bafyreibzynxkkoxxvppbfoeh5s2s2asrm2j7ziw2ol5ufau4q25d7ousiy"
}
```

The `/ccr` route takes the **CCBA** (Compute Contract Bid Accept) AT URI/CID,
not the CCB. The provider resolves the CCBA, then resolves the CCB and CCRFP
it references, validates that the CCBA's embedded CCRFP matches the one the
CCB embedded, spins the compute, and writes a CCR record referencing CCRFP,
CCB, and CCBA.

All record collection / `$type` names live under the
`com.publicdomainrelay.temp.*` namespace while the schemas are pre-stable
(e.g. `com.publicdomainrelay.temp.ccrfp`). Once stable they will move to
`com.publicdomainrelay.<name>` and evolve additively; genuine breaking
changes get a numeric suffix (`ccrfpV2`, `ccrfpV3`, …). Lexicons for every
type live in this repo under [`lexicons/`](./lexicons) and upstream at
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
