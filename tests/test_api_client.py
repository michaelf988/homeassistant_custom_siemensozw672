"""Tests for the OZW672 API client transport.

api_wrapper() used to swallow every exception, fall out of its retry loop and
return None, so callers blew up on `None["Result"]` far away from the real cause.
`retries=0` meant `for x in range(0)` never issued a single request at all, and a
session error that persisted recursed until RecursionError.
"""
import aiohttp
import pytest

from custom_components.siemens_ozw672.api import (
    SiemensOzw672ApiClient,
    SiemensOzw672ApiError,
    SiemensOzw672AuthError,
)

OK_LOGIN = {"SessionId": "session-2", "Result": {"Success": "true"}}
SESSION_ERROR = {"Result": {"Success": "false", "Error": {"Nr": "1", "Txt": "No session"}}}
OTHER_ERROR = {"Result": {"Success": "false", "Error": {"Nr": "7", "Txt": "Bad datapoint"}}}


def _reading(value, unit="°C"):
    return {"Data": {"Type": "Numeric", "Value": value, "Unit": unit},
            "Result": {"Success": "true"}}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def json(self, content_type=None):
        return self._payload


class _FakeSession:
    """Serves a scripted list of payloads; an Exception entry is raised instead."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def get(self, url, headers=None, ssl=None):
        self.calls.append(url)
        if not self.outcomes:
            raise AssertionError(f"unexpected extra request to {url}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


def _client(session, retries=2, **kwargs):
    return SiemensOzw672ApiClient(
        "ozw.example", "http", "user", "s3cr3t", session,
        timeout=5, retries=retries, **kwargs,
    )


async def test_transport_failure_raises_instead_of_returning_none():
    """Every attempt failing raises, rather than returning None to the caller."""
    session = _FakeSession(aiohttp.ClientError("boom"), aiohttp.ClientError("boom"))
    client = _client(session, retries=2)

    with pytest.raises(SiemensOzw672ApiError, match="after 2 attempt"):
        await client.api_wrapper("get", "http://ozw.example/api/x?SessionId=None")

    assert len(session.calls) == 2


async def test_zero_retries_still_issues_one_request():
    """retries=0 used to mean the loop body never ran and None came back."""
    session = _FakeSession(_reading(" 19.8"))
    client = _client(session, retries=0)

    result = await client.api_wrapper("get", "http://ozw.example/api/x?SessionId=None")

    assert result["Data"]["Value"] == " 19.8"
    assert len(session.calls) == 1


async def test_transient_failure_is_retried():
    """A first failed attempt does not fail the call."""
    session = _FakeSession(aiohttp.ClientError("boom"), _reading(" 19.8"))
    client = _client(session, retries=3)

    result = await client.api_wrapper("get", "http://ozw.example/api/x?SessionId=None")

    assert result["Data"]["Value"] == " 19.8"
    assert len(session.calls) == 2


async def test_non_session_error_raises_with_the_device_text():
    """An API-level error is reported rather than returned as a success-shaped dict."""
    session = _FakeSession(OTHER_ERROR)
    client = _client(session)

    with pytest.raises(SiemensOzw672ApiError, match="Bad datapoint"):
        await client.api_wrapper("get", "http://ozw.example/api/x?SessionId=None")


async def test_persistent_session_error_raises_instead_of_recursing():
    """A session error that survives re-authentication stops after one retry."""
    session = _FakeSession(SESSION_ERROR, OK_LOGIN, SESSION_ERROR)
    client = _client(session)

    with pytest.raises(SiemensOzw672AuthError):
        await client.api_wrapper("get", "http://ozw.example/api/x?SessionId=None")

    # One original call, one login, one retry - and then it gives up.
    assert len(session.calls) == 3


async def test_session_error_recovers_after_reauthentication():
    """The happy path of the re-auth branch still works."""
    session = _FakeSession(SESSION_ERROR, OK_LOGIN, _reading(" 19.8"))
    client = _client(session)

    result = await client.api_wrapper("get", "http://ozw.example/api/x?SessionId=None")

    assert result["Data"]["Value"] == " 19.8"
    assert "SessionId=session-2" in session.calls[-1]


async def test_no_data_sentinel_is_passed_through_untouched():
    """"----" must not be rewritten to "0".

    api.py used to substitute a zero here, so a datapoint the device had no
    reading for was recorded as a real zero in long-term statistics.
    """
    session = _FakeSession(_reading("----"))
    client = _client(session)

    data = await client.async_get_data([{"Id": "1963"}])

    assert data["1963"]["Data"]["Value"] == "----"


async def test_one_unreadable_datapoint_does_not_fail_the_whole_poll():
    """A failing datapoint is skipped; the rest of the poll still returns."""
    session = _FakeSession(OTHER_ERROR, _reading(" 19.8"))
    client = _client(session, retries=1)

    data = await client.async_get_data([{"Id": "1959"}, {"Id": "1960"}])

    assert "1959" not in data
    assert data["1960"]["Data"]["Value"] == " 19.8"


async def test_a_poll_that_reads_nothing_is_a_failure():
    """Only a completely empty poll is escalated to the coordinator."""
    session = _FakeSession(OTHER_ERROR, OTHER_ERROR)
    client = _client(session, retries=1)

    with pytest.raises(SiemensOzw672ApiError, match="None of the 2"):
        await client.async_get_data([{"Id": "1959"}, {"Id": "1960"}])


async def test_credentials_are_url_encoded_and_redacted():
    """The username is encoded too, and neither secret reaches the log."""
    session = _FakeSession(OK_LOGIN)
    client = SiemensOzw672ApiClient(
        "ozw.example", "http", "admin user", "p@ss word&x", session, timeout=5, retries=1
    )

    assert await client.async_get_sessionid() is True
    login_url = session.calls[0]
    assert "admin+user" in login_url
    assert "p@ss word&x" not in login_url
    assert "p%40ss+word%26x" in login_url
    assert "p%40ss+word%26x" not in client._redact(login_url)


async def test_requests_are_serialised_for_the_device():
    """All traffic goes through one lock, so the OZW672 never sees parallel requests."""
    client = _client(_FakeSession())

    assert client._request_lock is not None


# --- writing: which parameter shape the device accepts -----------------------
#
# Reported from a real OZW672 (firmware 12.x): every numeric write came back
# "datatype not supported", because IsValid=true was sent for every numeric
# datapoint. The original integration first sent it only for HasValid=true
# datapoints, then changed to sending it always - each shape is right on some
# firmwares, so the client tries and remembers rather than choosing once.

DATATYPE_ERROR = {
    "Result": {"Success": "false",
               "Error": {"Nr": "9", "Txt": "datatype not supported"}}
}
WRITE_OK = {"Result": {"Success": "true"}}


def _numeric(has_valid=None):
    descr = {"Type": "Numeric"}
    if has_valid is not None:
        descr["HasValid"] = has_valid
    return {"Id": "686", "OpLine": "2214", "Name": "Schaltdiff Aus Max TWW",
            "DPDescr": descr}


async def test_a_numeric_without_hasvalid_is_written_without_isvalid():
    """The shape the device that reported this bug rejects is not the first try."""
    session = _FakeSession(WRITE_OK)
    client = _client(session)

    await client.async_write_data(_numeric(has_valid="false"), "12.0")

    assert "IsValid" not in session.calls[0]
    assert "Value=12.0" in session.calls[0]


async def test_a_numeric_with_hasvalid_is_written_with_isvalid():
    """A datapoint that carries a validity flag still gets one."""
    session = _FakeSession(WRITE_OK)
    client = _client(session)

    await client.async_write_data(_numeric(has_valid="true"), "12.0")

    assert "IsValid=true" in session.calls[0]


async def test_a_rejected_shape_is_retried_the_other_way(caplog):
    """"datatype not supported" is answered by trying the other shape, not by giving up."""
    session = _FakeSession(DATATYPE_ERROR, WRITE_OK)
    client = _client(session, retries=1)

    response = await client.async_write_data(_numeric(has_valid="false"), "12.0")

    assert response == WRITE_OK
    assert len(session.calls) == 2
    assert "IsValid" not in session.calls[0]
    assert "IsValid=true" in session.calls[1]


async def test_the_accepted_shape_is_remembered():
    """Only the first write of a datapoint may cost two requests."""
    session = _FakeSession(DATATYPE_ERROR, WRITE_OK, WRITE_OK)
    client = _client(session, retries=1)
    datapoint = _numeric(has_valid="false")

    await client.async_write_data(datapoint, "12.0")
    await client.async_write_data(datapoint, "11.5")

    assert len(session.calls) == 3
    assert "IsValid=true" in session.calls[2]


async def test_a_write_rejected_both_ways_reports_both_attempts():
    """The error names what was tried, so the next step is not guesswork."""
    session = _FakeSession(DATATYPE_ERROR, DATATYPE_ERROR)
    client = _client(session, retries=1)

    with pytest.raises(SiemensOzw672ApiError) as raised:
        await client.async_write_data(_numeric(has_valid="false"), "12.0")

    message = str(raised.value)
    assert "without IsValid" in message and "with IsValid" in message
    assert "datatype not supported" in message
    assert "686" in message


async def test_a_shape_that_stops_working_is_forgotten():
    """A remembered shape must not lock a datapoint into failing forever."""
    session = _FakeSession(WRITE_OK, DATATYPE_ERROR, WRITE_OK)
    client = _client(session, retries=1)
    datapoint = _numeric(has_valid="false")

    await client.async_write_data(datapoint, "12.0")
    with pytest.raises(SiemensOzw672ApiError):
        await client.async_write_data(datapoint, "11.5")
    # The next write starts over from both shapes rather than repeating the one
    # that just failed.
    await client.async_write_data(datapoint, "11.0")

    assert "IsValid" not in session.calls[2]


async def test_non_numeric_writes_are_tried_once():
    """Only numerics have two shapes; an enumeration must not be written twice."""
    session = _FakeSession(DATATYPE_ERROR)
    client = _client(session, retries=1)
    datapoint = {"Id": "1441", "Name": "Operating mode",
                 "DPDescr": {"Type": "Enumeration"}}

    with pytest.raises(SiemensOzw672ApiError):
        await client.async_write_data(datapoint, "2")

    assert len(session.calls) == 1


async def test_a_session_error_is_not_treated_as_a_wrong_shape():
    """Re-authentication handles a stale session; a second shape would not."""
    session = _FakeSession(SESSION_ERROR, OK_LOGIN, SESSION_ERROR)
    client = _client(session, retries=1)

    with pytest.raises(SiemensOzw672AuthError):
        await client.async_write_data(_numeric(has_valid="false"), "12.0")
