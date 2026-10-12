# Security Policy

## Supported versions

Soularr is a small, volunteer-maintained project. Security fixes are made on `main` and ship in the next release.

| Version | Supported |
| --- | --- |
| `main` (Docker `:latest`) | ✅ |
| Latest release (currently `v1.2.x`) | ✅ |
| Older releases | ❌ Please update first |

The Docker images (`mrusse08/soularr` on Docker Hub, `ghcr.io/mrusse/soularr`) are built from this repository, so they are covered too.

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub instead:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Fill in the form.

Only the maintainers can see the report.

If the **Report a vulnerability** button isn't there, open a regular issue titled "Security contact request". Leave out all details of the problem; a maintainer will reply with a private way to send them. It's helpful to include:

- the Soularr version or commit, and whether you run the Docker image or the script directly;
- what an attacker needs: network access to the web UI, control of a Soulseek peer, access to Lidarr or slskd, and so on;
- steps to reproduce, or a proof of concept;
- what they can achieve (read secrets, modify or delete files, run code, ...);
- a suggested fix, if you have one.

This is a volunteer project, so responses depend on the maintainers' availability. We will acknowledge the report, keep you updated on a fix, and credit you in the release notes unless you would rather not be named. Please give us a reasonable amount of time to release a fix before you disclose the issue publicly.

## Scope

**In scope:** anything in this repository: `soularr.py`, the web UI (`webui/`), `run.sh` and the Docker image.

**Out of scope here** (please report to the relevant project instead):

- [slskd](https://github.com/slskd/slskd), [Lidarr](https://github.com/Lidarr/Lidarr) and the Soulseek network;
- the [`slskd-api`](https://pypi.org/project/slskd-api/), [`pyarr`](https://pypi.org/project/pyarr/) and [`music-tag`](https://pypi.org/project/music-tag/) libraries. If one of them makes Soularr exploitable, a report here is still welcome so we can pin or work around it.

## Running Soularr safely

Soularr is designed to run on a trusted home network next to slskd and Lidarr.

- **Do not expose the web UI (port `8265`) to the internet.** It has no login. Anyone who can reach it can read `config.ini`, including the slskd and Lidarr API keys, and can change it. If you don't use the web UI, turn it off with `WEBUI_ENABLED=false`. If you need remote access, put it behind a VPN or a reverse proxy that requires authentication.
- **Treat `config.ini` as a secret.** It holds your slskd and Lidarr API keys. Keep it readable only by the user Soularr runs as, and give slskd its own API key rather than reusing the Lidarr one.
- **Run the container as a non-root user** (the `user:` setting in the Docker Compose example), and mount only the directories Soularr needs.
- **Files from Soulseek come from untrusted peers.** Soularr moves downloads into Lidarr's import folder and edits their tags. Keep slskd's download directory separate from anything else you care about.
