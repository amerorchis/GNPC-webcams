# TODO (future, not urgent)

## Runner platform deadline — 2026-09-16

GitHub drops support for Linux ARM32 self-hosted runners after 16 September 2026.
`gnpic` runs a 32-bit (`armhf`) userland on a 64-bit kernel, so the deploy job in
`.github/workflows/ci.yml` will stop working on that date. This also affects the
existing runners for `email-testing` and `glacier_daily`.

Options:

- **Reinstall the Pi with 64-bit Raspberry Pi OS.** Keeps all three runners working
  and is the only fix that preserves the current setup. Biggest disruption — pyenv,
  `.venv`, `environment.env`, fonts, and every cron entry have to be rebuilt.
- **Switch deploy to SSH over Tailscale.** Runs on a GitHub-hosted runner and SSHes
  into the Pi, so no ARM runner is involved. `glacier_daily` already deploys this way
  and the OAuth client exists; this repo would need its own `TS_OAUTH_CLIENT_ID`,
  `TS_OAUTH_SECRET`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`, `DEPLOY_PATH`
  secrets. `scripts/deploy.sh` runs unchanged on the far side.
- **Cron poll on the Pi.** Extend `~/Modules/update_repos.sh` to run more often and
  call `scripts/deploy.sh`, gating on the GitHub API's check status for `origin/main`.
  No secrets and no inbound access, at the cost of deploy latency and losing the
  deploy log from the Actions UI.

## West-side cameras — glacier.org blocks still to add

The eight west-side NPS cameras are published by this pipeline as of 2026-08-11
(`apgar_mtn`, `apgar_village`, `lake_mcdonald`, `lake_mcdonald2`,
`apgar_visitor_center`, `middle_fork`, `headquarters`, `west_entrance`). What is
left is the website side — each one needs its own block on glacier.org/webcams,
and the copy-paste traps there are: the `alt` and both `title` attributes on the
image, a unique `id` on the image div, that same slug added to `CAMERA_IDS` in the
`glacier-webcams` plugin's `refresh.js`, a unique `countdown` id, and the
sunrise/sunset div ids. Until that is done the processed images are being uploaded
but nothing displays them.

Two entries on the NPS page remain non-candidates: **Many Glacier - 2** still has a
heading and write-up but no image element at all, dead on their side; and **Logan
Pass 2** is `smv_nps.jpg`, already in this pipeline.
