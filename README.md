# Compute Contract Provider Relay DigitalOcean

- <https://github.com/publicdomainrelay/compute-contract>

## Testing

```bash
X402_MAKE_FREE=1 nodemon -e py --exec "clear; uv run src/compute_contract_provider_relay_digitalocean/server.py; test 1"

curl http://localhost:4021/ccr/at://did:plc:5svqtrhheairglgiiyvutzik/com.publicdomainrelay.ccb/3mld4chetvx23/bafyreihb3nbdnrsmdpovctuyhizqifnhqinmzx3ehqd43pqkud2eytbdgy | jq
```

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
