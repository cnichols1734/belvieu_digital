"""Stripe Price objects are not dicts — inspect helpers must never call .get()."""

from types import SimpleNamespace

from app.services.stripe_inspect import inspect_price, stripe_field


class FakePrice:
    """Mimics stripe-python: attribute access works, .get() raises."""

    def __init__(self):
        self.id = "price_1UAgcMKSxANgFgSZAGzo01na"
        self.unit_amount = 2900
        self.livemode = True
        self.active = True
        self.recurring = SimpleNamespace(interval="month")
        self.product = SimpleNamespace(
            id="prod_TxGMXnDfDlxyB9",
            name="Monthly Website Hosting",
            active=True,
        )

    def get(self, *args, **kwargs):
        raise TypeError(
            "'get' is a dict method, but a Price is not a dict. "
            "Use .to_dict() to convert it."
        )


def test_stripe_field_reads_attributes():
    obj = SimpleNamespace(name="Monthly Website Hosting")
    assert stripe_field(obj, "name") == "Monthly Website Hosting"
    assert stripe_field(obj, "missing", "fallback") == "fallback"


def test_stripe_field_reads_dicts():
    assert stripe_field({"active": True}, "active") is True
    assert stripe_field(None, "active", False) is False


def test_inspect_price_does_not_call_get():
    info = inspect_price(FakePrice(), "Live")
    assert info["status"] == "ok"
    assert info["amount"] == 29.0
    assert info["amount_label"] == "$29.00/month"
    assert info["product_name"] == "Monthly Website Hosting"
    assert info["id"] == "price_1UAgcMKSxANgFgSZAGzo01na"
    assert info["issues"] == []


def test_inspect_price_flags_mode_mismatch():
    price = FakePrice()
    info = inspect_price(price, "Test")
    assert info["status"] == "warn"
    assert any("mode mismatch" in issue for issue in info["issues"])


def test_inspect_price_flags_inactive_product():
    price = FakePrice()
    price.product.active = False
    info = inspect_price(price, "Live")
    assert info["status"] == "error"
    assert any("not active" in issue for issue in info["issues"])


def test_inspect_price_one_time():
    price = FakePrice()
    price.recurring = None
    price.unit_amount = 19100
    info = inspect_price(price, "Live")
    assert info["amount_label"] == "$191.00 one-time"
    assert info["interval"] is None
