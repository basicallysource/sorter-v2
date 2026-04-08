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
