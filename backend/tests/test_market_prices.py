import json

import pytest

from agent import Assistant
from market_prices import DAILY_REPORT_URL, lookup_market_price_data


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


MARKETS = [
    {
        "market_id": 153,
        "market_name": "APMC Latur",
        "district_id": 355,
        "district_name": "Latur",
        "state_id": 20,
        "state_name": "Maharashtra",
    },
    {
        "market_id": 161,
        "market_name": "Lasalgaon APMC",
        "district_id": 361,
        "district_name": "Nashik",
        "state_id": 20,
        "state_name": "Maharashtra",
    },
]


def report_for(commodity_name, market_name, minimum, maximum, modal):
    return {
        "success": True,
        "title": "Market-wise, Commodity-wise Daily Report on: 10-Aug-2026",
        "states": [
            {
                "stateId": 20,
                "stateName": "Maharashtra",
                "markets": [
                    {
                        "marketId": 153 if "Latur" in market_name else 161,
                        "marketName": market_name,
                        "commodities": [
                            {
                                "commodityId": 23,
                                "commodityName": commodity_name,
                                "data": [
                                    {
                                        "marketCenter": market_name,
                                        "minimumPrice": minimum,
                                        "maximumPrice": maximum,
                                        "modalPrice": modal,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_onion_nashik_parses_actual_daily_report_shape_and_post_ids():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        if request.full_url == "https://api.agmarknet.gov.in/v1/market-district-state":
            return FakeResponse(MARKETS)
        return FakeResponse(report_for("Onion", "Lasalgaon APMC", 800, 2805, 2375))

    result = lookup_market_price_data("onion", "Nashik", opener=opener)
    body = json.loads(requests[1].data)

    assert requests[1].method == "POST"
    assert requests[1].full_url == DAILY_REPORT_URL
    assert body["marketIds"] == [161]
    assert body["stateIds"] == [20]
    assert body["includeExcel"] is False
    assert requests[1].headers["Origin"] == "https://agmarknet.gov.in"
    assert result["data"] == [
        {
            "commodity": "Onion",
            "market": "Lasalgaon APMC",
            "district": "Nashik",
            "minimum_price": 800,
            "maximum_price": 2805,
            "modal_price": 2375,
            "date": "2026-08-10",
        }
    ]


def test_cotton_latur_actual_no_data_does_not_fabricate_price():
    def opener(request, timeout):
        if request.full_url.endswith("market-district-state"):
            return FakeResponse([MARKETS[0]])
        return FakeResponse(
            {
                "success": True,
                "title": "Market-wise, Commodity-wise Daily Report on: 10-Aug-2026",
                "states": [{"stateId": 20, "stateName": "Maharashtra", "markets": []}],
            }
        )

    result = lookup_market_price_data("cotton", "Latur", opener=opener)

    assert result["status"] == "NO_DATA"
    assert result["data"] == []
    assert "price" not in result["message"].lower() or "no matching" in result["message"]


def test_timeout_returns_graceful_failure():
    def opener(request, timeout):
        raise TimeoutError("request timed out")

    result = lookup_market_price_data("wheat", "Pune", opener=opener)

    assert result["status"] == "ERROR"
    assert result["data"] == []
    assert "failed" in result["message"]


@pytest.mark.asyncio
async def test_tool_accepts_crop_and_district(monkeypatch):
    captured = {}

    def fake_lookup(crop, district):
        captured["crop"] = crop
        captured["district"] = district
        return {"status": "NO_DATA", "message": "No data", "data": []}

    monkeypatch.setattr("agent.lookup_market_price_data", fake_lookup)
    result = await Assistant().lookup_market_price(None, "cotton", "Latur")

    assert captured == {"crop": "cotton", "district": "Latur"}
    assert json.loads(result)["status"] == "NO_DATA"
    assert "could not be retrieved" in json.loads(result)["instruction"]
