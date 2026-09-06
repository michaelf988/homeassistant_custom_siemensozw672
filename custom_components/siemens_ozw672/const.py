"""Constants for Siemens OZW672."""
# Base component constants
NAME = "Siemens OZW672"
DOMAIN = "siemens_ozw672"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.6.0"
CONF_VERSION = 1
CONF_MINOR_VERSION = 7

ATTRIBUTION = "Siemens OZW672 integration, originally created by John Ahern"
# Shown as the device manufacturer in Home Assistant. Nominative use only - see
# the trademark note in the README; device_info used to report the integration
# name as the manufacturer and the integration version as the model.
MANUFACTURER = "Siemens"
ISSUE_URL = "https://github.com/michaelf988/homeassistant_custom_siemensozw672/issues"

# Icons
ICON = "mdi:bookmark"
ICON_THERMOMETER ="mdi:thermometer"
ICON_PERCENT ="mdi:percent"
ICON_ENUM="mdi:bookmark"
ICON_SWITCH="mdi:toggle-switch"
ICON_SELECT="mdi:gesture-tap"
ICON_NUMERIC="mdi:numeric"
ICON_POWER="mdi:lightning-bolt"
ICON_TIME="mdi:clock-outline"



# Device classes
BINARY_SENSOR_DEVICE_CLASS = "power"


# Platforms
BINARY_SENSOR = "binary_sensor"
SENSOR = "sensor"
SWITCH = "switch"
SELECT = "select"
NUMBER = "number"
TIME = "time"
PLATFORMS = [SWITCH, SELECT, NUMBER, TIME, BINARY_SENSOR, SENSOR]


# Configuration and options
CONF_ENABLED = "enabled"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_HOST = "hostname"
CONF_DEVICE = "devicename"
CONF_DEVICE_LONGNAME = "devicelongname"
CONF_DEVICE_ID = "deviceid"
CONF_PROTOCOL = "protocol"
CONF_MENUITEMS = "menuitems"
CONF_DATAPOINTS = "datapoints"
CONF_PREFIX_FUNCTION = "prefix_with_function"
CONF_PREFIX_OPLINE = "prefix_with_opline"
CONF_SCANINTERVAL = "scaninterval"
CONF_HTTPTIMEOUT = "httptimeout"
CONF_HTTPRETRIES = "httpretries"
CONF_USE_DEVICE_LONGNAME = "use_device_longname"
CONF_VERIFY_SSL = "verify_ssl"
CONF_REQUEST_DELAY = "request_delay"

# Polling priorities. The OZW672 is a small embedded web server and every datapoint
# costs it one HTTP request, so not everything deserves the same poll rate. Each
# configured datapoint carries one of these under CONF_PRIORITY, and each tier gets
# its own coordinator with its own interval.
CONF_PRIORITY = "Priority"
PRIORITY_FAST = "fast"
PRIORITY_MEDIUM = "medium"
PRIORITY_SLOW = "slow"
PRIORITIES = (PRIORITY_FAST, PRIORITY_MEDIUM, PRIORITY_SLOW)
# Datapoints configured before priorities existed, and anything not explicitly
# raised, land in the middle tier.
DEFAULT_PRIORITY = PRIORITY_MEDIUM

# Form keys for the priority-assignment step.
CONF_PRIORITY_FAST = "priority_fast"
CONF_PRIORITY_MEDIUM = "priority_medium"

# CONF_SCANINTERVAL keeps its name and its role as the *fastest* tier's interval,
# so an existing entry's stored value keeps meaning what it always meant.
CONF_INTERVAL_MEDIUM = "interval_medium"
CONF_INTERVAL_SLOW = "interval_slow"

DEFAULT_HTTPTIMEOUT = 30
DEFAULT_HTTPRETRIES = 2
DEFAULT_SCANINTERVAL = 60
DEFAULT_PREFIX_FUNCTION = True
DEFAULT_PREFIX_OPLINE = True
DEFAULT_USE_DEVICE_LONGNAME = False
# The OZW672 speaks HTTPS with a self-signed certificate, so verification stays off
# by default to keep existing installations working. It is an option rather than a
# hard-coded `verify_ssl=False` so anyone who does install a trusted certificate can
# turn it on.
DEFAULT_VERIFY_SSL = False
DEFAULT_INTERVAL_MEDIUM = 300
DEFAULT_INTERVAL_SLOW = 900
# Extra pause between consecutive requests to the device, in seconds. 0 keeps the
# previous behaviour; raise it if the OZW672 struggles under a long poll.
DEFAULT_REQUEST_DELAY = 0.0
MAX_REQUEST_DELAY = 10.0

