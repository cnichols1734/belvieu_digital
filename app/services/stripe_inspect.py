"""Read Stripe API resources without treating them as dicts.

stripe-python Price/Product objects raise if you call .get() —
"'get' is a dict method, but a Price is not a dict."
"""


def stripe_field(obj, name, default=None):
    """Read a field from a StripeObject or a plain dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def inspect_price(price, key_mode):
    """Normalize a retrieved Stripe Price into a plain dict for templates."""
    product = stripe_field(price, "product")
    if isinstance(product, str):
        product_name = None
        product_active = None
        product_id = product
    else:
        product_name = stripe_field(product, "name")
        product_active = stripe_field(product, "active")
        product_id = stripe_field(product, "id")

    unit_amount = stripe_field(price, "unit_amount") or 0
    recurring = stripe_field(price, "recurring")
    interval = stripe_field(recurring, "interval") if recurring else None
    livemode = bool(stripe_field(price, "livemode"))
    active = stripe_field(price, "active", True)
    price_id = stripe_field(price, "id")

    mode_match = (livemode and key_mode == "Live") or (
        not livemode and key_mode == "Test"
    )

    status = "ok"
    issues = []
    if product_active is False:
        status = "error"
        issues.append("product is not active")
    if active is False:
        status = "error"
        issues.append("price is not active")
    if not mode_match:
        if status == "ok":
            status = "warn"
        issues.append(
            f"mode mismatch (price={'Live' if livemode else 'Test'}, key={key_mode})"
        )

    amount_label = f"${unit_amount / 100:.2f}"
    if interval:
        amount_label += f"/{interval}"
    else:
        amount_label += " one-time"

    return {
        "id": price_id,
        "product_name": product_name or "Untitled product",
        "product_id": product_id,
        "amount": unit_amount / 100,
        "amount_label": amount_label,
        "interval": interval,
        "livemode": livemode,
        "active": bool(active),
        "product_active": product_active,
        "mode_match": mode_match,
        "status": status,
        "issues": issues,
    }
