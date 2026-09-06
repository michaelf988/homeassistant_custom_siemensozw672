A Home Assistant integration for the Siemens OZW672 web server, which exposes LPB/BSB
heating plants (RVS controllers and their extension modules) over a local HTTP API.

This is a fork of
[johnaherninfotrack/homeassistant_custom_siemensozw672](https://github.com/johnaherninfotrack/homeassistant_custom_siemensozw672),
maintained by [@michaelf988](https://github.com/michaelf988). Report issues with this fork
[here](https://github.com/michaelf988/homeassistant_custom_siemensozw672/issues).

**This component sets up the following platforms:**

| Platform | Description |
| --- | --- |
| `binary_sensor` | Read-only `On` / `Off` state, e.g. a pump |
| `sensor` | Read-only values that fit no other category |
| `switch` | Read/write `On` / `Off` |
| `select` | Read/write enumerations |
| `number` | Read/write numbers, e.g. a temperature |
| `time` | Read/write times of day, e.g. a programme switching time |

![example](example.png)

{% if not installed %}

## Installation

1. Click install.
2. Restart Home Assistant.
3. Go to *Settings → Devices & Services*, click **+ Add Integration** and search for
   **Siemens OZW672**.

{% endif %}

## Configuration is done in the UI

The OZW672 reads exactly one datapoint per HTTP request and is a small embedded web server,
so **poll only what you need**. Discovery can be re-run later to add more datapoints — pick
one function and at most ten datapoints at a time.

Every datapoint is assigned to one of three polling tiers, each with its own interval:

| Tier | Default | Typical use |
| --- | --- | --- |
| Priority 1 — fast | 60 s | Anything an automation reacts to |
| Priority 2 — medium | 300 s | Setpoints, operating modes |
| Priority 3 — slow | 900 s | Meter readings, diagnostics |

The last setup step sorts the selected datapoints into the fast and medium tiers; anything
left unpicked stays slow. The assignment can be changed later from the integration's
options, without redoing discovery.

Entities can be prefixed with the function name, the operating line number from the manual,
both, or neither — for example `DHW - 1640 Legionella function`.

### Recommendations for reliable operation

1. Use HTTP rather than HTTPS; it is measurably more scalable on this hardware. Enable it
   first on the device: *Home → 0.x OZW672.01 → Settings → Communication → Services → We
   access via http = ON*.
2. Give the OZW672 a static IP, gateway and DNS: *Home → 0.x OZW672.01 → Settings →
   Communication → Ethernet*.
3. Use a dedicated user on the OZW672 for Home Assistant polling — the *Service* user group
   works well.

HTTPS certificate verification is off by default, because the device ships a self-signed
certificate. It can be switched on in the options if you installed a trusted one.

## Credits

Original integration by [@johnaherninfotrack](https://github.com/johnaherninfotrack),
written on an OZW672.01 monitoring a home hydronic plant. This fork builds on that work.

## Disclaimer

**Independent, unofficial, community-developed project. Not affiliated with, endorsed by,
sponsored by, or approved by Siemens AG or any of its subsidiaries.**

"Siemens", "OZW672", "RVS43" and other product and model designations are trademarks or
registered trademarks of Siemens AG or their respective owners, used here nominatively only
to identify the hardware this integration communicates with. The bundled icon and logo are
original artwork created for this project — they are not Siemens assets and do not represent
Siemens branding.

This integration uses the local HTTP API exposed by the device itself and contains no
Siemens source code, firmware, or other proprietary material. Provided under the MIT License
without warranty of any kind; you use it, and any changes it writes to your equipment, at
your own risk.
