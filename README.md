# Siemens OZW672 Integration for Home Assistant

A Home Assistant integration for the Siemens OZW672 web server, which exposes LPB/BSB
heating plants (RVS controllers and their extension modules) over a local HTTP API.

> **This is a fork.** The original integration is
> [johnaherninfotrack/homeassistant_custom_siemensozw672](https://github.com/johnaherninfotrack/homeassistant_custom_siemensozw672)
> by [@johnaherninfotrack](https://github.com/johnaherninfotrack). This fork is maintained
> independently by [@michaelf988](https://github.com/michaelf988) and is not endorsed by
> the original author. Report issues with *this* fork
> [here](https://github.com/michaelf988/homeassistant_custom_siemensozw672/issues), not
> upstream. See [CHANGELOG.md](CHANGELOG.md) for what differs.

## Overview

The OZW672 is a web server platform for remote monitoring of Siemens LPB/BSB plants. The
original integration was built and tested against an OZW672.01 running firmware v11.0,
monitoring an RVS43.345/109 with three AVS73.390/109 extension modules.

You can also **write** values back to the OZW672, with three caveats:

1. The OZW672 marks only certain datapoints as writeable.
2. Writing is supported for enumerations, numbers, switches and times of day.
3. Some writes are silently ignored by the device. If that happens, check the same
   datapoint in the OZW672's own web UI.

### Entity types

| Platform | Description |
| --- | --- |
| `binary_sensor` | Read-only `On` / `Off` state, e.g. a pump |
| `sensor` | Read-only values that fit no other category |
| `switch` | Read/write `On` / `Off` |
| `select` | Read/write enumerations |
| `number` | Read/write numbers, e.g. a temperature or percentage |
| `time` | Read/write times of day, e.g. a programme switching time |

![example](example.png)

## Installation

**Via HACS** (recommended):

1. In HACS → *Integrations*, open the three-dot menu → *Custom repositories*.
2. Add `https://github.com/michaelf988/homeassistant_custom_siemensozw672` with category
   *Integration*.
3. *Explore & Download Repositories*, search for **Siemens OZW672**, download.
4. Restart Home Assistant.

**Manually**: copy `custom_components/siemens_ozw672/` into your Home Assistant
`custom_components/` directory and restart.

Then add the integration under *Settings → Devices & Services → + Add Integration* and
search for **Siemens OZW672**. Configuration is done entirely in the UI; there is no YAML
configuration.

## Polling priorities

The OZW672 reads exactly one datapoint per HTTP request, and it is a small embedded web
server. Polling 60 datapoints every minute means 60 requests a minute, which is what makes
a large selection slow and, on a busy plant, unreliable.

Every datapoint is therefore assigned to one of three polling tiers:

| Tier | Default interval | Typical use |
| --- | --- | --- |
| Priority 1 — fast | 60 s | Flow temperature, burner state — anything an automation reacts to |
| Priority 2 — medium | 300 s | Setpoints, operating modes |
| Priority 3 — slow | 900 s | Meter readings, diagnostics, anything you only look at |

The tier is chosen on the same screen as the datapoint: one checkbox list per tier.
Home Assistant cannot render a per-row radio group, so this is as close as it gets, and a
datapoint ticked in more than one tier is rejected rather than guessed at. *Also take
everything else on this screen at priority 3* sweeps up the remainder — so the usual
pattern is to tick the few that need to be current, then one box for the rest.

Each datapoint is offered with the value the device reports right now. Plenty of them do
not apply to a given plant and read `----`; one of those costs a request on every poll
and produces a permanently unknown entity, so it is worth seeing before picking it.

Each tier is polled by its own coordinator with its own interval, and a tier with no
datapoints is never polled at all. All three share one connection and one lock, so the
device never sees two requests at once. If it still struggles, raise *Pause between
requests* in the options.

To change the assignment later, open the integration's options and choose *Which
datapoints are polled how often*. Config entries created before this existed are migrated
into the medium tier.

## Adding and removing datapoints later

- **Adding**: run the integration's setup again and pick the same device. The existing
  entry is updated rather than duplicated, and only datapoints you have not configured
  yet are offered.
- **Removing**: options → *Which datapoints are configured*. Untick what you no longer
  want polled.

Removing matters more than it looks: **disabling an entity in Home Assistant does not
stop its datapoint being polled.** The coordinator works from the configured datapoints,
not from entity states, so a disabled entity still costs the OZW672 a request on every
poll. Removing it here is what actually stops that. The entity stays in the registry as
unavailable and can be deleted there.

## Options

Open the integration's options and choose *Connection, polling intervals and entity
domains*:

| Option | Default | Notes |
| --- | --- | --- |
| HTTP timeout | 30 s | |
| HTTP retries | 2 | |
| Polling interval, priority 1/2/3 | 60 / 300 / 900 s | See above |
| Pause between requests | 0 s | Deliberate gap between consecutive requests |
| Verify the HTTPS certificate | off | The device ships a self-signed certificate; turn this on only if you installed a trusted one |
| Use the device Addr+Type as the name | off | |
| Switch / select / number / time / binary sensor / sensor | on | Turn an entity domain off entirely |

## Recommendations for reliable operation

1. **Use HTTP rather than HTTPS.** It is measurably more scalable on this hardware. Enable
   it first on the device: *Home → 0.x OZW672.01 → Settings → Communication → Services →
   We access via http = ON*.
2. **Give the OZW672 a static IP, gateway and DNS**: *Home → 0.x OZW672.01 → Settings →
   Communication → Ethernet*.
3. **Discover a few datapoints at a time.** Pick one function and at most ten datapoints
   per run, then re-run discovery to add more. The selection screens are checkbox lists
   with a *select everything* option, and *◀ Go back to the previous step* returns to the
   previous screen if you want to change something — repeatedly, all the way back to the
   main menu.
4. **Use a dedicated user** on the OZW672 for Home Assistant polling — the *Service* user
   group works well.

### Entity naming

Entities can be prefixed two ways, chosen during setup:

- no prefix — `Legionella function`
- function/menu item — `DHW - Legionella function`
- operating line number from the manual — `1640 Legionella function`
- both — `DHW - 1640 Legionella function`

Note that from Home Assistant 2026.8, entity IDs of entities attached to a device also
carry the device name (`sensor.rvs43_outside_temp`). That is Home Assistant's own naming,
independent of these prefixes.

## Development

```console
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
python -m pytest
```

The test suite pins the Home Assistant version it runs against — currently 2026.8.3 on
Python 3.14. Every push and pull request runs `hassfest`, the HACS validation and the full
suite; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Releasing

The version lives in `manifest.json` and `const.py`, and the release workflow refuses a tag
that disagrees with the manifest. To cut a release:

1. `python scripts/set_version.py 0.6.0`
2. Add the matching `## 0.6.0` section to `CHANGELOG.md`.
3. Commit and push. CI runs hassfest, the HACS validation and the test suite.
4. Run the **Release** workflow from the Actions tab with **publish** ticked.

That builds `siemens_ozw672.zip` from `custom_components/siemens_ozw672/`, tags the commit
`v0.6.0`, and publishes a release whose notes are the `## 0.6.0` section of the changelog —
so the release and the changelog cannot drift apart. It refuses to run if a release for
that tag already exists.

Running the same workflow with **publish** unticked is a dry run: everything except the
publish, with the archive kept as a downloadable build artifact.

Publishing from the Releases page by hand still works and takes the same path — the
workflow checks the tag against `manifest.json` and attaches the archive. `hacs.json` sets
`zip_release`, so HACS installs that archive rather than cloning the repository.

A test guards the whole chain: `manifest.json`, `const.VERSION`, the changelog heading and
the config flow's schema version all have to agree before anything is tagged.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). When reporting a bug,
please enable debug logging and attach the logs:

```yaml
logger:
  default: info
  logs:
    custom_components.siemens_ozw672: debug
```

## Credits

Original integration by [@johnaherninfotrack](https://github.com/johnaherninfotrack),
written on an OZW672.01 monitoring a home hydronic plant. This fork builds on that work.

The project was generated from [@oncleben31](https://github.com/oncleben31)'s
[Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component),
with the code template largely from [@Ludeeus](https://github.com/ludeeus)'s
[integration_blueprint](https://github.com/custom-components/integration_blueprint).

## Disclaimer

**This is an independent, unofficial, community-developed project. It is not affiliated
with, endorsed by, sponsored by, or approved by Siemens AG or any of its subsidiaries.**

"Siemens", "OZW672", "RVS43", "AVS73" and other product and model designations are
trademarks or registered trademarks of Siemens AG or their respective owners. They are used
here **nominatively** — that is, solely to identify the hardware this integration
communicates with, as is permitted for accurate description of interoperability. No claim
to those marks is made or implied.

The icon and logo shipped with this integration are **original artwork created for this
project**. They are not Siemens assets, are not reproductions of any Siemens logo or
wordmark, and do not represent Siemens branding or an official Siemens product.

This integration talks to the OZW672 over the local HTTP API exposed by the device itself.
It contains no Siemens source code, firmware, or other proprietary Siemens material, and
distributes none.

The software is provided under the MIT License **without warranty of any kind** — see
[LICENSE](LICENSE). You use it, and any changes it writes to your equipment, at your own
risk.

If you are a rights holder and believe anything here misrepresents your brand, please open
an issue on the
[issue tracker](https://github.com/michaelf988/homeassistant_custom_siemensozw672/issues)
and it will be addressed promptly.
