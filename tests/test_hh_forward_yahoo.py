from datetime import date
from collectors.hh_forward_yahoo import front_12_symbols, parse_yahoo_chart


def test_front_12_symbols():
    syms = front_12_symbols(date(2026, 11, 15))
    assert len(syms) == 12
    assert syms[0] == (1, "NGZ26.NYM", "2026-12")
    assert syms[1] == (2, "NGF27.NYM", "2027-01")
    assert syms[-1] == (12, "NGX27.NYM", "2027-11")


def test_parse_yahoo_chart():
    sample = {
        "chart": {
            "result": [{
                "meta": {"regularMarketPrice": 3.456, "regularMarketTime": 1794749400},
                "indicators": {"quote": [{"close": [3.41, 3.456]}]},
            }]
        }
    }
    price, target_ts, avail_ts = parse_yahoo_chart(sample)
    assert price == 3.456
    assert target_ts.endswith("T00:00:00Z")
    assert avail_ts.endswith("Z")