# Which option carries each tier's interval, and what it defaults to.
PRIORITY_INTERVAL_OPTIONS = {
    PRIORITY_FAST: (CONF_SCANINTERVAL, DEFAULT_SCANINTERVAL),
    PRIORITY_MEDIUM: (CONF_INTERVAL_MEDIUM, DEFAULT_INTERVAL_MEDIUM),
    PRIORITY_SLOW: (CONF_INTERVAL_SLOW, DEFAULT_INTERVAL_SLOW),
}

# Bounds for the numeric options. The options dialog accepted any int, so a scan
# interval of 0 turned the coordinator into a tight polling loop and 0 retries meant
# `for x in range(0)` never ran a single request - the integration went silently dead.
MIN_SCANINTERVAL = 10
MAX_SCANINTERVAL = 86400
MIN_HTTPTIMEOUT = 5
MAX_HTTPTIMEOUT = 300
MIN_HTTPRETRIES = 1
MAX_HTTPRETRIES = 10

DEFAULT_OPTIONS = {'httptimeout': DEFAULT_HTTPTIMEOUT, 
    'httpretries': DEFAULT_HTTPRETRIES, 
    'scaninterval': DEFAULT_SCANINTERVAL, 
    CONF_PREFIX_FUNCTION: DEFAULT_PREFIX_FUNCTION, 
    CONF_PREFIX_OPLINE: DEFAULT_PREFIX_OPLINE, 
    CONF_USE_DEVICE_LONGNAME: DEFAULT_USE_DEVICE_LONGNAME,
    CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
    CONF_INTERVAL_MEDIUM: DEFAULT_INTERVAL_MEDIUM,
    CONF_INTERVAL_SLOW: DEFAULT_INTERVAL_SLOW,
    CONF_REQUEST_DELAY: DEFAULT_REQUEST_DELAY,
    'switch': True, 'select': True, 'number': True, 'time': True,
    'binary_sensor': True, 'sensor': True
}

# Defaults
DEFAULT_NAME = DOMAIN


STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""


