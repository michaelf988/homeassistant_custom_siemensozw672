"""Web API client for the Siemens OZW672."""
import asyncio
import logging
import socket
import time

import urllib.parse as Parse
import json

import aiohttp

from .const import TESTDATA

_LOGGER: logging.Logger = logging.getLogger(__package__)
HEADERS = {"Content-type": "application/json; charset=UTF-8"}

# Session errors the OZW672 reports when the SessionId is unknown or expired.
SESSION_ERROR_NUMBERS = ("1", "2")


class SiemensOzw672ApiError(Exception):
    """The OZW672 could not be reached, or answered with an error.

    api_wrapper() used to swallow every exception and fall out of its retry loop
    returning None, so callers blew up on `None["Result"]` far away from the
    actual cause.
    """


class SiemensOzw672AuthError(SiemensOzw672ApiError):
    """Authentication against the OZW672 failed."""


class SiemensOzw672ApiClient:
    def __init__(
        self,
        host: str,
        protocol: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        timeout: int,
        retries: int,
        verify_ssl: bool = False,
        request_delay: float = 0.0,
    ) -> None:
        """Siemens OZW672 API Client."""
        _LOGGER.debug("OZW Init")
        self._host = host
        self._protocol = protocol
        self._username = username
        self._password = password
        self._session = session
        self._sessionid = "None"
        self._dpdata = None
        self._timeout = timeout
        self._retries = retries
        self._verify_ssl = verify_ssl
        self._request_delay = request_delay
        # The OZW672 is a small embedded web server that copes badly with parallel
        # requests. Every request in this client goes through this lock, so however
        # many coordinators or entities call in, the device only ever sees one
        # request at a time.
        self._request_lock = asyncio.Lock()
        self._last_request_finished = 0.0

    def _redact(self, url: str) -> str:
        """Return a URL safe to log: no session id, no password."""
        redacted = url.replace(f"SessionId={self._sessionid}", "SessionId=XXXXXX")
        if self._password:
            # _url() builds queries with urlencode, which quotes with quote_plus.
            redacted = redacted.replace(Parse.quote_plus(self._password), "XXXXXX")
        return redacted

    def _url(self, path: str, **params) -> str:
        """Build an API URL with properly encoded query parameters."""
        query = Parse.urlencode(params)
        return f"{self._protocol}://{self._host}/api/{path}?{query}"

    async def async_get_sessionid(self) -> bool:
        """Login to the OZW672 and get a SessionID"""
        url = self._url("auth/login.json", user=self._username, pwd=self._password)
        _LOGGER.debug(f"OZW Login to host: {self._host}")
        if (self._host == "test"):
            response = json.loads(TESTDATA["PREAUTH"])
        else:
            response = await self.api_wrapper("get_preauth", url)
        success = response.get("Result", {}).get("Success")
        if (success == "true"):
            self._sessionid = response["SessionId"]
            return True
        _LOGGER.debug("Failed to Login to %s", self._host)
        return False

    async def async_get_sysinfo(self) -> dict:
        """ Sample: ./api/device/info.json?SessionId=1278af3d-a62d-4def-938e-ae2df141500e """
        url = self._url("device/info.json", SessionId=self._sessionid)
        if (self._host == "test"):
            response = json.loads(TESTDATA["SYSINFOLIST"])
        else:
            response = await self.api_wrapper("get", url)
        _LOGGER.debug(f'async_get_sysinfo - response: {response}')
        if response.get("Result", {}).get("Success") == "true":
            return response["Device"]
        return None

    async def async_get_devices(self) -> dict:
        """Get the device list from the OZW672."""
        """ Sample: ./api/devicelist/list.json?SessionId=af06e880-bd59-4fb7-873d-d7b3fbc9561f """
        url = self._url("devicelist/list.json", SessionId=self._sessionid)
        if (self._host == "test"):
            response = json.loads(TESTDATA["DEVICELIST"])
        else:
            response = await self.api_wrapper("get", url)
        _LOGGER.debug(f'async_get_devices - response: {response}')
        if response.get("Result", {}).get("Success") == "true":
            return response["Devices"]
        return None

    async def async_get_menutree(self, id) -> dict:
        """Get the Menu Tree from the OZW672.  If Id="" - then it lists the devices"""
        """ Sample: ./api/menutree/list.json?SessionId=29090e86-3c9a-4eb3-9e95-d5c1729c41e3&Id="""
        url = self._url("menutree/list.json", SessionId=self._sessionid, Id=id)
        if (self._host == "test") and (id == ""):
            response = json.loads(TESTDATA["MENUTREEDEVICELIST"])
        elif (self._host == "test") and (int(id) > 0):
            response = json.loads(TESTDATA["MENUITEMLIST"][id])
        elif (self._host == "test"):
            response = json.loads(TESTDATA["MENUITEMLIST"])
        else:
            response = await self.api_wrapper("get", url)
        _LOGGER.debug(f"async_get_menutree reponse: {response}")
        if response.get("Result", {}).get("Success") == "true":
            return response
        return None

    async def async_get_datapoints(self, id) -> dict:
        """Get the DataPoint(s) from the OZW672. """
        url = self._url("menutree/list.json", SessionId=self._sessionid, Id=id)
        _LOGGER.debug(f"async_get_datapoints: id={id}")
        if (self._host == "test"):
            response = json.loads(TESTDATA["DATAPOINTLIST"][id])
        else:
            response = await self.api_wrapper("get", url)
        _LOGGER.debug(f"async_get_datapoints Datapoint Data reponse: {response}")
        if response.get("Result", {}).get("Success") == "true":
            return response["DatapointItems"]
        return None
        #Sample response: {"MenuItems": [], "DatapointItems": [{"Id": "1438", "Address": "0x310571", "DpSubKey": "0", "WriteAccess": "true", "Text": {"CatId": "2", "GroupId": "2", "Id": "3514", "Long": "DHW operating mode", "Short": "DHW OptgMode"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""

    async def async_get_data(self, datapoints) -> dict:
        """Get the Data for multiple datapoints from the OZW672.

        A datapoint that cannot be read is skipped and logged rather than taking
        the whole poll down with it: previously one failing datapoint raised, the
        coordinator turned that into UpdateFailed, and *every* entity of the
        integration went unavailable. Only a poll in which nothing at all could be
        read is treated as a failure.
        """
        start_time = time.monotonic()
        _LOGGER.debug(f"async_get_data Getting data for datapoints : {datapoints}")
        consolidated_response = {}
        failed = []
        for dp in datapoints:
            if isinstance(dp, str):
                dpdata = json.loads(dp)
            else:
                dpdata = dp
            id = dpdata["Id"]
            url = self._url(
                "menutree/read_datapoint.json", SessionId=self._sessionid, Id=id
            )
            try:
                if (self._host == "test"):
                    response = json.loads(TESTDATA["DATAPOINT"][id])
                else:
                    response = await self.api_wrapper("get", url)
            except SiemensOzw672ApiError as exception:
                _LOGGER.debug(f"async_get_data failed for datapoint {id}: {exception}")
                failed.append(id)
                continue
            _LOGGER.debug(f"async_get_data response : {response}")
            if response.get("Result", {}).get("Success") == "true" and "Data" in response:
                # The device's no-data sentinel ("----") is deliberately passed
                # through untouched. It used to be rewritten to "0" here, which
                # recorded a missing reading as a real zero in long-term statistics.
                consolidated_response[id] = response
            else:
                failed.append(id)
        elapsed_time = time.monotonic() - start_time
        if failed:
            _LOGGER.warning(
                "Could not read %d of %d datapoints from the OZW672: %s",
                len(failed), len(datapoints), ", ".join(failed),
            )
        if datapoints and not consolidated_response:
            raise SiemensOzw672ApiError(
                f"None of the {len(datapoints)} requested datapoints could be read"
            )
        if elapsed_time > 60:
            _LOGGER.warning(
                f"OZW672 Data Poll time exceeding 60 seconds. Last Poll Time: {round(elapsed_time)} seconds"
            )
        _LOGGER.debug(f"OZW672 Data Poll time: {round(elapsed_time)} seconds")
        return consolidated_response
        # Sample response {"Data": {"Type": "Enumeration", "Value": "On", "Unit": ""}, "Result": {"Success": "true"}}

    async def async_write_data(self, datapoint, value) -> dict:
        """Write the Data for a single datapoint to the OZW672."""
        _LOGGER.debug(f"async_write_data Writing data for datapoint : {datapoint}")
        if isinstance(datapoint, str):
            dpdata = json.loads(datapoint)
        else:
            dpdata = datapoint
        id = dpdata["Id"]
        dptype = dpdata["DPDescr"]["Type"]
        params = {"SessionId": self._sessionid, "Id": id, "Type": dptype, "Value": value}
        if dptype == "Numeric":  # and ("HasValid" in dpdata["DPDescr"]):
            params["IsValid"] = "true"
        url = self._url("menutree/write_datapoint.json", **params)
        if (self._host == "test"):
            # I could do something here to make the test work using the DPDescr cached data
            response = json.loads(TESTDATA["DATAPOINT"][id])
        else:
            response = await self.api_wrapper("get", url)
        _LOGGER.debug(f"async_write_data Datapoint Data response : {response}")
        if response.get("Result", {}).get("Success") == "true":
            return response
        raise SiemensOzw672ApiError(f"The OZW672 rejected the write to datapoint {id}")

    async def async_get_data_descr(self, datapoints, all_dpdata, force=False) -> dict:
        """Get the DataPoint Descriptions for multiple datapoints from the OZW672. """
        _LOGGER.debug(f"async_get_data_descr Getting data descriptions for datapoints : {datapoints}")
        consolidated_response = {}
        for dp in datapoints:
            if isinstance(dp, str):
                dpjson = json.loads(dp)
            else:
                dpjson = dp
            id = dpjson["Id"]
            dpdata = all_dpdata.get(id)
            if dpdata is None:
                # The value could not be read, so there is nothing to classify.
                _LOGGER.warning(
                    "Skipping datapoint %s: the OZW672 did not return a value for it", id
                )
                continue
            writeable = dpjson["WriteAccess"]
            url = self._url(
                "menutree/datapoint_desc.json", SessionId=self._sessionid, Id=id
            )
            if (self._host == "test"):
                response = json.loads(TESTDATA["DATAPOINTDESCR"][id])
            else:
                if writeable == "true" or force:  #We only need descriptions for Writeable datapoints.
                    response = await self.api_wrapper("get", url)
                else:  #Just return the Type - save the OZW a load of queries.
                    response = {
                        "Description": {"Type": dpdata["Data"]["Type"]},
                        "Result": {"Success": "true"},
                    }
            if response.get("Result", {}).get("Success") == "true":
                _LOGGER.debug(f"DatapointItem description reponse: {response}")
                ### This is the main place where the sensors are categorised into domains
                ### Data Point Descriptions are only polled at the time of discovery
                ###
                # Enumeration + Writeable + NOT On/Off = Select Entity
                # Enumeration + Writeable + On/Off = Switch
                # RadioButton/Enumeration + NOT Writeable + On/Off = BinarySensor
                # Number + Writeable + Percent/Temp = Number
                # Number + NOT Writeable + Percent/Temp = Sensor
                # Number + Writeable/NOT Writeable + OtherType = Sensor
                # Everything Else = Sensor
                ###
                if response["Description"]["Type"] == "Enumeration":
                    if writeable == "true":
                        if dpdata["Data"]["Value"] in ['On', 'Off'] :
                            response["Description"]["HAType"] = "switch"
                        else:
                            response["Description"]["HAType"] = "select"
                    else:
                        if dpdata["Data"]["Value"] in ['On', 'Off'] :
                            response["Description"]["HAType"] = "binarysensor"
                        else:
                            response["Description"]["Enums"] = []  #Some Enums are huge - don't need them for read only sensors.
                            response["Description"]["HAType"] = "sensor"
                elif response["Description"]["Type"] == "RadioButton":
                    if writeable == "true":
                        response["Description"]["HAType"] = "switch"
                    else:
                        if dpdata["Data"]["Value"] in ['On', 'Off'] :
                            response["Description"]["HAType"] = "binarysensor"
                        else:
                            response["Description"]["HAType"] = "sensor"
                elif response["Description"]["Type"] == "Numeric":
                    if writeable == "true" and response["Description"].get("Unit") in ['°C', '°F', 'K', '%', 'kWh', 'Wh']:
                        response["Description"]["HAType"] = "number"
                    else:
                        response["Description"]["HAType"] = "sensor"
                elif response["Description"]["Type"] == "TimeOfDay":
                    # A writeable time of day is a time entity; a read-only one has
                    # nowhere better to go than a sensor. Between 0.4.0 and 0.5.0
                    # both were sensors, because the "time" HAType this restores was
                    # claimed by no platform and those datapoints vanished silently.
                    if writeable == "true":
                        response["Description"]["HAType"] = "time"
                    else:
                        response["Description"]["HAType"] = "sensor"
                else:
                    # Everything else becomes a read-only sensor.
                    response["Description"]["HAType"] = "sensor"
                consolidated_response[id] = response
        _LOGGER.debug(f"async_get_data_descr DatapointItem description reponse: {consolidated_response}")
        return consolidated_response

    async def _request_json(self, url: str, headers: dict) -> dict:
        """Perform one GET, retrying on transport errors.

        Raises SiemensOzw672ApiError when every attempt failed, rather than
        returning None: the old loop fell through to an implicit `return None`,
        and `retries=0` meant it never ran a single request at all.
        """
        attempts = max(1, self._retries)
        logurl = self._redact(url)
        last_error = "unknown error"
        for attempt in range(1, attempts + 1):
            try:
                async with self._request_lock:
                    if self._request_delay:
                        # Space out requests so a burst never hits the device.
                        wait = self._last_request_finished + self._request_delay - time.monotonic()
                        if wait > 0:
                            await asyncio.sleep(wait)
                    try:
                        async with asyncio.timeout(self._timeout):
                            response = await self._session.get(
                                url, headers=headers, ssl=self._verify_ssl
                            )
                            return await response.json(content_type=None)
                    finally:
                        self._last_request_finished = time.monotonic()
            except asyncio.TimeoutError:
                last_error = f"timed out after {self._timeout}s"
            except (aiohttp.ClientError, socket.gaierror) as exception:
                last_error = repr(exception)
            except ValueError as exception:  # includes json.JSONDecodeError
                last_error = f"malformed response: {exception!r}"
            _LOGGER.debug(
                "Request to %s failed (attempt %d/%d): %s", logurl, attempt, attempts, last_error
            )
        raise SiemensOzw672ApiError(
            f"Request to {logurl} failed after {attempts} attempt(s): {last_error}"
        )

    async def api_wrapper(
        self, method: str, url: str, data: dict = None, headers: dict = None,
        _reauth_attempted: bool = False
    ) -> dict:
        """Get information from the OZW WebAPI."""
        if headers is None:
            headers = {}
        logurl = self._redact(url)

        if method == "get_preauth":
            _LOGGER.debug(f"HTTP GET (login) url: {logurl}")
            return await self._request_json(url, headers)

        _LOGGER.debug(f"HTTP GET url: {logurl}")
        cache_sessionid = self._sessionid
        jsonresponse = await self._request_json(url, headers)
        _LOGGER.debug(f"API GET: {jsonresponse}")

        result = jsonresponse.get("Result", {}) if isinstance(jsonresponse, dict) else {}
        if result.get("Success") != "false":
            return jsonresponse

        error = result.get("Error") or {}
        if str(error.get("Nr")) in SESSION_ERROR_NUMBERS:
            if _reauth_attempted:
                # Re-authenticating did not help. Raising rather than recursing
                # again, which previously looped until RecursionError when the
                # session kept being rejected.
                raise SiemensOzw672AuthError(
                    f"Re-authentication did not resolve the session error for url: {logurl}"
                )
            await self.async_get_sessionid()
            # Search and replace SessionId
            newurl = url.replace(
                f"SessionId={cache_sessionid}", f"SessionId={self._sessionid}"
            )
            return await self.api_wrapper("get", newurl, _reauth_attempted=True)

        raise SiemensOzw672ApiError(
            f'Failed API call with error: {error.get("Txt", "unknown error")} for url: {logurl}'
        )
