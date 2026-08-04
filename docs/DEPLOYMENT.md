# Production deployment

This project uses GitHub-hosted CI and a narrowly scoped SSH deploy step. The VPS never runs pull-request CI.

## One-time VPS setup

Install Docker Engine, Docker Compose v2, `curl`, and `flock`. Create a non-root deployment user in the Docker group, clone this repository into the chosen `PRODUCTION_PATH`, and create its runtime `.env` on the host. Do not commit or upload that file.

Create a dedicated SSH key for the deployment user, add its public half to `authorized_keys`, and add the server host key to the GitHub environment's `DEPLOY_KNOWN_HOSTS` secret using `ssh-keyscan` from a trusted operator workstation. The host should have a GHCR token with read-only package access.

The compose file expects the normal runtime variables from `.env`, including database, Redis, Telegram, Stripe, and administrator settings. Add `DISCORD_BOT_TOKEN` only when enabling the `discord` Compose profile. `DISCORD_GUILD_ID` is optional and is intended only for development slash-command registration.

## GitHub configuration

Create a protected `production` environment and set these environment secrets:

- `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`
- `PRODUCTION_PATH`
- `GHCR_DEPLOY_TOKEN`

`deploy.yml` builds immutable images tagged with the commit SHA after the `Quality` workflow succeeds on `main`, then calls `scripts/deploy.sh` over verified SSH. Pull requests never deploy and do not receive production secrets.

## Operational checks and rollback

After an initial deployment, verify `curl --fail http://127.0.0.1/healthz` on the VPS and `docker compose ps`. The script runs Alembic once before recreating services and retains the previous image tag in `.deploy-image.env`.

If health verification fails, inspect `docker compose logs`. Redeploy a known previous SHA via **Run workflow** only when it remains compatible with the current schema. Do not automatically run Alembic downgrades: the restaurant-primary constraint downgrade is data-dependent and fails if duplicate references were created after its removal. To pause automation, disable the Deploy workflow in GitHub Actions; manual deployments remain available through `workflow_dispatch`.
