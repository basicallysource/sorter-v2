# Documentation Site

This directory is the canonical source for the project documentation site that is intended to publish to GitHub Pages.

## What lives here

- durable detector benchmark conclusions
- model and artifact documentation
- target conversion workflows
- the Pages site layout and styling

## Publishing

The GitHub Pages workflow lives in:

- `../.github/workflows/documentation-pages.yml`

It builds from `docs/`.

## Local preview

If you want to preview locally:

```bash
cd docs
bundle install
bundle exec jekyll serve
```

If local Ruby gets in the way, use the Docker-based workflow described below. The GitHub Pages workflow is the authoritative CI build path.

## Local Docker build

The most reliable local test path is a disposable Ruby 3.1 container:

```bash
./local-jekyll.sh build
```

This gives you a real local build check without needing GitHub Pages to be enabled yet.

For a local preview server on `http://127.0.0.1:4000`:

```bash
./local-jekyll.sh serve
```

## Images

Keep full-resolution originals in `docs/_img-src/`, mirroring the path they'll be
served at under `docs/assets/img/`. Originals live in Git LFS and are never
deployed (Jekyll ignores underscore-prefixed dirs).

Regenerate the web-friendly versions before pushing whenever `_img-src` changes:

```bash
python3 docs/scripts/optimize_images.py
```

It downscales each original (long side ≤ 1600px) and writes a progressive JPEG
(opaque images) or optimized PNG (transparent images) to the matching path under
`docs/assets/img/`. Pages reference those `assets/img/...` paths — `.jpg` for
photos, `.png` for transparent renders. Commit both the original and the
generated web version.
