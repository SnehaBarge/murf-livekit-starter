import argparse
import json
import logging
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

AGMARKNET_BASE_URL = "https://api.agmarknet.gov.in/v1"
MARKET_LOOKUP_URL = f"{AGMARKNET_BASE_URL}/market-district-state"
DAILY_REPORT_URL = (
    f"{AGMARKNET_BASE_URL}/prices-and-arrivals/market-report/daily"
)
REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://agmarknet.gov.in",
    "Referer": "https://agmarknet.gov.in/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}
logger = logging.getLogger("market_prices")


def _request_json(request: Request, *, opener=urlopen, timeout: float = 10):
    endpoint = request.full_url
    try:
        with opener(request, timeout=timeout) as response:
            logger.info("Agmarknet HTTP %s %s", response.status, endpoint)
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        logger.warning("Agmarknet HTTP %s %s", error.code, endpoint)
        raise
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        logger.warning("Agmarknet request failed %s: %s", endpoint, error)
        raise


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _resolve_markets(
    district: str, *, opener=urlopen, timeout: float = 10
) -> list[dict]:
    request = Request(MARKET_LOOKUP_URL, headers=REQUEST_HEADERS)
    _, payload = _request_json(request, opener=opener, timeout=timeout)
    district_name = _normalise(district)
    return [
        item
        for item in payload
        if isinstance(item, dict)
        and _normalise(str(item.get("district_name", ""))) == district_name
    ]


def _report_rows(
    payload: dict, crop: str, district: str, price_date: str
) -> list[dict]:
    rows = []
    crop_name = _normalise(crop)
    for state in payload.get("states", []):
        for market in state.get("markets", []):
            market_name = market.get("marketName")
            for commodity in market.get("commodities", []):
                commodity_name = commodity.get("commodityName", "")
                if crop_name not in _normalise(commodity_name):
                    continue
                for record in commodity.get("data", []):
                    rows.append(
                        {
                            "commodity": commodity_name,
                            "market": record.get("marketCenter") or market_name,
                            "district": district,
                            "minimum_price": record.get("minimumPrice"),
                            "maximum_price": record.get("maximumPrice"),
                            "modal_price": record.get("modalPrice"),
                            "date": price_date,
                        }
                    )
    return rows


def lookup_market_price_data(
    crop: str, district: str, *, opener=urlopen, timeout: float = 10
) -> dict:
    """Return the latest Agmarknet daily report rows for crop and district."""
    try:
        markets = _resolve_markets(district, opener=opener, timeout=timeout)
        if not markets:
            return {
                "status": "NO_DATA",
                "message": f"Agmarknet has no market mapping for {district}.",
                "data": [],
            }

        market_ids = sorted({item["market_id"] for item in markets})
        state_ids = sorted({item["state_id"] for item in markets})
        for days_ago in range(8):
            price_date = date.today() - timedelta(days=days_ago)
            payload = json.dumps(
                {
                    "date": price_date.isoformat(),
                    "marketIds": market_ids,
                    "stateIds": state_ids,
                    "includeExcel": False,
                }
            ).encode("utf-8")
            request = Request(
                DAILY_REPORT_URL,
                data=payload,
                headers={**REQUEST_HEADERS, "Content-Type": "application/json"},
                method="POST",
            )
            _, report = _request_json(request, opener=opener, timeout=timeout)
            rows = _report_rows(report, crop, district, price_date.isoformat())
            if rows:
                return {
                    "status": "OK",
                    "message": "Market price data retrieved.",
                    "data": rows,
                }
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {
            "status": "ERROR",
            "message": f"Agmarknet market price lookup failed: {error}",
            "data": [],
        }

    return {
        "status": "NO_DATA",
        "message": "Agmarknet returned no matching market price data.",
        "data": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test Agmarknet market data")
    parser.add_argument("crop")
    parser.add_argument("district")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(json.dumps(lookup_market_price_data(args.crop, args.district), indent=2))


if __name__ == "__main__":
    main()