TESTDATA={}
TESTDATA["PREAUTH"]="""{"SessionId": "8ee67600-b4d8-4f66-b48e-ca2eabd1f2e7", "Result": {"Success": "true"}}"""
TESTDATA["DEVICELIST"]="""{"Devices": [{"Name": "OZW672.01", "Addr": "0.5", "Type": "OZW672.01", "SerialNr": "00FD3100033C", "TreeDate": "22.05.2023", "TreeTime": "16:19", "TreeGenerated": "true"}, {"Name": "RVS43.345/109a", "Addr": "0.1", "Type": "RVS43.345/109", "SerialNr": "008600004EBF", "TreeDate": "08.06.2023", "TreeTime": "20:15", "TreeGenerated": "true"}], "Result": {"Success": "true"}}"""
TESTDATA["MENUTREEDEVICELIST"]="""{"MenuItems": [{"Id": "1327", "Text": {"CatId": "2", "GroupId": "4", "Id": "106", "Long": "0.1 RVS43.345/109", "Short": "TSP 1"}}, {"Id": "2", "Text": {"CatId": "1", "GroupId": "4", "Id": "106", "Long": "0.5 OZW672.01", "Short": "Device"}}], "DatapointItems": [], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["SYSINFOLIST"]="""{"Device": {"Name": "OZW672.01", "Addr": "0.5", "Type": "OZW672.01", "FabNr": "021863", "SerialNr": "00FD3100033C", "FwVersion": "00.11.00", "SysDefVersion": "02.29.01"}, "Result": {"Success": "true"}}"""

TESTDATA["MENUITEMLIST"]={}
TESTDATA["MENUITEMLIST"]["1327"]="""{"MenuItems": [{"Id": "1437", "Text": {"CatId": "2", "GroupId": "4", "Id": "295", "Long": "DHW", "Short": "DHW"}},{"Id": "1959","Text": {"CatId": "2","GroupId": "4","Id": "315","Long": "Diagnostics consumer","Short": "Diagnostics consumer"}}], "DatapointItems": [], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1437"]="""{"MenuItems": [], "DatapointItems": [{"Id": "1438", "Address": "0x310571", "DpSubKey": "0", "WriteAccess": "true", "Text": {"CatId": "2", "GroupId": "2", "Id": "3514", "Long": "DHW operating mode", "Short": "DHW OptgMode"}}, {"Id": "1439", "Address": "0x3106b9", "DpSubKey": "0", "WriteAccess": "true", "Text": {"CatId": "2", "GroupId": "2", "Id": "3516", "Long": "DHW temperature nominal setpoint", "Short": "DHW NomSetp"}}, {"Id": "1441", "Address": "0x250722", "DpSubKey": "0", "WriteAccess": "true", "Text": {"CatId": "2", "GroupId": "2", "Id": "3522", "Long": "DHW release", "Short": "DHW Release"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1438"]="""{"MenuItems": [], "DatapointItems": [{"Id": "1438", "Address": "0x310571", "DpSubKey": "0", "WriteAccess": "true", "Text": {"CatId": "2", "GroupId": "2", "Id": "3514", "Long": "DHW operating mode", "Short": "DHW OptgMode"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1439"]="""{"MenuItems": [], "DatapointItems": [{"Id": "1439", "Address": "0x3106b9", "DpSubKey": "0", "WriteAccess": "true", "Text": {"CatId": "2", "GroupId": "2", "Id": "3516", "Long": "DHW temperature nominal setpoint", "Short": "DHW NomSetp"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1441"]="""{"MenuItems": [], "DatapointItems": [{"Id": "1441", "Address": "0x250722", "DpSubKey": "0", "WriteAccess": "true", "Text": {"CatId": "2", "GroupId": "2", "Id": "3522", "Long": "DHW release", "Short": "DHW Release"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1959"]="""{"MenuItems": [{"Id": "9998", "Text": {"CatId": "2", "GroupId": "4", "Id": "999", "Long": "SubMenu1", "Short": "SubMenu1"}}], "DatapointItems": [{"Id":"1960","Address":"0x50521","DpSubKey":"0","WriteAccess":"false","Text":{"CatId":"2","GroupId":"2","Id":"39","Long":"Outside temp","Short":"Outside temp"}},{"Id":"1961","Address":"0x50522","DpSubKey":"0","WriteAccess":"false","Text":{"CatId":"2","GroupId":"2","Id":"40","Long":"Test Generic Number","Short":"Test Generic Number"}},{"Id":"1966","Address":"0x509a5","DpSubKey":"0","WriteAccess":"false","Text":{"CatId":"2","GroupId":"2","Id":"5328","Long":"Status heat circuit pump 1","Short":"Heatcircuitpump1"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1962"]="""{"MenuItems": [], "DatapointItems": [{"Id":"1962","Address":"0x50523","DpSubKey":"0","WriteAccess":"true","Text":{"CatId":"2","GroupId":"2","Id":"41","Long":"Test Writeable Energy","Short":"Test Writeable Energy"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1960"]="""{"MenuItems": [], "DatapointItems": [{"Id":"1960","Address":"0x50521","DpSubKey":"0","WriteAccess":"false","Text":{"CatId":"2","GroupId":"2","Id":"39","Long":"Outside temp","Short":"Outside temp"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1961"]="""{"MenuItems": [], "DatapointItems": [{"Id":"1961","Address":"0x50522","DpSubKey":"0","WriteAccess":"false","Text":{"CatId":"2","GroupId":"2","Id":"40","Long":"Test Generic Number","Short":"Test Generic Number"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["1966"]="""{"MenuItems": [], "DatapointItems": [{"Id":"1966","Address":"0x509a5","DpSubKey":"0","WriteAccess":"false","Text":{"CatId":"2","GroupId":"2","Id":"5328","Long":"Status heat circuit pump1","Short":"Heatcircuitpump1"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""
TESTDATA["MENUITEMLIST"]["9998"]="""{"MenuItems": [], "DatapointItems": [{"Id":"9999","Address":"0x31057","DpSubKey":"0","WriteAccess":"true","Text":{"CatId":"2","GroupId":"2","Id":"9999","Long":"Test Submenu DataPoint1","Short":"Test Submenu DataPoint1"}}], "WidgetItems": [], "Result": {"Success": "true"}}"""

TESTDATA["DATAPOINT"]={}
TESTDATA["DATAPOINT"]["1438"]="""{"Data": {"Type": "Enumeration", "Value": "On", "Unit": ""}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1439"]="""{"Data": {"Type": "Numeric", "Value": "        52", "Unit": "°C"}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1441"]="""{"Data": {"Type": "Enumeration", "Value": "24h/day", "Unit": "", "EnumValue": "0"}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1960"]="""{"Data": {"Type": "Numeric","Value": " 15.8","Unit": "°C"}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1963"]="""{"Data": {"Type": "Numeric","Value": "----","Unit": "\u00b0C"}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1966"]="""{"Data": {"Type": "RadioButton","Value": "On","Unit": ""},"Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1970"]="""{"Data": {"Type": "TimeOfDay","Value": "06:30","Unit": ""}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1962"]="""{"Data": {"Type": "Numeric","Value": " 120.0","Unit": "kWh"}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["1961"]="""{"Data": {"Type": "Numeric","Value": " 15.0","Unit": "kWh"}, "Result": {"Success": "true"}}"""
TESTDATA["DATAPOINT"]["9999"]="""{"Data": {"Type": "RadioButton","Value": "On","Unit": ""},"Result": {"Success": "true"}}"""

TESTDATA["DATAPOINTDESCR"]={}
TESTDATA["DATAPOINTDESCR"]["1438"]="""{"Description":{"Type":"Enumeration","Name":"DHW operating mode","Enums":[{"Text":"Off","Value":"0","IsCurrentValue":"false"},{"Text":"On","Value":"1","IsCurrentValue":"true"},{"Text":"Eco","Value":"2","IsCurrentValue":"false"}]},"Result":{"Success":"true"}}"""
TESTDATA["DATAPOINTDESCR"]["1439"]="""{"Description":{"Type":"Numeric","Value":"52.000000","Unit":"°C","Name":"DHW temperature nominal setpoint","Min":"45.000000","Max":"60.000000","Resolution":"1.000000","FieldWitdh":"10","DecimalDigits":"0","HasValid":"false","IsValid":"true"},"Result":{"Success":"true"}}"""
TESTDATA["DATAPOINTDESCR"]["1441"]="""{"Description":{"Type":"Enumeration","Name":"DHW release","Enums":[{"Text":"24h/day","Value":"0","IsCurrentValue":"true"},{"Text":"Heating programs with forward shift","Value":"1","IsCurrentValue":"false"},{"Text":"Time switch program 4","Value":"2","IsCurrentValue":"false"}]},"Result":{"Success":"true"}}"""
TESTDATA["DATAPOINTDESCR"]["1960"]="""{"Description":{"Type":"Numeric","Value":"15.859375","Unit":"°C","Name":"Outside temp","Min":"-50.000000","Max":"50.000000","Resolution":"0.100000","FieldWitdh":"12","DecimalDigits":"1","HasValid":"false","IsValid":"true"},"Result":{"Success":"true"}}"""
TESTDATA["DATAPOINTDESCR"]["1966"]="""{"Description":{"Type":"RadioButton","Name": "Status heat circuit pump 1","Buttons":[{"TextOpt0": "Off","TextOpt1": "On","Significance": "1","IsActive": "true"} ]},"Result": {"Success": "true"}}"""
TESTDATA["DATAPOINTDESCR"]["1961"]="""{"Description":{"Type":"Numeric","Value":"15.0","Unit":"kWh","Name":"Test Generic Number","Min":"0.000000","Max":"2147483647.0000005","Resolution":"1.000000","FieldWitdh":"10","DecimalDigits":"0","HasValid":"false","IsValid":"true"},"Result":{"Success":"true"}}"""
TESTDATA["DATAPOINTDESCR"]["1970"]="""{"Description":{"Type":"TimeOfDay","Name":"Standby start"},"Result":{"Success":"true"}}"""
TESTDATA["DATAPOINTDESCR"]["1962"]="""{"Description":{"Type":"Numeric","Value":"120.0","Unit":"kWh","Name":"Test Writeable Energy","Min":"0.000000","Max":"100000.000000","Resolution":"1.000000","FieldWitdh":"10","DecimalDigits":"1","HasValid":"false","IsValid":"true"},"Result":{"Success":"true"}}"""
TESTDATA["DATAPOINTDESCR"]["9999"]="""{"Description":{"Type":"RadioButton","Name": "Test Submenu DataPoint1","Buttons":[{"TextOpt0": "Off","TextOpt1": "On","Significance": "1","IsActive": "true"} ]},"Result": {"Success": "true"}}"""



