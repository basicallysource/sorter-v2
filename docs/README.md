# Documentation Site

Jekyll static site, the canonical source for Sorter project documentation.
Deployed via Vercel.

## Publishing and PR previews

- Push to `main` → production deploy.
- Push to any other branch → automatic preview deployment. The stable
  per-branch preview URL is
  `https://sorter-v2-docs-git-<branch>-spencer-huberts-projects.vercel.app`,
  publicly viewable, always tracking the branch's latest push. Send that link
  to reviewers; merge to `main` once approved.

## Local preview

```bash
./docs/serve.sh start
```

Runs Jekyll at `http://localhost:4000` with livereload. `./serve.sh
{status|logs|restart|stop}`. For a containerized build check without local
Ruby: `./docs/local-jekyll.sh build` (or `serve`).

## Images

Images are **not stored in git**. Full-resolution originals and web-optimized
versions live in the `basically-docs` DigitalOcean Spaces bucket, served
through a Cloudflare Worker (`docs/scripts/img-worker/`) at
`https://img.basically.website`.

To add an image:

```bash
python3 docs/scripts/upload_image.py <original-file> <dest-path>
```

Example: `python3 docs/scripts/upload_image.py ~/Downloads/IMG_1234.jpg
assembly/top-interface/step1` uploads the original to `originals/…` and a
web-friendly version (long side ≤ 1600px, opaque → progressive `.jpg`,
transparent → `.png`) to `web/…`, then prints the URLs. Reference the printed
`https://img.basically.website/web/…` URL in the page.

Names are immutable (the CDN caches for 30 days): if an image's content
changes, upload it under a new name. The script refuses to overwrite an
existing name unless `--force`.

Credentials live in `~/.config/basically/do-spaces.env` (`SPACES_KEY` /
`SPACES_SECRET`), not in the repo.

See `AGENTS.md` in this directory for the full authoring playbook.
