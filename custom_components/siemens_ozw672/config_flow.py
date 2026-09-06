"""Adds config flow for Siemens OZW672."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers import selector

from .api import SiemensOzw672ApiClient
from .const import CONF_HOST
from .const import CONF_DEVICE
from .const import CONF_DEVICE_LONGNAME
from .const import CONF_DEVICE_ID
from .const import CONF_PROTOCOL
from .const import CONF_PASSWORD
from .const import CONF_USERNAME
from .const import CONF_MENUITEMS
from .const import CONF_DATAPOINTS
from .const import CONF_PREFIX_FUNCTION
from .const import CONF_PREFIX_OPLINE
from .const import CONF_SCANINTERVAL
from .const import CONF_HTTPTIMEOUT
from .const import CONF_HTTPRETRIES
from .const import DOMAIN
from .const import DEFAULT_HTTPTIMEOUT
from .const import DEFAULT_HTTPRETRIES
from .const import DEFAULT_SCANINTERVAL
from .const import DEFAULT_USE_DEVICE_LONGNAME
from .const import DEFAULT_OPTIONS
from .const import CONF_USE_DEVICE_LONGNAME
from .const import CONF_VERIFY_SSL
from .const import CONF_VERSION
from .const import CONF_MINOR_VERSION
from .const import CONF_PRIORITY
from .const import CONF_PRIORITY_FAST
from .const import CONF_PRIORITY_MEDIUM
from .const import CONF_INTERVAL_MEDIUM
from .const import CONF_INTERVAL_SLOW
from .const import CONF_REQUEST_DELAY
from .const import DEFAULT_INTERVAL_MEDIUM
from .const import DEFAULT_INTERVAL_SLOW
from .const import DEFAULT_REQUEST_DELAY
from .const import MAX_REQUEST_DELAY
from .const import PRIORITY_FAST
from .const import PRIORITY_MEDIUM
from .const import PRIORITY_SLOW
from .const import DEFAULT_VERIFY_SSL
from .const import MIN_SCANINTERVAL
from .const import MAX_SCANINTERVAL
from .const import MIN_HTTPTIMEOUT
from .const import MAX_HTTPTIMEOUT
from .const import MIN_HTTPRETRIES
from .const import MAX_HTTPRETRIES

import json

from .helpers import datapoint_priority

PROTOCOL_OPTIONS = [
    selector.SelectOptionDict(value="http", label="HTTP"),
    selector.SelectOptionDict(value="https", label="HTTPS")
]



import logging
_LOGGER: logging.Logger = logging.getLogger(__package__)


def priority_schema(datapoints):
    """Two multi-selects that sort datapoints into the fast and medium tiers.

    Anything left unselected stays in the slow tier, so the safe default for a
    device with limited capacity needs no clicks at all. A datapoint picked in
    both lists counts as fast.
    """
    options = [
        selector.SelectOptionDict(
            value=datapoint["Id"],
            label=f'{datapoint.get("MenuItem", "")} - {datapoint.get("OpLine", "")} '
                  f'{datapoint.get("Name", datapoint["Id"])}',
        )
        for datapoint in datapoints
    ]
    current = {
        priority: [dp["Id"] for dp in datapoints if datapoint_priority(dp) == priority]
        for priority in (PRIORITY_FAST, PRIORITY_MEDIUM)
    }
    return vol.Schema({
        vol.Optional(CONF_PRIORITY_FAST, default=current[PRIORITY_FAST]):
            selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, multiple=True)
            ),
        vol.Optional(CONF_PRIORITY_MEDIUM, default=current[PRIORITY_MEDIUM]):
            selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, multiple=True)
            ),
    })


def apply_priorities(datapoints, user_input):
    """Return datapoints with the priority chosen on the assignment form."""
    fast = set(user_input.get(CONF_PRIORITY_FAST) or [])
    medium = set(user_input.get(CONF_PRIORITY_MEDIUM) or [])
    updated = []
    for datapoint in datapoints:
        if datapoint["Id"] in fast:
            priority = PRIORITY_FAST
        elif datapoint["Id"] in medium:
            priority = PRIORITY_MEDIUM
        else:
            priority = PRIORITY_SLOW
        updated.append({**datapoint, CONF_PRIORITY: priority})
    return updated

class SiemensOzw672FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for siemens_ozw672."""

    # Taken from const so the flow and async_migrate_entry() can never disagree:
    # a hard-coded 5 here meant every freshly created entry was immediately
    # considered out of date and re-migrated on the next start.
    VERSION = CONF_VERSION
    MINOR_VERSION = CONF_MINOR_VERSION
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}
        self._session = None
        self._client = None
        self._discovereddevices = dict()
        self._devicemenuitems = None
        self._sysinfo = None
        self._datapoints = []
        self._datapoints_descr = []
        self._deviceid = None
        self._data = None
        self._devserialnumber = ""
        self.alldevices = None
        self._options = dict(DEFAULT_OPTIONS)
        self._disablenamechoice = False
        self._alldevicemenuitems = []
        # Set when the selected device is already configured, so the final step
        # updates that entry instead of creating a duplicate one beside it.
        self._existing_entry = None

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        """ First Screen - Protocol, Hostname/IP, Username, Password, and some options"""
        self._errors = {}
        if user_input is not None:
            valid = await self._test_credentials(
                user_input[CONF_HOST], user_input[CONF_PROTOCOL], user_input[CONF_USERNAME], user_input[CONF_PASSWORD], DEFAULT_HTTPTIMEOUT, DEFAULT_HTTPRETRIES
            )
            if valid:
                # Get the list of devices:
                menutree = await self._get_menutree("")
                self.alldevices = await self._get_devices()
                if menutree is None or self.alldevices is None:
                    # Credentials were accepted but the device stopped responding
                    # part-way through discovery.
                    self._errors["base"] = "cannot_connect"
                    return await self._show_config_form(user_input)
                self._discovereddevices = menutree["MenuItems"]
                self._data=user_input
                if CONF_DEVICE_ID in self._data:
                    existing_entry = self.async_entry_for_existingdevice(self._data[CONF_DEVICE_ID])
                    if existing_entry:
                        self._disablenamechoice=True
                return await self.async_step_device()
            else:
                self._errors["base"] = "auth"
            return await self._show_config_form(user_input)
        return await self._show_config_form(user_input)

    async def async_step_device(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            device=json.loads(user_input[CONF_DEVICE])
            ### Support a Customized name for the Device being monitored.
            self._data[CONF_DEVICE]=device["Name"]
            self._data[CONF_DEVICE_LONGNAME]=device["LongName"]
            self._options[CONF_PREFIX_FUNCTION]=user_input[CONF_PREFIX_FUNCTION]
            self._options[CONF_PREFIX_OPLINE]=user_input[CONF_PREFIX_OPLINE]
            self._options[CONF_USE_DEVICE_LONGNAME]=user_input[CONF_USE_DEVICE_LONGNAME]
            self._data[CONF_PREFIX_FUNCTION]=user_input[CONF_PREFIX_FUNCTION]
            self._data[CONF_PREFIX_OPLINE]=user_input[CONF_PREFIX_OPLINE]
            self._data[CONF_USE_DEVICE_LONGNAME]=user_input[CONF_USE_DEVICE_LONGNAME]
            ### Each device has a MenuTree root ID
            menutreeid=device["Id"]
            ### Get the System Info as discovery used Serial Number of the OZW672 and Serial Number of the Device.
            self._sysinfo = await self._get_sysinfo()
            self._data[CONF_DEVICE_ID]=f'{self._sysinfo["SerialNr"]}:{device["Text"]["Long"]}' #Redundant code - used as a default
            for d in self.alldevices:
                d_ident = f'{d["Addr"]} {d["Type"]}'
                if d_ident == device["Text"]["Long"]:
                    self._data[CONF_DEVICE_ID]=f'{self._sysinfo["SerialNr"]}:{d["SerialNr"]}'
            self._devserialnumber = self._data[CONF_DEVICE_ID]
            ### Support updating an existing device
            existing_entry = self.async_entry_for_existingdevice(self._data[CONF_DEVICE_ID])
            if existing_entry:
                self._existing_entry = existing_entry
                self._datapoints = list(existing_entry.data.get(CONF_DATAPOINTS) or [])
                # Detect if a change to the naming has occurred and updated all.
                _LOGGER.debug(f'Found existing datapoints: {self._datapoints}')
            await self.async_set_unique_id(self._devserialnumber)
            ### Now get a list of Functions/MenuItems (ignore datapoints at this level) for this device to enable the user to select what to monitor.
            self._devicemenuitems = (await self._get_menutree(menutreeid))["MenuItems"]
            return await self.async_step_mainmenu()
        else:
            return await self._show_device_selection_form(user_input)
        return await self._show_device_selection_form(user_input)

    async def async_step_mainmenu(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            self._data[CONF_MENUITEMS]=user_input[CONF_MENUITEMS]
            self._alldevicemenuitems=user_input[CONF_MENUITEMS]
            _LOGGER.debug(f"Found: CONF_MENUITEMS: {self._data[CONF_MENUITEMS]}")
            ### Now we have selected a list of Functions/MenuItems/DataPointItmes to monitor, recursively call a function to enable the user to select entities to monitor.
            return await self.async_step_submenu()
        else:
            return await self._show_mainmenu_selection_form(user_input)
        return await self._show_mainmenu_selection_form(user_input)
    

    async def async_step_submenu(self, user_input=None):
        _LOGGER.debug(f"async_step_submenu - user_input: {user_input}")
        self._errors = {}
        if user_input is not None:
            ###### WE NEED TO PROCESS SELECTED SUBMENUS HERE
            if CONF_MENUITEMS in user_input:
                for submenu in user_input[CONF_MENUITEMS]:
                    _LOGGER.debug(f'Appending {submenu} in MenuItems to discover')
                    self._alldevicemenuitems.append(submenu)
            if CONF_DATAPOINTS in user_input:
                # Get DP Data as we need this to determine type.
                all_dpdata = await self._get_data(user_input[CONF_DATAPOINTS])
                _LOGGER.debug(f'async_step_submenu **** Intial DP Data: {all_dpdata}')
                all_dpdescr = await self._get_data_descr(user_input[CONF_DATAPOINTS], all_dpdata)
                _LOGGER.debug(f'async_step_submenu **** Initial DP Descriptions: {all_dpdescr}')
                for dp in user_input[CONF_DATAPOINTS]:
                    dpjson=json.loads(dp)
                    dpdescr = all_dpdescr[dpjson["Id"]]["Description"]
                    _LOGGER.debug(f'async_step_submenu - "Id": {dpjson["Id"]},"WriteAccess": {dpjson["WriteAccess"]},"OpLine": {dpjson["Text"]["Id"]}, "Name": {dpjson["Text"]["Long"]},"MenuItem": {dpjson["MenuItem"]}, "DPDescr": {dpdescr} ')
                    self._datapoints.append({"Id": dpjson["Id"],"WriteAccess": dpjson["WriteAccess"],"OpLine": dpjson["Text"]["Id"], "Name": dpjson["Text"]["Long"],"MenuItem": dpjson["MenuItem"], "DPDescr": dpdescr })
            self._data[CONF_DATAPOINTS]=self._datapoints
            _LOGGER.debug(f"DATAPOINTS: {self._data[CONF_DATAPOINTS]}")
            if len(self._alldevicemenuitems) > 0:
                ### Recursively traverse through all menu items.
                _LOGGER.debug("****** Recursing further through menu ******")
                return await self.async_step_submenu()
            else: ### FINALLY... Create our discovered entities. ###
                return await self.async_step_priorities()
        else:
            if len(self._alldevicemenuitems) > 0:
                item = self._alldevicemenuitems.pop(0)
                _LOGGER.debug(f"Generating Config Form for item: {item} ")
                ### For each Function/MenuItem selected, list the entities available and allow the user to select what to monitor/poll
                ### Note - these could be submenus
                return await self._show_submenu_selection_form(item,user_input)
            else:
                # Nothing was selected on the main menu, so there is nothing to
                # walk through. Returning None here made Home Assistant raise on
                # a flow step that produced no result.
                return self.async_abort(reason="no_menu_items")

    async def async_step_priorities(self, user_input=None):
        """Assign each selected datapoint to a polling tier.

        The OZW672 is a small embedded web server and every datapoint costs it one
        HTTP request per poll, so polling everything at the same rate is what makes
        a large selection painful. Anything not raised here stays in the slowest
        tier, which is the safe default for a device this size.
        """
        self._errors = {}
        if user_input is not None:
            self._datapoints = apply_priorities(self._datapoints, user_input)
            self._data[CONF_DATAPOINTS] = self._datapoints
            return self._async_finish()
        return self.async_show_form(
            step_id="priorities",
            data_schema=priority_schema(self._datapoints),
            description_placeholders={"count": str(len(self._datapoints))},
            errors=self._errors,
        )

    def _async_finish(self):
        """Create the config entry, or update the one this device already has."""
        self._data["options"] = self._options
        if self._options.get(CONF_USE_DEVICE_LONGNAME):
            _LOGGER.debug(f'Options: {self._options} -- Will use Device Long Name')
            dev_title = self._data[CONF_DEVICE_LONGNAME]
        else:
            dev_title = self._data[CONF_DEVICE]
        if self._existing_entry is not None:
            # The device is already configured. Updating that entry keeps its
            # entities and history; creating a second entry with the same unique
            # id used to duplicate every entity instead.
            self.hass.config_entries.async_update_entry(
                self._existing_entry,
                title=dev_title,
                data=self._data,
                options=self._options,
            )
            return self.async_abort(reason="reconfigure_successful")
        return self.async_create_entry(
            title=dev_title, data=self._data, options=self._options
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler.

        The handler takes no arguments: Home Assistant supplies the config entry via
        the inherited OptionsFlow.config_entry property. Passing it to the constructor
        has been deprecated since HA 2024.11.
        """
        return SiemensOzw672OptionsFlowHandler()

    def async_entry_for_existingdevice(self, deviceserialnumber):
        """Find an existing entry for a serialnumber."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_DEVICE_ID) == deviceserialnumber:
                return entry
        return None

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
            {
                vol.Required(CONF_PROTOCOL, default="http"): selector.SelectSelector(selector.SelectSelectorConfig(options=PROTOCOL_OPTIONS)),
                vol.Required(CONF_HOST): str, 
                vol.Required(CONF_USERNAME): str, 
                vol.Required(CONF_PASSWORD): str
            }
            ),
            errors=self._errors,
        )

    async def _show_device_selection_form(self, user_input):  # pylint: disable=unused-argument
        """Show the device selection form. """
        _LOGGER.debug("Building device list from: " + str(self._discovereddevices))
        device_list_selector = []
        for device in self._discovereddevices:
            devchannel=str(device["Text"]["Long"]).split(' ',1)[0]
            devname=str(device["Text"]["Long"]).split(' ',1)[1]
            # Fall back to the name from the menu tree, then let a matching entry
            # in the device list override it. Without the break, the *last* device
            # in the list decided the name for every entry.
            device["Name"] = devname
            for dev in self.alldevices:
                if dev['Addr'] == devchannel:
                    device["Name"] = dev['Name']
                    break
            device["LongName"]=str(device["Text"]["Long"])
            device_list_selector.append(selector.SelectOptionDict(value=json.dumps(device), label="Address+Device: "+str(device["Text"]["Long"] +" (Name:"+device["Name"]+")")))
        if self._disablenamechoice == False:
            schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): selector.SelectSelector(selector.SelectSelectorConfig(options=device_list_selector)),
                    vol.Required(CONF_USE_DEVICE_LONGNAME, default=self._options[CONF_USE_DEVICE_LONGNAME]): bool,
                    vol.Required(CONF_PREFIX_FUNCTION, default=self._options[CONF_PREFIX_FUNCTION]): bool,
                    vol.Required(CONF_PREFIX_OPLINE, default=self._options[CONF_PREFIX_OPLINE]): bool
                })
        else:
            schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): selector.SelectSelector(selector.SelectSelectorConfig(options=device_list_selector)),
                    vol.Required(CONF_PREFIX_FUNCTION, default=self._options[CONF_PREFIX_FUNCTION]): bool,
                    vol.Required(CONF_PREFIX_OPLINE, default=self._options[CONF_PREFIX_OPLINE]): bool
                })

        return self.async_show_form(
            step_id="device",
            data_schema=schema,
            errors=self._errors,
        )

    async def _show_mainmenu_selection_form(self, user_input):  # pylint: disable=unused-argument
        """Show the menu item selection form. """
        _LOGGER.debug("Building Menu Item list from " + str(self._devicemenuitems))
        menuitem_list_selector = []
        for menuitem in self._devicemenuitems:
            menuitem_list_selector.append(selector.SelectOptionDict(value=json.dumps(menuitem), label=menuitem["Text"]["Long"]))
        return self.async_show_form(
            step_id="mainmenu",
            data_schema=vol.Schema(
            {
                vol.Required(CONF_MENUITEMS,default=False): selector.SelectSelector(selector.SelectSelectorConfig(options=menuitem_list_selector, multiple=True))
            }
            ),
            errors=self._errors,
        )

    async def _show_submenu_selection_form(self, item, user_input):  # pylint: disable=unused-argument
        """Show the Sub Menu Itme and Data Point item selection form. """
        _LOGGER.debug(f"Building SubMenu list for item: {item} ")
        datapoint_list_selector = []
        menuitem_list_selector = []
        
        menutree_item=json.loads(item)
        menutree_id=menutree_item["Id"]
        menutree_name=menutree_item["Text"]["Long"]
        if "MenuItem" not in item:
            menutree_menulocation = menutree_name
        else:
            menutree_menulocation = menutree_item["MenuItem"] + "->" + menutree_name
        existing_dp_items = self._datapoints
        
        new_all_items = await self._get_menutree(menutree_id)
        new_dp_items = new_all_items["DatapointItems"]
        new_menu_items = new_all_items["MenuItems"]

        _LOGGER.debug(f'Generating form for Submenus: {new_menu_items} and DataPoints: {new_dp_items} at menulocation: {menutree_menulocation} ')
        for menu in new_menu_items:
            menu["MenuItem"]=menutree_menulocation
            menuitem_list_selector.append(selector.SelectOptionDict(value=json.dumps(menu), label=menu["Text"]["Long"]) )

        for dp in new_dp_items:
            ### If we are already polling a variable - don't list it.
            already_exists=False
            for edp in existing_dp_items:
                if edp["Id"] == dp["Id"]:
                    already_exists=True
                    break
            ### If this is something new to monitor - add it to our Dict.
            if not already_exists:
                dp["MenuItem"]=menutree_menulocation
                datapoint_list_selector.append(selector.SelectOptionDict(value=json.dumps(dp), label=dp["Text"]["Long"]))
        this_data_schema=vol.Schema({vol.Optional(CONF_DATAPOINTS): "",vol.Optional(CONF_DATAPOINTS): ""})
        
        if len(datapoint_list_selector) == 0 and len(menuitem_list_selector) == 0:
            this_data_schema=vol.Schema(
            {
                vol.Optional(CONF_MENUITEMS): "",
                vol.Optional(CONF_DATAPOINTS): "" 
            }
            )
        elif len(datapoint_list_selector) == 0 and len(menuitem_list_selector) > 0:
            this_data_schema=vol.Schema(
            {
                vol.Optional(CONF_MENUITEMS, default=[]): selector.SelectSelector(selector.SelectSelectorConfig(options=menuitem_list_selector, multiple=True)),
                vol.Optional(CONF_DATAPOINTS): "" 
            }
            )
        elif len(datapoint_list_selector) > 0 and len(menuitem_list_selector) == 0:
            this_data_schema=vol.Schema(
                {
                vol.Optional(CONF_MENUITEMS): "",
                vol.Required(CONF_DATAPOINTS, default=[]): selector.SelectSelector(selector.SelectSelectorConfig(options=datapoint_list_selector, multiple=True))
                }
            )
        elif len(datapoint_list_selector) > 0 and len(menuitem_list_selector) > 0:
            this_data_schema=vol.Schema(
                {
                vol.Optional(CONF_MENUITEMS, default=[]): selector.SelectSelector(selector.SelectSelectorConfig(options=menuitem_list_selector, multiple=True)),
                vol.Required(CONF_DATAPOINTS, default=[]): selector.SelectSelector(selector.SelectSelectorConfig(options=datapoint_list_selector, multiple=True))
                }
            )
        _LOGGER.debug(f'Data schema: {this_data_schema}')
        return self.async_show_form(
            step_id="submenu",
            data_schema=this_data_schema,
            description_placeholders={"item_name": menutree_menulocation},
            errors=self._errors,
        )


    async def _test_credentials(self, host, protocol, username, password, timeout, retries):
        """Return true if credentials are valid."""
        try:
            self._session = async_create_clientsession(self.hass)
            self._client = SiemensOzw672ApiClient(host, protocol, username, password, self._session, timeout, retries)
            if (await self._client.async_get_sessionid()):
                return True
            return False
        except Exception:  # pylint: disable=broad-except
            pass
        return False

    async def _get_sysinfo(self):
        """Return the OZW672 system info, or None if it could not be fetched."""
        try:
            return await self._client.async_get_sysinfo()
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug(f'Exception: {repr(err)}')
            return None

    async def _get_devices(self):
        """Return the discovered device list, or None if it could not be fetched."""
        try:
            return await self._client.async_get_devices()
        except Exception as err: # pylint: disable=broad-except
            _LOGGER.debug(f'Exception: {repr(err)}')
            return None

    async def _get_menutree(self,id):
        """Return the menu tree for an id, or None if it could not be fetched."""
        try:
            return await self._client.async_get_menutree(id)
        except Exception as err: # pylint: disable=broad-except
            _LOGGER.debug(f'Exception: {repr(err)}')
            return None

    async def _get_datapoints(self,id):
        """Return the datapoints for an id, or None if they could not be fetched."""
        try:
            return await self._client.async_get_datapoints(id)
        except Exception as err: # pylint: disable=broad-except
            _LOGGER.debug(f'Exception: {repr(err)}')
            return None

    async def _get_data(self, datapoints):
        """Update data via OZW API."""
        try:
            return await self._client.async_get_data(datapoints)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug(f'Exception: {repr(err)}')
            return None

    async def _get_data_descr(self,datapoints,all_dpdata):
        """Return datapoint descriptions, or None if they could not be fetched."""
        try:
            return await self._client.async_get_data_descr(datapoints, all_dpdata)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug(f'Exception: {repr(err)}')
            return None

