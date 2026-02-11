"""Domain service — availability checking, pricing, and domain choice storage.

Uses:
- Direct RDAP HTTP queries for real-time domain availability checks against
  actual registry databases (Verisign for .com/.net, etc.).
- python-whois as a fallback for TLDs not covered by RDAP (like .co, .io, .me).
- Cloudflare Domain Pricing API (cfdomainpricing.com) for live wholesale
  TLD pricing. Cached in memory with a 24-hour TTL.

No API keys or accounts required. No bootstrap step.
"""

import logging
import time
from datetime import datetime, timezone

import requests
import whois

from app.extensions import db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Cloudflare Pricing Cache
# ──────────────────────────────────────────────

CF_PRICING_URL = "https://cfdomainpricing.com/prices.json"
_cf_prices: dict = {}
_cf_prices_fetched: float = 0
CF_CACHE_TTL = 86400  # 24 hours


def _get_cf_prices() -> dict:
    """Return cached Cloudflare TLD pricing, refreshing if stale or empty."""
    global _cf_prices, _cf_prices_fetched

    if time.time() - _cf_prices_fetched > CF_CACHE_TTL or not _cf_prices:
        try:
            resp = requests.get(CF_PRICING_URL, timeout=10)
            resp.raise_for_status()
            _cf_prices = resp.json()
            _cf_prices_fetched = time.time()
            logger.info(
                f"Refreshed Cloudflare pricing: {len(_cf_prices)} TLDs loaded"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch Cloudflare pricing: {e}")
    return _cf_prices


# ──────────────────────────────────────────────
# RDAP — Direct HTTP queries (primary method)
# ──────────────────────────────────────────────

IANA_RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
_rdap_servers: dict = {}
_rdap_servers_fetched: float = 0
RDAP_CACHE_TTL = 86400  # 24 hours


def _get_rdap_servers() -> dict:
    """Load RDAP server mapping from IANA bootstrap, cached 24h."""
    global _rdap_servers, _rdap_servers_fetched

    if time.time() - _rdap_servers_fetched > RDAP_CACHE_TTL or not _rdap_servers:
        try:
            resp = requests.get(IANA_RDAP_BOOTSTRAP_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            servers = {}
            for entry in data.get("services", []):
                tlds = entry[0]
                urls = entry[1]
                if urls:
                    rdap_url = urls[0]
                    if not rdap_url.endswith("/"):
                        rdap_url += "/"
                    for tld in tlds:
                        servers[tld.lower()] = rdap_url

            _rdap_servers = servers
            _rdap_servers_fetched = time.time()
            logger.info(f"Loaded IANA RDAP bootstrap: {len(servers)} TLDs")
        except Exception as e:
            logger.warning(f"Failed to fetch IANA RDAP bootstrap: {e}")

    return _rdap_servers


def _rdap_check(domain: str, tld: str) -> bool | None:
    """Query RDAP to check if a domain is registered.

    Returns:
        True  = domain is registered (taken)
        False = domain is available
        None  = couldn't determine (no RDAP server for this TLD)
    """
    servers = _get_rdap_servers()
    rdap_base = servers.get(tld)

    if not rdap_base:
        return None  # No RDAP server → fall through to WHOIS

    url = f"{rdap_base}domain/{domain}"

    try:
        resp = requests.get(
            url,
            headers={"Accept": "application/rdap+json"},
            timeout=8,
            allow_redirects=True,
        )

        if resp.status_code == 200:
            return True   # Domain exists = taken
        elif resp.status_code == 404:
            return False  # Not found = available
        else:
            logger.warning(f"RDAP returned {resp.status_code} for {domain}")
            return None
    except requests.exceptions.Timeout:
        logger.warning(f"RDAP timeout for {domain}")
        return None
    except Exception as e:
        logger.warning(f"RDAP request failed for {domain}: {e}")
        return None


# ──────────────────────────────────────────────
# WHOIS — Fallback for TLDs without RDAP
# ──────────────────────────────────────────────

def _whois_check(domain: str) -> bool | None:
    """Query WHOIS to check if a domain is registered.

    Returns:
        True  = domain is registered (taken)
        False = domain is available
        None  = couldn't determine
    """
    try:
        w = whois.whois(domain)

        # python-whois returns an object even for available domains,
        # but domain_name will be None/empty if the domain doesn't exist.
        if w.domain_name:
            return True   # Registered
        else:
            return False  # Available (no domain_name in response)

    except whois.exceptions.WhoisDomainNotFoundError:
        # "No match" / "Domain not found" → available
        return False
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "no match" in error_str:
            return False
        logger.warning(f"WHOIS lookup failed for {domain}: {e}")
        return None


# ──────────────────────────────────────────────
# TLD Extraction
# ──────────────────────────────────────────────

def _extract_tld(domain: str) -> str:
    """Extract the TLD from a domain name.

    Handles multi-part TLDs like co.uk, com.au, etc.
    """
    domain = domain.lower().strip().rstrip(".")

    multi_part_tlds = [
        "co.uk", "me.uk", "net.uk", "org.uk",
        "co.nz", "net.nz", "org.nz", "geek.nz",
        "com.mx", "org.mx",
        "com.co", "net.co", "nom.co",
        "com.ai", "net.ai", "off.ai", "org.ai",
    ]
    for tld in multi_part_tlds:
        if domain.endswith(f".{tld}"):
            return tld

    parts = domain.rsplit(".", 1)
    if len(parts) == 2:
        return parts[1]
    return ""


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def check_domain_availability(domain_name: str, price_limit: float = 25.00) -> dict:
    """Check if a domain is available and get its Cloudflare wholesale price.

    Strategy: Try RDAP first (fastest, most accurate). If no RDAP server
    exists for the TLD, fall back to WHOIS (covers virtually everything).

    Args:
        domain_name: Full domain (e.g. "mariospizza.com")
        price_limit: Max annual price considered "included" (default $25)

    Returns dict with keys:
        available (bool): Whether the domain is unregistered
        domain (str): The cleaned domain name
        tld (str): The extracted TLD
        price (float|None): Annual registration price from Cloudflare, or None
        renewal (float|None): Annual renewal price, or None
        within_budget (bool): True if price <= price_limit
        price_source (str): "cloudflare" or "unknown"
        error (str|None): Error message if check failed
    """
    domain_name = domain_name.lower().strip().rstrip(".")

    if not domain_name or "." not in domain_name:
        return {"error": "Please enter a valid domain name (e.g. mybusiness.com)"}

    # Strip protocol/path if user pasted a URL
    if "://" in domain_name:
        domain_name = domain_name.split("://", 1)[1]
    domain_name = domain_name.split("/")[0]

    # Strip www. prefix — users often type it but it's a subdomain,
    # not a registrable domain. "www.test.com" → "test.com"
    if domain_name.startswith("www."):
        domain_name = domain_name[4:]

    tld = _extract_tld(domain_name)
    if not tld:
        return {"error": "Could not determine the domain extension (e.g. .com)"}

    # --- Tier 1: RDAP (fast, direct HTTP) ---
    result = _rdap_check(domain_name, tld)

    # --- Tier 2: WHOIS fallback ---
    if result is None:
        logger.info(f"No RDAP for .{tld}, falling back to WHOIS for {domain_name}")
        result = _whois_check(domain_name)

    # --- Both failed ---
    if result is None:
        return {
            "error": (
                f"We couldn't verify .{tld} availability right now. "
                "Please try again in a moment, or try a .com domain."
            )
        }

    available = not result  # True=taken from checkers, flip for our API

    # --- Look up pricing from Cloudflare ---
    cf_prices = _get_cf_prices()
    tld_pricing = cf_prices.get(tld)

    price = None
    renewal = None
    price_source = "unknown"
    within_budget = False

    if tld_pricing:
        price = tld_pricing.get("registration")
        renewal = tld_pricing.get("renewal")
        price_source = "cloudflare"
        if price is not None:
            within_budget = price <= price_limit

    return {
        "available": available,
        "domain": domain_name,
        "tld": tld,
        "price": price,
        "renewal": renewal,
        "within_budget": within_budget,
        "price_source": price_source,
        "error": None,
    }


def save_domain_choice(
    site_id: str,
    choice_type: str,
    domain: str | None = None,
    price: float | None = None,
    self_purchase: bool = False,
) -> bool:
    """Save the client's domain selection to their Site record.

    Args:
        site_id: The Site.id to update
        choice_type: One of "search_new", "own_domain", "keep_subdomain"
        domain: The selected domain name (required for search_new / own_domain)
        price: Annual price from Cloudflare (only for search_new)
        self_purchase: True if domain is over budget and client buys it

    Returns True on success, False if site not found.
    """
    from app.models.site import Site

    site = db.session.get(Site, site_id)
    if not site:
        return False

    site.domain_choice = choice_type
    site.requested_domain = domain
    site.requested_domain_price = price
    site.domain_self_purchase = self_purchase
    site.domain_choice_at = datetime.now(timezone.utc)

    db.session.commit()
    logger.info(
        f"Domain choice saved for site {site_id}: "
        f"{choice_type} / {domain} / ${price} / self_purchase={self_purchase}"
    )
    return True
