from virlo_exporter.api.billing import BillingClass, BillingSafety


def test_billing_classifier() -> None:
    assert BillingSafety.classify("GET", "/agents") == BillingClass.FREE_READ
    assert BillingSafety.classify("POST", "/agents") == BillingClass.PAID_ACTION
    assert BillingSafety.classify("POST", "/agents/suggest-keywords") == BillingClass.FREE_READ
    assert BillingSafety.classify("GET", "/agents/id/hooks") == BillingClass.CONDITIONAL_COST
    assert (
        BillingSafety.classify("GET", "/agents/id/hooks", data_intelligence_enabled=True)
        == BillingClass.FREE_READ
    )
    assert BillingSafety.classify("GET", "/trends") == BillingClass.CONDITIONAL_COST


def test_estimate_and_headers() -> None:
    assert BillingSafety.estimate_agent(data_intelligence=False).total == 0.5
    assert BillingSafety.estimate_agent(data_intelligence=True).total == 1.5
    cost, balance = BillingSafety.response_cost(
        {"x-credits-used": "150", "x-credits-remaining": "1850"}
    )
    assert cost == 1.5
    assert balance == 18.5