class SiemensOzw672OptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for siemens_ozw672."""

    def __init__(self):
        """Initialize options flow.

        Nothing is read from the config entry here: self.config_entry is not yet
        available during construction. It is populated in async_step_init instead.
        """
        self.options = None

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Offer the two things worth changing after setup."""
        if self.options is None:
            self.options = dict(self.config_entry.options)
            _LOGGER.debug(f'OptionsFlow - Existing options: {self.options}')
        return self.async_show_menu(step_id="init", menu_options=["settings", "priorities"])

    async def async_step_settings(self, user_input=None):
        """Connection settings, poll intervals and which entity domains are on."""
        if user_input is not None:
            self.options.update(user_input)
            _LOGGER.debug(f'Updating Options.  New Options: {self.options}')
            return self._update_options()

        def default(key, fallback):
            value = self.options.get(key)
            return fallback if value is None else value

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    # Bounded, because a bare int let a scan interval of 0 turn the
                    # coordinator into a tight polling loop and 0 retries stopped the
                    # client from issuing a single request.
                    vol.Required(CONF_HTTPTIMEOUT, default=default(CONF_HTTPTIMEOUT, DEFAULT_HTTPTIMEOUT)): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_HTTPTIMEOUT, max=MAX_HTTPTIMEOUT)
                    ),
                    vol.Required(CONF_HTTPRETRIES, default=default(CONF_HTTPRETRIES, DEFAULT_HTTPRETRIES)): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_HTTPRETRIES, max=MAX_HTTPRETRIES)
                    ),
                    # The three polling tiers. CONF_SCANINTERVAL keeps its name and
                    # its meaning as the fastest tier's interval.
                    vol.Required(CONF_SCANINTERVAL, default=default(CONF_SCANINTERVAL, DEFAULT_SCANINTERVAL)): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCANINTERVAL, max=MAX_SCANINTERVAL)
                    ),
                    vol.Required(CONF_INTERVAL_MEDIUM, default=default(CONF_INTERVAL_MEDIUM, DEFAULT_INTERVAL_MEDIUM)): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCANINTERVAL, max=MAX_SCANINTERVAL)
                    ),
                    vol.Required(CONF_INTERVAL_SLOW, default=default(CONF_INTERVAL_SLOW, DEFAULT_INTERVAL_SLOW)): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCANINTERVAL, max=MAX_SCANINTERVAL)
                    ),
                    # A deliberate pause between consecutive requests, for a device
                    # that struggles under a long poll.
                    vol.Required(CONF_REQUEST_DELAY, default=default(CONF_REQUEST_DELAY, DEFAULT_REQUEST_DELAY)): vol.All(
                        vol.Coerce(float), vol.Range(min=0, max=MAX_REQUEST_DELAY)
                    ),
                    vol.Required(CONF_USE_DEVICE_LONGNAME, default=default(CONF_USE_DEVICE_LONGNAME, DEFAULT_USE_DEVICE_LONGNAME)): bool,
                    vol.Required(CONF_VERIFY_SSL, default=default(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
                    vol.Required("switch", default=self.options.get("switch", True)): bool,
                    vol.Required("select", default=self.options.get("select", True)): bool,
                    vol.Required("number", default=self.options.get("number", True)): bool,
                    vol.Required("time", default=self.options.get("time", True)): bool,
                    vol.Required("binary_sensor", default=self.options.get("binary_sensor", True)): bool,
                    vol.Required("sensor", default=self.options.get("sensor", True)): bool,
                }
            )
        )

    async def async_step_priorities(self, user_input=None):
        """Re-assign datapoints to polling tiers without redoing discovery."""
        datapoints = self.config_entry.data.get(CONF_DATAPOINTS) or []
        if user_input is not None:
            data = dict(self.config_entry.data)
            data[CONF_DATAPOINTS] = apply_priorities(datapoints, user_input)
            # Priorities live in the datapoints, which are entry *data*. Writing
            # them here rather than into the options is what lets the reload pick
            # up the new tiers.
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self._update_options()
        return self.async_show_form(
            step_id="priorities",
            data_schema=priority_schema(datapoints),
            description_placeholders={"count": str(len(datapoints))},
        )

    def _update_options(self):
        """Update config entry options.

        The entry title follows the device-name choice here rather than in the
        update listener: renaming from inside async_setup_entry would fire the
        listener again and reload the entry a second time.
        """
        _LOGGER.debug("Updating options for entry %s", self.config_entry.title)
        if self.options.get(CONF_USE_DEVICE_LONGNAME):
            new_title = self.config_entry.data.get(CONF_DEVICE_LONGNAME)
        else:
            new_title = self.config_entry.data.get(CONF_DEVICE)
        if new_title and new_title != self.config_entry.title:
            self.hass.config_entries.async_update_entry(self.config_entry, title=new_title)
        return self.async_create_entry(title="", data=self.options)
