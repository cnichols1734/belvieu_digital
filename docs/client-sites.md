# Client sites

This repository is the Belvieu Digital **control plane** (`https://portal.belvieudigital.com`). It does **not** generate, build, or host client websites. It stores slugs, preview and production URLs, and billing state.

Client sites live in separate repositories. This portal records their URLs only.

## Stack and hosting

- Stack: Astro + TypeScript, static output.
- One GitHub repository per business in the Belvieu Digital GitHub org.
- Host on Cloudflare Workers Static Assets (also compatible with Cloudflare Pages).

## How the portal records a site

After a site exists, Ellis records the live URL on the portal (`prospects.demo_url` and/or `sites.published_url`).

The portal tracks URLs only. There is no site generator and no Cloudflare deploy API in this repo.

## Pointers

| What | Where |
|---|---|
| Portal architecture, auth, billing, tickets | [`CLAUDE.md`](../CLAUDE.md) |
