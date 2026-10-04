"""ContreeSDK's per-call "Token expires in 0 hours" warning is dropped."""
import logging

from nge import nebius_client


def test_the_five_minute_token_warning_is_dropped_and_nothing_else(caplog):
    nebius_client._quiet_token_expiry()
    nebius_client._quiet_token_expiry()                # idempotent
    lg = logging.getLogger("contree_sdk.sdk.client._base")
    assert sum(isinstance(f, nebius_client._DropTokenExpiry) for f in lg.filters) == 1
    with caplog.at_level(logging.WARNING, logger=lg.name):
        lg.warning("Token expires in 0 hours")
        lg.warning("Timeout 300s exceeds run_max_timeout=120")
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs == ["Timeout 300s exceeds run_max_timeout=120"]
