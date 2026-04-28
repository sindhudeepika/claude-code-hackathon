"""
Contract tests — API response shape and field validation.
These define the public contract of the customer portal API.
If these break after a code change, a consumer of the API will be affected.
"""

import pytest

pytestmark = pytest.mark.usefixtures("webapp_available")

KNOWN_CUSTOMER_ID = "a1b2c3d4-0001-0001-0001-000000000001"


@pytest.mark.contract
def test_customers_list_shape(http, webapp_url):
    resp = http.get(f"{webapp_url}/api/customers", timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "pagination" in body
    assert isinstance(body["data"], list)


@pytest.mark.contract
def test_customers_list_pagination_fields(http, webapp_url):
    resp = http.get(f"{webapp_url}/api/customers?page=1&limit=5", timeout=10)
    pagination = resp.json()["pagination"]
    for field in ("page", "limit", "total", "pages"):
        assert field in pagination, f"Missing pagination field: {field}"
    assert pagination["page"] == 1
    assert pagination["limit"] == 5


@pytest.mark.contract
def test_customer_record_has_required_fields(http, webapp_url):
    resp = http.get(f"{webapp_url}/api/customers/{KNOWN_CUSTOMER_ID}", timeout=10)
    assert resp.status_code == 200
    customer = resp.json()
    required_fields = ["id", "first_name", "last_name", "email", "created_at"]
    for field in required_fields:
        assert field in customer, f"Missing required field: {field}"


@pytest.mark.contract
def test_customer_email_is_redacted_by_default(http, webapp_url):
    """PII rule: email must be redacted in external API responses."""
    resp = http.get(f"{webapp_url}/api/customers/{KNOWN_CUSTOMER_ID}", timeout=10)
    assert resp.status_code == 200
    customer = resp.json()
    email = customer.get("email", "")
    assert "***" in email or email == "", (
        f"Email is not redacted in external response: {email!r}. "
        "PII must be redacted unless X-PII-Scope: internal header is present."
    )


@pytest.mark.contract
def test_customer_phone_is_redacted_by_default(http, webapp_url):
    resp = http.get(f"{webapp_url}/api/customers/{KNOWN_CUSTOMER_ID}", timeout=10)
    customer = resp.json()
    phone = customer.get("phone", "")
    if phone:
        assert "***" in phone, (
            f"Phone is not redacted in external response: {phone!r}. PII must be redacted."
        )


@pytest.mark.contract
def test_transactions_list_shape(http, webapp_url):
    resp = http.get(
        f"{webapp_url}/api/customers/{KNOWN_CUSTOMER_ID}/transactions",
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "pagination" in body
    assert isinstance(body["data"], list)


@pytest.mark.contract
def test_transaction_record_has_required_fields(http, webapp_url):
    resp = http.get(
        f"{webapp_url}/api/customers/{KNOWN_CUSTOMER_ID}/transactions?limit=1",
        timeout=10,
    )
    body = resp.json()
    if not body["data"]:
        pytest.skip("No transactions for test customer — check seed data")
    tx = body["data"][0]
    for field in ("id", "amount", "description", "transaction_date", "status"):
        assert field in tx, f"Missing transaction field: {field}"


@pytest.mark.contract
def test_transactions_for_unknown_customer_returns_404(http, webapp_url):
    resp = http.get(
        f"{webapp_url}/api/customers/00000000-0000-0000-0000-000000000000/transactions",
        timeout=10,
    )
    assert resp.status_code == 404
    assert "error" in resp.json()


@pytest.mark.contract
def test_customers_list_limit_capped_at_100(http, webapp_url):
    resp = http.get(f"{webapp_url}/api/customers?limit=9999", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["pagination"]["limit"] <= 100
