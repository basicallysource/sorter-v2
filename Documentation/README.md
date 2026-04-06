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

It builds from `Documentation/` so we are not tied to GitHub's built-in `/docs` source-folder convention.

## Local preview

If you want to preview locally:

```bash
cd Documentation
bundle install
bundle exec jekyll serve
```

If macOS picks up the system `/usr/bin/bundle`, you may need to switch to a newer Ruby toolchain first. The GitHub Pages workflow is the authoritative build path.
