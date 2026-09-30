"""IEEE MA-L parsing and lookup use only a tiny synthetic CSV fixture."""

import pytest

from nettracker.discovery.vendor import lookup_vendor, parse_ma_l_csv

CSV = (
    "Registry,Assignment,Organization Name,Organization Address\n"
    "MA-L,001A2B,Example Devices Inc.,Example City\n"
    "MA-L,ABCDEF,Private,\n"
    "MA-M,001A2C,Other Inc.,Example City\n"
    "MA-L,INVALID,Malformed Inc.,Example City\n"
)


def test_parse_and_lookup_public_oui_only() -> None:
    vendors = parse_ma_l_csv(CSV)
    assert vendors == {"001A2B": "Example Devices Inc."}
    assert lookup_vendor("00:1a:2b:33:44:55", vendors) == "Example Devices Inc."
    assert lookup_vendor("00:1a:2c:33:44:55", vendors) is None
    assert lookup_vendor("02:1a:2b:33:44:55", vendors) is None
    assert lookup_vendor("01:1a:2b:33:44:55", vendors) is None


def test_invalid_input_is_rejected_without_network() -> None:
    with pytest.raises(ValueError, match="header"):
        parse_ma_l_csv("wrong,columns\nfoo,bar\n")
    with pytest.raises(ValueError, match="invalid MAC"):
        lookup_vendor("not-a-mac", {})
