# Deployment preparation

The approved public architecture is a static research site with a historical-snapshot engine demo. The local Git repository is initialized and its `origin` is `https://github.com/RetroMrii/polyBTCv2.git`. The website links to that repository by default. No hosted website URL has been verified. See [publication readiness](PUBLICATION_READINESS.md) before release.

The owner selected frontend-only publication. No hosted backend is required or planned for this release; the existing backend remains a local development and monitoring tool.

## Build artifact

Run `npm ci` and `npm run build` in `dashboard/frontend`. Serve the resulting `dist/` directory with any static host. The site uses relative assets and hash routes, so both domain-root and repository-subpath hosting are supported without application-server rewrites. HTTPS and ordinary static-file caching are sufficient; invalidate HTML and version publication assets with a release when evidence changes.

Optional build variables:

| Variable | Purpose |
|---|---|
| `VITE_GITHUB_URL` | Optional HTTPS GitHub URL override; defaults to `https://github.com/RetroMrii/polyBTCv2`, matching the configured remote. |
| `VITE_ENABLE_LOCAL_MONITOR` | Defaults off in production. Use `true` only for a local production preview with the local API. Never enable merely to publish the static site. |

The public historical demo reads bundled, sanitized records. It does not call the FastAPI backend, load model binaries, access local files, make market requests or launch processes. Source exports use market aliases and explicit historical timestamps. Calibration rows are labelled fitting data. No live status or profit claim is inferred.

## Local monitor

The existing backend binds to loopback and retains GET-only APIs, Host/CORS restrictions, query deadlines and read-only SQLite access. `/api/settings` contains local source paths by design for local diagnostics. **Do not expose this backend unchanged publicly.** Public deployment does not require it. Existing local dashboard scripts and operational workflows remain available; starting collectors or paper runtimes is a separate action.

The development site (`npm run dev`) provides an “Open local monitor” link and preserves the original hash-page names. Run the backend separately using the existing documented command when local monitoring is desired. Refresh existing frontend development servers after changing content; no operational process restart is needed for publications.

## Before publication

1. Review the existing repository's proposed changes and resolve the publication-readiness findings. Verify `origin` still points to the intended repository and rebuild the website. Review the proposed file set rather than adding the entire workspace.
2. Keep environments, raw data, model binaries, operational databases, private configuration, account exports, local logs and test/build caches excluded. Review curated evidence for redistribution rights as well as privacy.
3. Select hosting/domain, verify production navigation, downloads and mobile rendering at its actual base path, and approve the exact release artifact.
4. Obtain explicit approval before pushing code, changing visibility or deploying publicly. Verify the resulting public URL before adding it to README.

No credentials, accounts, purchases, repository visibility changes or external publication were performed during the transformation. Existing public-content approval does not itself establish data licensing permission.
