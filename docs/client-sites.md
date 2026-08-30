# Client sites

This repository is the Belvieu Digital **control plane** (`https://portal.belvieudigital.com`). It does **not** generate, build, or host client websites. It stores slugs, preview and production URLs, and billing state.

Client sites are designed and shipped in their own repos. The full design and build law lives in [`cnichols1734/waas-researcher`](https://github.com/cnichols1734/waas-researcher). Do not duplicate that law here.

## What a client site is

- One production-quality custom one-pager per business. No template generator.
- Stack: Astro + TypeScript, static output, no UI library.
- Business data lives in `src/data/site.ts`. Each site ships `PRODUCT.md` and `DESIGN.md`.
- Unique visual concept per business. No AI slop. No em dashes in client copy. No Inter, Roboto, Arial, Helvetica, system UI, or Space Grotesk.

## Repos and hosting

- One GitHub repository per business in the Belvieu Digital GitHub org. Deploy from that repo.
- Host on Cloudflare Workers Static Assets. Also compatible with Cloudflare Pages.
- Temporary `workers.dev` preview first. Attach a custom domain later without changing architecture.

## How the portal records a site

1. The site is built in its own repo. In Cursor, use grok-4.6 xhigh fast only.
2. QA is a dedicated Belvieu QA bot (not JARVIS).
3. After QA PASS, Johnny 5 writes the live URL onto the portal record (`prospects.demo_url` and/or `sites.published_url`).
4. The portal tracks URLs only. There is no site generator and no Cloudflare deploy API in this repo.

## Pointers

| What | Where |
|---|---|
| Portal architecture, auth, billing, tickets | [`CLAUDE.md`](../CLAUDE.md) |
| Client-site design and build law | [`cnichols1734/waas-researcher`](https://github.com/cnichols1734/waas-researcher) |
