"""Platform for the Daikin AC."""
import base64
import datetime
import functools
import logging
import os
import re
import requests
import time
import asyncio
import json

from homeassistant.util import Throttle
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant import config_entries, core

from .const import DOMAIN, DAIKIN_DEVICES

from .daikin_base import Appliance

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = datetime.timedelta(minutes=10)

class DaikinApi:
    """Daikin Residential API."""

    def __init__(self,
                hass: core.HomeAssistant,
                entry: config_entries.ConfigEntry,
                implementation: config_entry_oauth2_flow.AbstractOAuth2Implementation,):
        """Initialize a new Daikin Residential Altherma API."""
        _LOGGER.debug("Initialing Daikin Residential Altherma API...")
        self.hass = hass
        self._config_entry = entry
        self.session = config_entry_oauth2_flow.OAuth2Session(
            hass, entry, implementation
        )

        # The Daikin cloud returns old settings if queried with a GET
        # immediately after a PATCH request. Se we use this attribute
        # to skip the first GET if a PATCH request has just been executed.
        self._just_updated = False

        # The following lock is used to serialize http requests to Daikin cloud
        # to prevent receiving old settings while a PATCH is ongoing.
        self._cloud_lock = asyncio.Lock()

        _LOGGER.info("Daikin Residential Altherma API initialized.")

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        token_valid = self.session.valid_token
        if not token_valid:
            _LOGGER.debug("Token before renew: %s", self.session.token["access_token"])
        await self.session.async_ensure_token_valid()
        if not token_valid:
            _LOGGER.debug("Token after renew: %s", self.session.token["access_token"])
        return self.session.token["access_token"]

    async def doBearerRequest(self, resourceUrl, options=None):
        token = await self.async_get_access_token()
        if token is None:
            raise Exception("Missing token. Please repeat Authentication process.")

        if not resourceUrl.startswith("http"):
            resourceUrl = "https://api.onecta.daikineurope.com" + resourceUrl

        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        }

        async with self._cloud_lock:
            _LOGGER.debug("BEARER REQUEST URL: %s", resourceUrl)
            if (
                options is not None
                and "method" in options
                and options["method"] == "PATCH"
            ):
                _LOGGER.debug("BEARER REQUEST JSON: %s", options["json"])
                func = functools.partial(
                    requests.patch, resourceUrl, headers=headers, data=options["json"]
                )
            else:
                func = functools.partial(requests.get, resourceUrl, headers=headers)
            try:
                res = await self.hass.async_add_executor_job(func)
            except Exception as e:
                _LOGGER.error("REQUEST FAILED: %s", e)
                return []

            limit_minute = res.headers.get('X-RateLimit-Limit-minute', 0)
            limit_day = res.headers.get('X-RateLimit-Limit-day', 0)
            limit_remaining_minutes = res.headers.get('X-RateLimit-Remaining-minute', 0)
            limit_remaining_day = res.headers.get('X-RateLimit-Remaining-day', 0)

            _LOGGER.debug("BEARER RESPONSE CODE: %s LIMIT: remaining minute %s day %s MAX: minute %s day %s ", res.status_code, limit_remaining_minutes, limit_remaining_day, limit_minute, limit_day)

        if res.status_code == 200:
            try:
                return res.json()
            except Exception:
                _LOGGER.error("RETRIEVE JSON FAILED: %s", res.text)
                return False
        elif res.status_code == 204:
            self._just_updated = True
            return True

        raise Exception("Communication failed! Status: " + str(res.status_code))

    async def getCloudDeviceDetails(self):
        """Get pure Device Data from the Daikin cloud devices."""
        json_puredata = await self.doBearerRequest("/v1/gateway-devices")
        return json_puredata

    async def getCloudDevices(self):
        """Get array of DaikinResidentialDevice objects and get their data."""
        self.json_data = await self.getCloudDeviceDetails()

        res = {}
        for dev_data in self.json_data or []:
            device = Appliance(dev_data, self)
            res[dev_data["id"]] = device
        return res

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self, **kwargs):
        """Pull the latest data from Daikin."""
        if self._just_updated:
            self._just_updated = False
            _LOGGER.debug("API UPDATE skipped (just updated from UI)")
            return False

        _LOGGER.debug("API UPDATE")

        self.json_data = await self.getCloudDeviceDetails()
        for dev_data in self.json_data or []:

            if dev_data["id"] in self.hass.data[DOMAIN][DAIKIN_DEVICES]:
                self.hass.data[DOMAIN][DAIKIN_DEVICES][dev_data["id"]].setJsonData(
                    dev_data
                )
