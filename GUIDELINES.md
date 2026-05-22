# Home Assistant Integration – Best Practices & Framework Guidelines für Claude Code

> **Zweck dieses Dokuments:** Du (Claude Code) entwickelst eine HACS Custom Component für eine Wärmepumpe, die über lokale REST/HTTP‑Calls im LAN kommuniziert (`iot_class: local_polling`, optional `local_push`). Dieses Dokument ist deine verbindliche Referenz für **wie** integriert wird – nicht **was** an Wärmepumpen‑Domänenlogik gemacht wird. Ziel ist eine Integration, die zugleich **HACS‑konform** ist und **Core‑mergeable** bleibt (Quality Scale Bronze → idealerweise Silver/Gold). Stand: HA Core 2026.x, Python 3.13+.
>
> Wenn Unsicherheit besteht: **NICHT raten** – im Zweifel das jeweils verlinkte Dokument unter `developers.home-assistant.io` per Fetch konsultieren. Das ist die kanonische Quelle. Sekundärquellen (Blogs, Community‑Posts) sind bestenfalls Hinweise.

---

## 0. Leitprinzipien (TL;DR der Regeln)

1. **Async‑first, immer.** Kein blockierendes I/O im Event‑Loop. Wenn eine Bibliothek synchron ist → `hass.async_add_executor_job(...)`. Besser: eine vollständig async‑Bibliothek schreiben (Platinum‑Voraussetzung).
2. **Keine eigene `aiohttp.ClientSession`.** Immer `async_get_clientsession(hass)` aus `homeassistant.helpers.aiohttp_client` benutzen, wenn keine Cookies oder Sondereinstellungen nötig sind. Sonst `async_create_clientsession(hass, ...)`. Quelle: `homeassistant/helpers/aiohttp_client.py`.
3. **Eine API‑Client‑Klasse, sauber von HA entkoppelt.** Idealerweise als eigenes PyPI‑Package (z. B. `pyheatpumpxy`), sodass die Integration nur dünner Wrapper ist (HA‑Idiom „Integration ist Glue Code"). Quality‑Scale‑Regel `dependency-transparency`.
4. **`DataUpdateCoordinator` ist Pflicht** für jedes Polling. Eigene Polling‑Schleifen oder `async_track_time_interval` zum Daten‑Holen sind Anti‑Pattern.
5. **Config Flow only.** Kein YAML‑Setup. ADR‑0010 sagt klar: für Geräte/Services ist UI‑Setup verbindlich. Quality‑Scale‑Regel `config-flow`.
6. **`ConfigEntry.runtime_data`** statt `hass.data[DOMAIN][entry.entry_id]`. Seit 2024.5 idiomatisch, ab 2024.11 für Bronze verpflichtend.
7. **`EntityDescription`‑Pattern** für alle Entities, **nicht** Property‑Salat.
8. **Strict typing**, `from __future__ import annotations`, kein `Any` ohne Begründung. Platinum‑Regel `strict-typing`.
9. **Keine Klartext‑Strings im UI.** Alles über `strings.json` + `translations/<lang>.json` und `translation_key`.
10. **Tests sind keine Optionen.** Bronze fordert `config-flow-test-coverage` (100 % im Config Flow), Silver fordert `> 95 %` Gesamt‑Coverage.

Direkter Einstieg: <https://developers.home-assistant.io/docs/creating_integration_file_structure/>

---

## 1. Projektstruktur

### 1.1 Verzeichnisbaum (HACS‑konform und Core‑konform)

```
heatpump_xy/                              # GitHub‑Repo‑Root
├── README.md                             # Pflicht für HACS
├── hacs.json                             # Pflicht im Repo‑Root für HACS
├── LICENSE
├── .github/
│   └── workflows/
│       ├── hassfest.yaml                 # home-assistant/actions/hassfest@master
│       ├── hacs.yaml                     # hacs/action@main
│       └── tests.yaml                    # pytest mit pytest-homeassistant-custom-component
├── custom_components/
│   └── heatpump_xy/                      # Domain – muss exakt manifest.json:domain entsprechen
│       ├── __init__.py                   # async_setup_entry / async_unload_entry
│       ├── manifest.json                 # Pflicht
│       ├── const.py                      # DOMAIN, CONF_*, defaults
│       ├── config_flow.py                # ConfigFlow + OptionsFlow
│       ├── coordinator.py                # DataUpdateCoordinator
│       ├── entity.py                     # gemeinsame Basisklasse (CoordinatorEntity)
│       ├── api.py                        # API-Client-Wrapper (oder externes PyPI-Package)
│       ├── sensor.py                     # Plattform: Sensoren
│       ├── climate.py                    # Plattform: Climate-Entity
│       ├── binary_sensor.py              # falls nötig
│       ├── number.py / select.py / switch.py
│       ├── diagnostics.py                # Pflicht ab Gold
│       ├── repairs.py                    # falls Repair-Flows existieren
│       ├── services.yaml                 # nur wenn eigene Services registriert
│       ├── strings.json                  # UI-Strings (Quelle für en.json)
│       ├── translations/
│       │   ├── en.json
│       │   └── de.json
│       ├── icons.json                    # Icon-Translations (Gold-Regel)
│       ├── quality_scale.yaml            # Pflicht sobald ein Quality-Scale-Level angestrebt wird
│       └── brand/                        # ab HA 2026.3 lokal möglich (siehe §17.3)
│           ├── icon.png
│           ├── icon@2x.png
│           ├── logo.png
│           └── logo@2x.png
└── tests/                                # nicht im HACS-Download enthalten
    ├── __init__.py
    ├── conftest.py
    ├── test_config_flow.py
    ├── test_coordinator.py
    ├── test_init.py
    ├── test_sensor.py
    ├── fixtures/
    │   └── status_response.json
    └── snapshots/                        # syrupy-Snapshots
```

**Wichtig:**
- HACS erwartet die Integration unter `custom_components/<domain>/`. Bei einem späteren Core‑Merge wandert genau dieses Verzeichnis nach `homeassistant/components/<domain>/` – die `tests/` werden zu `tests/components/<domain>/`.
- Der Verzeichnisname `heatpump_xy` **muss** dem `domain`‑Feld in `manifest.json` exakt entsprechen, sonst schlägt hassfest fehl.

Referenzen:
- <https://developers.home-assistant.io/docs/creating_integration_file_structure/>
- <https://hacs.xyz/docs/publish/integration/>

### 1.2 Empfohlener Startpunkt

Das offizielle **`integration_blueprint`** Repo (<https://github.com/home-assistant/integration_blueprint>) ist die kanonische Vorlage. Es enthält Coordinator, Config Flow, Sensor‑Plattform, Tests und HACS‑Konformität – darauf aufsetzen statt von Null beginnen.

---

## 2. `manifest.json`

### 2.1 Vollständiges Schema (Core‑Quelle: `homeassistant/loader.py`)

```json
{
  "domain": "heatpump_xy",
  "name": "Heatpump XY",
  "version": "0.1.0",
  "codeowners": ["@christian"],
  "config_flow": true,
  "dependencies": [],
  "after_dependencies": ["zeroconf"],
  "documentation": "https://github.com/christian/ha-heatpump-xy",
  "issue_tracker": "https://github.com/christian/ha-heatpump-xy/issues",
  "integration_type": "device",
  "iot_class": "local_polling",
  "loggers": ["pyheatpumpxy"],
  "requirements": ["pyheatpumpxy==0.4.2"],
  "quality_scale": "bronze",
  "zeroconf": [
    { "type": "_heatpump._tcp.local.", "properties": { "vendor": "xy*" } }
  ],
  "dhcp": [
    { "macaddress": "AABBCC*", "hostname": "heatpump-*" }
  ]
}
```

### 2.2 Feldweise Pflicht/Optional und HACS vs Core

| Feld | Custom (HACS) | Core | Hinweis |
|---|---|---|---|
| `domain` | Pflicht | Pflicht | Lowercase + Underscore, == Verzeichnisname |
| `name` | Pflicht | Pflicht | Bei „Cloud" Suffix auch „Cloud" anhängen; lokal kein Suffix |
| `version` | **Pflicht** für Custom | **Verboten** für Core | HACS lehnt Manifest ohne `version` ab; Core wird via `pip` getrackt |
| `codeowners` | Pflicht (≥ 1 GitHub‑Handle) | Pflicht | Silver: aktive Maintainer (`integration-owner`) |
| `config_flow` | `true` | `true` | YAML‑Setup ist tot, ADR‑0010 |
| `documentation` | Pflicht | Pflicht (`https://www.home-assistant.io/integrations/<domain>`) | Custom: GitHub‑README oder eigene Seite |
| `issue_tracker` | Pflicht | weglassen (auto‑generiert) | |
| `integration_type` | `device` / `hub` / `service` / `helper` / `system` / `hardware` / `entity` / `virtual` | dito | Wärmepumpe = `device` (ein physisches Gerät pro Entry). Ein zentrales LAN‑Gateway für mehrere Geräte = `hub`. |
| `iot_class` | Pflicht | Pflicht | Für lokale Wärmepumpe: `local_polling` (oder `local_push` falls Push) |
| `requirements` | Pflicht (PyPI‑Pin) | Pflicht (PyPI‑Pin) | **Immer exakt** pinnen: `paket==1.2.3` |
| `dependencies` | optional | optional | Soft via `after_dependencies` (z. B. `zeroconf`) |
| `loggers` | optional | empfohlen | Liste der Logger‑Namen der Library, damit User Debug aktivieren können |
| `quality_scale` | weglassen oder eigener Wert | required ab Bronze | Custom default = `custom` |
| `zeroconf` / `dhcp` / `ssdp` / `bluetooth` / `usb` | optional | optional | Triggern Discovery (siehe §4.5) |
| `single_config_entry` | optional | optional | Wenn nur eine Instanz Sinn ergibt |

**Stolperfallen:**
- `version` muss SemVer sein und mit dem GitHub‑Release‑Tag korrespondieren.
- Bei Core‑Submission **dürfen** `version` und `issue_tracker` **nicht** drin sein (hassfest weist sie zurück).
- `iot_class` Werte: `assumed_state | cloud_polling | cloud_push | local_polling | local_push | calculated`.

Quellen:
- <https://developers.home-assistant.io/docs/creating_integration_manifest/>
- <https://github.com/home-assistant/core/blob/dev/homeassistant/loader.py>

---

## 3. `hacs.json`

Im **Repo‑Root**, nicht im Component‑Verzeichnis.

```json
{
  "name": "Heatpump XY",
  "homeassistant": "2025.1.0",
  "hacs": "2.0.0",
  "render_readme": true,
  "country": ["DE", "AT", "CH"],
  "zip_release": false
}
```

| Feld | Beschreibung |
|---|---|
| `name` | Pflicht. Anzeigename in HACS |
| `homeassistant` | Mindestversion HA Core – User unter dieser Version sehen die Integration nicht |
| `hacs` | Mindestversion HACS. **Achtung:** HACS hat seit 2.0.0 mit der 1.x‑Reihe gebrochen und benötigt selbst HA 2024.4.1+. Keine `1.34.0` mehr eintragen, sondern `2.0.0` als Minimum nutzen. |
| `render_readme` | `true` → README.md statt info.md anzeigen. Sonst muss `info.md` existieren |
| `country` | ISO‑Codes; nur relevant wenn regional. Für Wärmepumpe i. d. R. weglassen |
| `zip_release` | `true` wenn GitHub‑Release ein ZIP enthält. Standard `false` (HACS pulled aus dem Tag) |
| `filename` | nur bei `zip_release: true` |
| `hide_default_branch` | optional |

Quellen:
- <https://hacs.xyz/docs/publish/start/>
- <https://hacs.xyz/docs/publish/integration/>
- <https://github.com/hacs/integration/releases>

---

## 4. Config Flow

### 4.1 Grundgerüst

```python
# config_flow.py
from __future__ import annotations
from typing import Any
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_API_KEY
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from .api import HeatpumpClient, CannotConnect, InvalidAuth
from .const import DOMAIN, DEFAULT_PORT

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Required(CONF_API_KEY): cv.string,
})


class HeatpumpConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = HeatpumpClient(
                host=user_input[CONF_HOST],
                port=user_input[CONF_PORT],
                api_key=user_input[CONF_API_KEY],
                session=session,
            )
            try:
                info = await client.async_get_device_info()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.serial_number)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: user_input[CONF_HOST]}
                )
                return self.async_create_entry(
                    title=info.model,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
```

### 4.2 Pflicht‑Bausteine

- **`async_set_unique_id` + `_abort_if_unique_id_configured`** – verhindert Doppel‑Setup. Bei IP‑Änderung via DHCP wird `CONF_HOST` automatisch upgedatet.
- **`unique_id` als String** (Seriennummer, MAC). Ab HA 2025.10 wird non‑string als Fehler gewertet.
- **Validate before create**: erst Connection testen, dann `async_create_entry`. Kein „Setup‑Eintrag erzeugen, dann Fehler in `async_setup_entry`".

### 4.3 Options Flow vs Reconfigure Flow

- **Options Flow**: für Verhaltens‑Settings nach Setup (z. B. `scan_interval`, „Disabled by default"‑Entitäten). Wird im Config‑Entry Detail als „Configure" angezeigt.
- **Reconfigure Flow** (Gold‑Regel `reconfiguration-flow`): wenn der User die *Verbindungsdaten* ändern muss (Host, API‑Key) ohne neu hinzuzufügen.

```python
async def async_step_reconfigure(
    self, user_input: dict[str, Any] | None = None
) -> ConfigFlowResult:
    entry = self._get_reconfigure_entry()
    # validation analog zu async_step_user, dann:
    return self.async_update_reload_and_abort(
        entry, data_updates=user_input
    )
```

### 4.4 Reauth Flow (Silver `reauthentication-flow`)

Trigger: in `async_setup_entry` oder im Coordinator `raise ConfigEntryAuthFailed` werfen.

```python
async def async_step_reauth(
    self, entry_data: Mapping[str, Any]
) -> ConfigFlowResult:
    return await self.async_step_reauth_confirm()

async def async_step_reauth_confirm(
    self, user_input: dict[str, Any] | None = None
) -> ConfigFlowResult:
    entry = self._get_reauth_entry()
    # ... validation ...
    return self.async_update_reload_and_abort(
        entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
    )
```

### 4.5 Discovery (Gold `discovery`)

Wenn die Wärmepumpe im LAN per mDNS oder DHCP erkennbar ist, in `manifest.json` definieren:

```json
"zeroconf": [{ "type": "_heatpump._tcp.local." }]
```

Und im Flow:

```python
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

async def async_step_zeroconf(
    self, discovery_info: ZeroconfServiceInfo
) -> ConfigFlowResult:
    serial = discovery_info.properties.get("serial")
    if not serial:
        return self.async_abort(reason="no_serial")
    await self.async_set_unique_id(serial)
    self._abort_if_unique_id_configured(
        updates={CONF_HOST: str(discovery_info.ip_address)}
    )
    self.context["title_placeholders"] = {"name": discovery_info.name}
    self._discovery_info = discovery_info
    return await self.async_step_discovery_confirm()
```

Quellen:
- <https://developers.home-assistant.io/docs/config_entries_config_flow_handler/>
- <https://developers.home-assistant.io/docs/network_discovery/>

---

## 5. `DataUpdateCoordinator`

### 5.1 Wann Coordinator?

**Immer**, sobald mehrere Entities aus derselben API‑Antwort gespeist werden. Eigene `async_update`‑Methoden pro Entity gegen dieselbe API sind Anti‑Pattern und werden vom Quality‑Check abgelehnt.

### 5.2 Polling‑Coordinator (Standardfall)

```python
# coordinator.py
from __future__ import annotations
from datetime import timedelta
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HeatpumpClient, CannotConnect, InvalidAuth
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

@dataclass
class HeatpumpData:
    flow_temp: float
    return_temp: float
    compressor_state: str
    # ... weitere Felder als typed dataclass

type HeatpumpConfigEntry = ConfigEntry[HeatpumpCoordinator]


class HeatpumpCoordinator(DataUpdateCoordinator[HeatpumpData]):
    config_entry: HeatpumpConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: HeatpumpConfigEntry,
        client: HeatpumpClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            always_update=False,  # spart unnötige Listener-Calls
        )
        self.client = client

    async def _async_setup(self) -> None:
        """Einmalig vor erstem Refresh – HA 2024.8+."""
        self.device_info = await self.client.async_get_device_info()

    async def _async_update_data(self) -> HeatpumpData:
        try:
            return await self.client.async_get_state()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(err) from err
        except CannotConnect as err:
            raise UpdateFailed(f"Heatpump unreachable: {err}") from err
```

### 5.3 Push‑Coordinator (`local_push`)

Wenn die Wärmepumpe Webhooks/MQTT/UDP‑Push schickt: `update_interval=None`, und im API‑Client einen Callback registrieren, der `coordinator.async_set_updated_data(new_data)` aufruft. Dadurch profitierst du weiterhin von der Listener‑Logik und `available`/`last_update_success`.

### 5.4 Initial Refresh

**Immer** `await coordinator.async_config_entry_first_refresh()` in `async_setup_entry` aufrufen – das wirft korrekt `ConfigEntryNotReady` (Bronze‑Regel `test-before-setup`) und triggert HA's exponential backoff.

Quellen:
- <https://developers.home-assistant.io/docs/integration_fetching_data/>
- <https://developers.home-assistant.io/blog/2024/08/05/coordinator_async_setup/>

---

## 6. Entity‑Design

### 6.1 Basis‑Entity in `entity.py`

```python
from __future__ import annotations
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import HeatpumpCoordinator
from .const import DOMAIN, MANUFACTURER


class HeatpumpEntity(CoordinatorEntity[HeatpumpCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HeatpumpCoordinator) -> None:
        super().__init__(coordinator)
        info = coordinator.device_info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.serial_number)},
            manufacturer=MANUFACTURER,
            model=info.model,
            sw_version=info.firmware,
            configuration_url=f"http://{coordinator.client.host}/",
            serial_number=info.serial_number,
        )
```

### 6.2 `EntityDescription`‑Pattern (verbindlich)

```python
# sensor.py
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HeatpumpData, HeatpumpConfigEntry
from .entity import HeatpumpEntity


@dataclass(frozen=True, kw_only=True)
class HeatpumpSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[HeatpumpData], float | int | str | None]


SENSORS: tuple[HeatpumpSensorEntityDescription, ...] = (
    HeatpumpSensorEntityDescription(
        key="flow_temp",
        translation_key="flow_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda d: d.flow_temp,
    ),
    HeatpumpSensorEntityDescription(
        key="electric_power",
        translation_key="electric_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.electric_power,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatpumpConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(HeatpumpSensor(coordinator, desc) for desc in SENSORS)


class HeatpumpSensor(HeatpumpEntity, SensorEntity):
    entity_description: HeatpumpSensorEntityDescription

    def __init__(
        self,
        coordinator: HeatpumpCoordinator,
        description: HeatpumpSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.device_info.serial_number}_{description.key}"
        )

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self.coordinator.data)
```

### 6.3 Pflicht‑Attribute pro Entity

| Attribut | Wofür | Quality‑Scale |
|---|---|---|
| `_attr_unique_id` | stabile ID, idealerweise `<serial>_<key>` | Bronze `entity-unique-id` |
| `_attr_has_entity_name = True` | Friendly Name = "<Device> <translated key>" | Bronze `has-entity-name` |
| `translation_key` | Übersetzung in `strings.json` → entity → <platform> → <key>.name | Gold `entity-translations` |
| `device_class` | wo immer möglich (Temperatur, Power, Energy, …) | Gold `entity-device-class` |
| `state_class` | `MEASUREMENT` / `TOTAL` / `TOTAL_INCREASING` | Gold |
| `entity_category` | `CONFIG` / `DIAGNOSTIC` für Nicht‑Hauptmesswerte | Gold `entity-category` |
| `_attr_entity_registry_enabled_default = False` | für selten genutzte / verbose Entities | Gold `entity-disabled-by-default` |
| `available`‑Property | aus Coordinator: `super().available and self.coordinator.last_update_success` | Silver `entity-unavailable` |

### 6.4 `available` korrekt herleiten

```python
@property
def available(self) -> bool:
    return super().available and self.entity_description.value_fn(
        self.coordinator.data
    ) is not None
```

Quelle: <https://developers.home-assistant.io/docs/core/entity/>

---

## 7. Async/Await Patterns

- **Niemals blockierendes I/O im Event‑Loop.** `requests`, `urllib`, `socket.recv` ohne async, `time.sleep` → tabu.
- **Synchrone Bibliothek** → in Executor: `await hass.async_add_executor_job(blocking_call, arg1)`. Für Platinum `async-dependency` muss die Library aber ausschließlich async sein.
- **HTTP‑Session**:
  ```python
  from homeassistant.helpers.aiohttp_client import async_get_clientsession
  session = async_get_clientsession(hass)  # geteilt, auto-cleanup
  ```
  Niemals `aiohttp.ClientSession()` selbst instanziieren in Integrationscode. Quality‑Scale Platinum‑Regel `inject-websession`: Die externe Library muss eine Session als Parameter akzeptieren.
- **Timeouts**: `async with asyncio.timeout(10):` (Python 3.11+ Stil) statt `async_timeout`.
- **Context Manager** korrekt benutzen:
  ```python
  async with session.get(url, timeout=ClientTimeout(total=10)) as resp:
      resp.raise_for_status()
      return await resp.json()
  ```
- **Kein `asyncio.create_task` ohne Tracking.** Falls nötig: `entry.async_create_background_task(hass, coro, name="heatpump_listener")`.

---

## 8. API‑Client

### 8.1 Trennung von HA

Die API‑Klasse darf **keine** HA‑Imports enthalten. Sie ist potenziell ein eigenes PyPI‑Package (`pyheatpumpxy`) – das ist die Voraussetzung für `dependency-transparency` und Voraussetzung für Core‑Merge bei nicht‑trivialen Integrationen.

### 8.2 Beispiel‑Client

```python
# api.py (oder externes Package pyheatpumpxy)
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Self
import aiohttp


class HeatpumpError(Exception):
    """Basisklasse."""


class CannotConnect(HeatpumpError):
    """Netzwerk-/HTTP-Fehler."""


class InvalidAuth(HeatpumpError):
    """401/403."""


@dataclass(slots=True)
class DeviceInfo:
    serial_number: str
    model: str
    firmware: str


@dataclass(slots=True)
class State:
    flow_temp: float
    return_temp: float
    electric_power: float
    compressor_state: str


class HeatpumpClient:
    def __init__(
        self,
        host: str,
        port: int,
        api_key: str,
        session: aiohttp.ClientSession,
        *,
        request_timeout: float = 10.0,
    ) -> None:
        self._base = f"http://{host}:{port}"
        self._headers = {"X-API-Key": api_key}
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

    async def _request(self, path: str) -> dict:
        try:
            async with self._session.get(
                f"{self._base}{path}",
                headers=self._headers,
                timeout=self._timeout,
            ) as resp:
                if resp.status in (401, 403):
                    raise InvalidAuth(f"HTTP {resp.status}")
                if resp.status >= 500:
                    raise CannotConnect(f"HTTP {resp.status}")
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CannotConnect(str(err)) from err

    async def async_get_device_info(self) -> DeviceInfo:
        raw = await self._request("/api/info")
        return DeviceInfo(**raw)

    async def async_get_state(self) -> State:
        raw = await self._request("/api/state")
        return State(**raw)
```

### 8.3 Retry/Backoff

`DataUpdateCoordinator` macht *Polling* selbst – kein Retry‑Loop dort. Aber bei *einzelnen* Befehlen (z. B. Setpoint setzen): `tenacity` oder ein einfacher 3‑facher Retry mit exponential backoff bei `CannotConnect` ist akzeptabel.

---

## 9. Type Hints und Modernes Python

- **Python 3.13** wurde mit HA Core 2024.12 für HA OS / Container ausgeliefert (automatisches Upgrade laut Release‑Blog) und ist seit HA 2025.2 die Pflicht‑Mindestversion für eigene Core‑Installationen. Du darfst `match`, `Self`, `type X = ...` Aliasse, `Generic[T]` mit `class C[T]:`‑Syntax verwenden.
- **`from __future__ import annotations`** in jeder Datei oben.
- Für Datenstrukturen: `dataclass` (mit `slots=True, kw_only=True`), für API‑Responses optional `pydantic` v2 oder `mashumaro`. Pure dict ist Anti‑Pattern.
- **`py.typed`** Marker im Custom‑Component‑Verzeichnis ist nicht erforderlich (es ist kein Package), aber im **externen API‑Package** Pflicht (Platinum `strict-typing`).
- Strict typing aktivieren:
  ```toml
  # pyproject.toml
  [tool.mypy]
  strict = true
  python_version = "3.13"
  ```

---

## 10. Translations

### 10.1 `strings.json` (Quelldatei – Englisch)

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect to Heatpump",
        "data": {
          "host": "Host or IP",
          "port": "Port",
          "api_key": "API key"
        },
        "data_description": {
          "host": "Hostname or IP address of the heatpump in the local network.",
          "api_key": "Stored under Service > API in the heatpump web interface."
        }
      },
      "reauth_confirm": {
        "title": "Re-authenticate Heatpump",
        "data": { "api_key": "API key" }
      },
      "reconfigure": {
        "title": "Reconfigure Heatpump",
        "data": { "host": "Host or IP", "port": "Port", "api_key": "API key" }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect.",
      "invalid_auth": "Invalid API key.",
      "unknown": "Unexpected error."
    },
    "abort": {
      "already_configured": "Device is already configured",
      "reauth_successful": "Re-authentication was successful",
      "reconfigure_successful": "Re-configuration was successful"
    }
  },
  "entity": {
    "sensor": {
      "flow_temperature": { "name": "Flow temperature" },
      "electric_power":   { "name": "Electric power" }
    }
  },
  "exceptions": {
    "set_temperature_failed": {
      "message": "Failed to set temperature: {reason}"
    }
  }
}
```

### 10.2 Übersetzungen

`translations/en.json` ist eine 1:1 Kopie von `strings.json` (das ist HA‑Konvention; im Core wird sie automatisch generiert via Lokalise, im Custom‑Component musst du sie selbst bereitstellen).

`translations/de.json` analog mit deutschen Strings.

### 10.3 Icon‑Translations (Gold `icon-translations`)

```json
// icons.json
{
  "entity": {
    "sensor": {
      "flow_temperature": { "default": "mdi:thermometer-water" },
      "compressor_state": {
        "default": "mdi:engine",
        "state": { "off": "mdi:engine-off", "on": "mdi:engine" }
      }
    }
  }
}
```

Hassfest validiert hier, dass nur `mdi:`‑Präfixe vorkommen.

Quelle: <https://developers.home-assistant.io/docs/internationalization/>

---

## 11. Services / Actions

### 11.1 `services.yaml`

```yaml
set_setpoint:
  target:
    entity:
      domain: climate
      integration: heatpump_xy
  fields:
    temperature:
      required: true
      example: 21.5
      selector:
        number:
          min: 5
          max: 60
          step: 0.5
          unit_of_measurement: "°C"
```

### 11.2 Registrierung

Services in **`async_setup`**, nicht in `async_setup_entry`. Damit existieren sie auch ohne geladenen Entry und Automations können sie referenzieren.

```python
# __init__.py
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _async_set_setpoint(call: ServiceCall) -> ServiceResponse:
        entry_id = call.data.get("config_entry_id")
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("config_entry_not_loaded")
        coordinator: HeatpumpCoordinator = entry.runtime_data
        try:
            await coordinator.client.async_set_setpoint(call.data["temperature"])
        except CannotConnect as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_temperature_failed",
                translation_placeholders={"reason": str(err)},
            ) from err
        await coordinator.async_request_refresh()
        return {"applied": call.data["temperature"]}

    hass.services.async_register(
        DOMAIN, "set_setpoint", _async_set_setpoint,
        schema=vol.Schema({...}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True
```

Quelle: <https://developers.home-assistant.io/docs/dev_101_services/>

---

## 12. Diagnostics

```python
# diagnostics.py
from __future__ import annotations
from typing import Any
from dataclasses import asdict
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import HeatpumpConfigEntry

TO_REDACT = {CONF_API_KEY, "serial_number", "mac"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HeatpumpConfigEntry,
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
        "device_info": async_redact_data(
            asdict(coordinator.device_info), TO_REDACT
        ),
    }
```

Pflicht ab **Gold** (`diagnostics`). Sensible Felder *immer* redacten – Diagnostics werden im Klartext in GitHub‑Issues gepostet.

Quelle: <https://developers.home-assistant.io/docs/core/integration/diagnostics/>

---

## 13. Repairs

```python
from homeassistant.helpers import issue_registry as ir

ir.async_create_issue(
    hass,
    DOMAIN,
    "firmware_outdated",
    is_fixable=False,
    is_persistent=True,
    severity=ir.IssueSeverity.WARNING,
    translation_key="firmware_outdated",
    translation_placeholders={"current": fw, "minimum": "2.5.0"},
    learn_more_url="https://github.com/christian/ha-heatpump-xy/wiki/firmware",
)
```

- `severity`: `CRITICAL | ERROR | WARNING`
- `is_fixable=True` + `repairs.py` mit `RepairsFlow` für interaktive Lösung
- `is_persistent=True` → bleibt nach HA‑Restart sichtbar

Quelle: <https://developers.home-assistant.io/docs/core/platform/repairs/>

---

## 14. Logging

```python
# Modul-weit
_LOGGER = logging.getLogger(__name__)

# Verwendung
_LOGGER.debug("Heatpump state: %s", state)        # ja, lazy formatting
_LOGGER.warning("Retrying after %.1fs", delay)
_LOGGER.error("Setpoint failed: %s", err)
# nie: _LOGGER.info(f"Heatpump {host} polled")    # nein, kein f-string in log
# nie: print(...)
```

Regeln (Silver `log-when-unavailable`):
- **Kein Spam.** Bei Verbindungsverlust: einmal `warning` beim ersten Fehlschlag, einmal `info` bei Recovery. `DataUpdateCoordinator` macht das automatisch, eigene Logs nur wenn nötig.
- **Kein `info` bei normalem Betrieb.** `debug` für Telemetrie, `info` nur für Lifecycle (Setup, Unload).
- **Logger‑Namen** in `manifest.json` `loggers` eintragen.

---

## 15. Tests

### 15.1 Setup

```toml
# pyproject.toml
[project.optional-dependencies]
test = [
  "pytest>=8",
  "pytest-asyncio",
  "pytest-cov",
  "pytest-homeassistant-custom-component",
  "syrupy",
  "aioresponses",
]
```

### 15.2 `tests/conftest.py`

```python
from __future__ import annotations
import pytest
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    return snapshot.use_extension(HomeAssistantSnapshotExtension)
```

### 15.3 Config‑Flow‑Test

```python
from unittest.mock import AsyncMock, patch
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from custom_components.heatpump_xy.const import DOMAIN


async def test_user_flow_happy_path(hass):
    with patch(
        "custom_components.heatpump_xy.config_flow.HeatpumpClient.async_get_device_info",
        new=AsyncMock(return_value=DeviceInfo("ABC123", "XY-9000", "1.0.0")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "10.0.0.5", "port": 80, "api_key": "secret"},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["host"] == "10.0.0.5"
```

### 15.4 Snapshot‑Tests für Sensoren

```python
async def test_sensors(hass, snapshot, init_integration):
    state = hass.states.get("sensor.heatpump_xy_flow_temperature")
    assert state == snapshot
```

Erstellung der Snapshots: `pytest --snapshot-update`.

### 15.5 Coverage

- Bronze fordert `config-flow-test-coverage` = **100 %** für `config_flow.py`.
- Silver fordert `test-coverage` ≥ **95 %** insgesamt.

```bash
pytest tests/ \
  --cov=custom_components.heatpump_xy \
  --cov-report=term-missing \
  --cov-fail-under=95
```

Quellen:
- <https://developers.home-assistant.io/docs/development_testing/>
- <https://github.com/MatthewFlamm/pytest-homeassistant-custom-component>

---

## 16. Quality Scale

### 16.1 Tiers (Stand: offizielle Checklist Nov 2024, validiert für HA 2026.x)

Es gibt **4 skalierte Tiers** (Bronze → Silver → Gold → Platinum). Jeder höhere Tier inkludiert alle Regeln der niedrigeren Tiers. Daneben **4 Spezial‑Tiers**: `no_score`, `internal`, `legacy`, `custom`.

Quelle der vollständigen Liste: <https://developers.home-assistant.io/docs/core/integration-quality-scale/checklist/> (kanonisch, Stand 20. Nov 2024).

### 16.2 Vollständige Regelliste (52 Regeln: 18 + 10 + 21 + 3)

#### 🥉 Bronze (18) – Pflicht für jede neue Integration

| Slug | Bedeutung |
|---|---|
| `action-setup` | Services in `async_setup` registrieren, nicht `async_setup_entry`. |
| `appropriate-polling` | Sinnvolles Default‑Polling‑Intervall (nicht zu schnell, nicht zu langsam). |
| `brands` | Logo/Icon im `home-assistant/brands` Repo (Core) bzw. `brand/` lokal (Custom ab 2026.3). |
| `common-modules` | Coordinator in `coordinator.py`, Basis‑Entity in `entity.py`. |
| `config-flow` | UI‑Setup, mit `data_description` für Kontext, `data` vs `options` korrekt getrennt. |
| `config-flow-test-coverage` | 100 % Coverage im Config Flow. |
| `dependency-transparency` | Externe Lib auf PyPI, Open Source, Build aus inspizierbarem Source. |
| `docs-actions` | Doku beschreibt jede Service Action. |
| `docs-high-level-description` | Doku beschreibt das Produkt/den Service. |
| `docs-installation-instructions` | Schritt‑für‑Schritt Setup‑Anleitung. |
| `docs-removal-instructions` | Wie sauber deinstallieren. |
| `entity-event-setup` | Subscriptions in `async_added_to_hass` / Cleanup in `async_will_remove_from_hass`. |
| `entity-unique-id` | Stabile `unique_id` pro Entity. |
| `has-entity-name` | `_attr_has_entity_name = True`. |
| `runtime-data` | `ConfigEntry.runtime_data` statt `hass.data[DOMAIN][...]`. |
| `test-before-configure` | Verbindung wird vor `async_create_entry` getestet. |
| `test-before-setup` | `ConfigEntryNotReady` / `ConfigEntryAuthFailed` in Setup. |
| `unique-config-entry` | Doppel‑Setup verhindert. |

#### 🥈 Silver (10) – Stabilität zur Laufzeit

| Slug | Bedeutung |
|---|---|
| `action-exceptions` | `ServiceValidationError` / `HomeAssistantError` in Services. |
| `config-entry-unloading` | `async_unload_entry` sauber implementiert. |
| `docs-configuration-parameters` | Doku beschreibt alle Options‑Parameter. |
| `docs-installation-parameters` | Doku beschreibt alle Setup‑Felder. |
| `entity-unavailable` | Entity wird `unavailable` bei API‑Verlust. |
| `integration-owner` | ≥ 1 aktiver Codeowner. |
| `log-when-unavailable` | Einmal Fehler, einmal Recovery, kein Spam. |
| `parallel-updates` | `PARALLEL_UPDATES` explizit in jeder Plattformdatei. |
| `reauthentication-flow` | Reauth Flow implementiert. |
| `test-coverage` | ≥ 95 % Test Coverage. |

#### 🥇 Gold (21) – beste UX

| Slug | Bedeutung |
|---|---|
| `devices` | Korrekter Eintrag im Device Registry (Manufacturer, Model, sw_version, identifiers). |
| `diagnostics` | Diagnostics‑Plattform mit Redaction. |
| `discovery` | Auto‑Discovery via Zeroconf/SSDP/DHCP/Bluetooth/USB wenn möglich. |
| `discovery-update-info` | IP‑Update via Discovery (DHCP) wird übernommen. |
| `docs-data-update` | Doku beschreibt Push vs Poll, Intervalle. |
| `docs-examples` | Automation‑Beispiele in der Doku. |
| `docs-known-limitations` | Bekannte Limitationen dokumentiert. |
| `docs-supported-devices` | Liste unterstützter Modelle. |
| `docs-supported-functions` | Liste der bereitgestellten Plattformen/Entities. |
| `docs-troubleshooting` | Troubleshooting‑Sektion. |
| `docs-use-cases` | Use‑Case‑Beschreibungen. |
| `dynamic-devices` | Geräte, die nach Setup hinzukommen, werden automatisch erkannt. |
| `entity-category` | `EntityCategory.CONFIG` / `DIAGNOSTIC` korrekt gesetzt. |
| `entity-device-class` | `device_class` wo immer möglich. |
| `entity-disabled-by-default` | Selten genutzte Entities default disabled. |
| `entity-translations` | Entity‑Namen via `translation_key`. |
| `exception-translations` | Exception‑Messages mit `translation_domain`/`translation_key`. |
| `icon-translations` | `icons.json` statt hardcoded `mdi:`. |
| `reconfiguration-flow` | `async_step_reconfigure` implementiert. |
| `repair-issues` | `ir.async_create_issue` statt stiller Logfehler. |
| `stale-devices` | Entfernte Geräte werden auch in HA entfernt. |

#### 🏆 Platinum (3) – technische Exzellenz

| Slug | Bedeutung |
|---|---|
| `async-dependency` | Library ist vollständig async (kein Executor‑Wrapping). |
| `inject-websession` | Lib akzeptiert externe `aiohttp.ClientSession`. |
| `strict-typing` | `mypy --strict` clean. |

### 16.3 `quality_scale.yaml`

```yaml
rules:
  # Bronze
  action-setup: done
  appropriate-polling: done
  brands: done
  common-modules: done
  config-flow: done
  config-flow-test-coverage: done
  dependency-transparency: done
  docs-actions:
    status: exempt
    comment: Integration registers no custom actions.
  docs-high-level-description: done
  docs-installation-instructions: done
  docs-removal-instructions: done
  entity-event-setup: done
  entity-unique-id: done
  has-entity-name: done
  runtime-data: done
  test-before-configure: done
  test-before-setup: done
  unique-config-entry: done
  # Silver
  action-exceptions: todo
  config-entry-unloading: done
  # ...
```

Hassfest validiert: jeder im Manifest deklarierte Tier zwingt zu vollständigem `done`/`exempt` aller Regeln dieses Tiers und darunter. Exemptions **brauchen** einen `comment`.

### 16.4 Manifest‑Eintrag

```json
"quality_scale": "bronze"
```

Erst auf `silver`/`gold`/`platinum` upgraden, **wenn alle Regeln tatsächlich erfüllt** und ein PR den Upgrade dokumentiert.

Quellen:
- <https://developers.home-assistant.io/docs/core/integration-quality-scale/>
- <https://developers.home-assistant.io/docs/core/integration-quality-scale/checklist/>
- <https://github.com/home-assistant/architecture/blob/master/adr/0022-integration-quality-scale.md>
- <https://developers.home-assistant.io/blog/2024/11/20/integration-quality-scale/>

---

## 17. HACS‑Spezifika

### 17.1 Pflicht‑Dateien (Repository‑Root)

- `README.md` – ist sichtbar in HACS, wenn `render_readme: true`
- `hacs.json` – siehe §3
- `LICENSE` – HACS rejected ohne
- `custom_components/<domain>/manifest.json` mit `version` und `documentation`
- GitHub‑**Releases** (Tags allein reichen *nicht*) mit SemVer (`v0.1.0`)

### 17.2 GitHub Actions

```yaml
# .github/workflows/hassfest.yaml
name: Validate
on: [push, pull_request]
jobs:
  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master
  hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hacs/action@main
        with:
          category: integration
```

### 17.3 Brands / Logo

Drei Wege, je nach Reife:

1. **Custom (HACS), HA ≥ 2026.3**: lokales `custom_components/heatpump_xy/brand/` mit `icon.png` (256×256), `icon@2x.png` (512×512), `logo.png`, `logo@2x.png`. Wird über HA's Brands‑Proxy ausgeliefert.
2. **Custom (HACS), HA < 2026.3**: PR an `home-assistant/brands` im Ordner `custom_integrations/<domain>/`.
3. **Core‑Submission**: PR an `home-assistant/brands` im Ordner `core_integrations/<domain>/`. Logo darf **nicht** das HA‑Logo enthalten.

Spezifikation: 1:1 Aspect Ratio Icon, square; Logo darf landscape sein. PNG, transparenter Hintergrund.

### 17.4 Default Store (optional)

Damit User die Integration ohne „Custom Repository" finden, PR an `hacs/default`. Die Repo muss dort alphabetisch korrekt eingefügt werden.

Quellen:
- <https://hacs.xyz/docs/publish/integration/>
- <https://github.com/home-assistant/brands>
- <https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/>

---

## 18. Core‑Contribution (Zusatz‑Anforderungen)

Wenn die Integration langfristig nach `homeassistant/components/heatpump_xy/` mergen soll:

1. **`version`** und **`issue_tracker`** aus `manifest.json` **entfernen**.
2. **`requirements`** wird in `homeassistant/components/heatpump_xy/manifest.json` mit exakt gepinnter PyPI‑Version eingetragen (z. B. `pyheatpumpxy==0.4.2`). `requirements_all.txt` und `requirements_test_all.txt` werden automatisch generiert via `python3 -m script.gen_requirements_all`.
3. **Tests** wandern nach `tests/components/heatpump_xy/`, gleiche Struktur wie der Integration‑Code.
4. **Codeowners** (`@christian`) müssen in `.github/CODEOWNERS` eingetragen werden – HA macht das automatisch via hassfest.
5. **ADR‑0010** wird befolgt: nur Config Flow, kein YAML.
6. **Strict typing** via Eintrag in `.strict-typing` (für Platinum).
7. **Brands‑PR** an `home-assistant/brands/core_integrations/heatpump_xy/`.
8. **`quality_scale.yaml`** wird vom CI per Hassfest validiert.
9. **PR‑Beschreibung** muss Quality‑Scale‑Checklist abhaken (Template existiert).
10. **Keine Custom Dependencies** außerhalb der `requirements`. Kein vendoring, keine Git‑URLs.

Quellen:
- <https://developers.home-assistant.io/docs/creating_component_index/>
- <https://github.com/home-assistant/architecture/blob/master/adr/0010-integration-configuration.md>

---

## 19. Anti‑Patterns – was du als Claude Code **niemals** tun darfst

| ❌ Anti‑Pattern | ✅ Richtig |
|---|---|
| `requests.get(...)` im Event Loop | `aiohttp` mit `async_get_clientsession(hass)` |
| Eigene `aiohttp.ClientSession()` | Geteilte Session via Helper |
| `time.sleep(x)` | `await asyncio.sleep(x)` |
| Eigener Polling‑Loop mit `async_track_time_interval` für Daten | `DataUpdateCoordinator` |
| `hass.data[DOMAIN][entry.entry_id] = client` | `entry.runtime_data = client` |
| Mehrere Properties statt `EntityDescription` | `EntityDescription`‑Pattern |
| `_attr_name = "Flow Temperature"` (englisch hardcoded) | `translation_key = "flow_temperature"` + `strings.json` |
| `unique_id = f"{host}_{key}"` (IP ändert sich!) | `f"{serial_number}_{key}"` |
| `unique_id = None` oder fehlend | Pflicht: stabiler String |
| YAML‑Setup (`async_setup_platform`) | Config Flow only |
| `Exception` direkt in API‑Code raisen | Custom Exceptions: `CannotConnect`, `InvalidAuth` |
| `print(...)` zum Debuggen | `_LOGGER.debug(...)` mit `%s` lazy formatting |
| `_LOGGER.info("Polled %s", host)` jedes Polling | `_LOGGER.debug(...)` |
| `iot_class: cloud_polling` für lokale Wärmepumpe | `local_polling` |
| `integration_type: hub` für ein einzelnes Gerät | `device` |
| Service in `async_setup_entry` registrieren | In `async_setup` |
| API‑Code mit HA‑Imports vermischt | Reine Library, dependency injected |
| `update_before_add=True` mit Coordinator | Nicht nötig, Coordinator hat bereits Daten |
| Mutable State in Entity ohne Coordinator | State immer aus `coordinator.data` ziehen |
| Eigenes `async_update` pro Entity | `_handle_coordinator_update` (kommt von `CoordinatorEntity`) |
| Synchrone Library aufrufen ohne Executor | `await hass.async_add_executor_job(fn, arg)` |
| Diagnostics ohne Redaction von API‑Keys | `async_redact_data(..., TO_REDACT)` |

---

## 20. Dokumentations‑Pointer (für Fetch durch Claude Code)

| Thema | URL |
|---|---|
| Integration File Structure | <https://developers.home-assistant.io/docs/creating_integration_file_structure/> |
| Manifest | <https://developers.home-assistant.io/docs/creating_integration_manifest/> |
| Config Flow | <https://developers.home-assistant.io/docs/config_entries_config_flow_handler/> |
| Options Flow | <https://developers.home-assistant.io/docs/config_entries_options_flow_handler/> |
| Network Discovery | <https://developers.home-assistant.io/docs/network_discovery/> |
| Fetching Data / Coordinator | <https://developers.home-assistant.io/docs/integration_fetching_data/> |
| Coordinator `_async_setup` | <https://developers.home-assistant.io/blog/2024/08/05/coordinator_async_setup/> |
| `runtime_data` | <https://developers.home-assistant.io/blog/2024/04/30/store-runtime-data-inside-config-entry/> |
| Entity | <https://developers.home-assistant.io/docs/core/entity/> |
| Sensor | <https://developers.home-assistant.io/docs/core/entity/sensor/> |
| Climate | <https://developers.home-assistant.io/docs/core/entity/climate/> |
| Device Registry | <https://developers.home-assistant.io/docs/device_registry_index/> |
| Internationalization | <https://developers.home-assistant.io/docs/internationalization/> |
| Service Actions | <https://developers.home-assistant.io/docs/dev_101_services/> |
| Diagnostics | <https://developers.home-assistant.io/docs/core/integration/diagnostics/> |
| Repairs | <https://developers.home-assistant.io/docs/core/platform/repairs/> |
| Testing | <https://developers.home-assistant.io/docs/development_testing/> |
| Quality Scale Overview | <https://developers.home-assistant.io/docs/core/integration-quality-scale/> |
| Quality Scale Checklist | <https://developers.home-assistant.io/docs/core/integration-quality-scale/checklist/> |
| Quality Scale Rules Index | <https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/> |
| ADR‑0010 (kein YAML) | <https://github.com/home-assistant/architecture/blob/master/adr/0010-integration-configuration.md> |
| ADR‑0022 (Quality Scale) | <https://github.com/home-assistant/architecture/blob/master/adr/0022-integration-quality-scale.md> |
| Hassfest GitHub Action | <https://developers.home-assistant.io/blog/2020/04/16/hassfest/> |
| HACS Integration Publish | <https://hacs.xyz/docs/publish/integration/> |
| HACS hacs.json Spec | <https://hacs.xyz/docs/publish/start/> |
| Brands Repo | <https://github.com/home-assistant/brands> |
| Brands Proxy API (lokale Brands) | <https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/> |
| `pytest-homeassistant-custom-component` | <https://github.com/MatthewFlamm/pytest-homeassistant-custom-component> |
| Integration Blueprint | <https://github.com/home-assistant/integration_blueprint> |

---

## 21. Vorgehens‑Checkliste für die Wärmepumpen‑Integration

1. **Repo aus `integration_blueprint` ableiten**, Domain umbenennen auf `heatpump_xy`.
2. **API‑Wrapper** (`api.py` oder eigenes PyPI‑Package) implementieren mit `aiohttp` + Custom Exceptions + Dataclasses.
3. **`manifest.json`** mit `iot_class: local_polling`, `integration_type: device`, `quality_scale: bronze`.
4. **Config Flow** mit User Step + Validation + Unique ID = Seriennummer; falls Zeroconf/DHCP Discovery möglich, ergänzen.
5. **`DataUpdateCoordinator`** in `coordinator.py` mit `_async_setup` und `_async_update_data`.
6. **`entity.py`** mit `HeatpumpEntity(CoordinatorEntity)` Basis.
7. **Plattformen** (`sensor.py`, `climate.py`, ggf. `number.py`/`select.py`/`switch.py`) via `EntityDescription`‑Pattern. **Keine** Wärmepumpen‑Domänenlogik (z. B. SG‑Ready) – das gehört in Helper‑Entities, die der User selbst orchestriert, oder in spätere Erweiterungen.
8. **`strings.json` + `translations/en.json` + `translations/de.json`** mit allen Config‑/Entity‑/Exception‑Strings.
9. **`icons.json`** für sinnvolle Default‑Icons.
10. **`diagnostics.py`** mit Redaction.
11. **Reauth Flow** (Silver) und **Reconfigure Flow** (Gold), wenn Bandbreite vorhanden.
12. **Tests**: `test_config_flow.py` (100 %), `test_coordinator.py`, `test_init.py`, `test_sensor.py` mit Snapshots.
13. **Hassfest + HACS Action** in `.github/workflows/`.
14. **`quality_scale.yaml`** mit Status pro Regel (Bronze vollständig `done`).
15. **Brands** lokal (HA ≥ 2026.3) oder via PR an `home-assistant/brands/custom_integrations/heatpump_xy/`.
16. **GitHub Release** v0.1.0 erzeugen → HACS kann installieren.
17. **Optional**: PR an `hacs/default` für Default‑Store‑Listing.
18. **Langfristig**: PR an `home-assistant/core` mit allen Adaptionen aus §18.

---

## 22. Bekannte Unsicherheiten / „neuere Änderungen, prüfen"

- **Lokale Brand‑Images** sind erst ab HA 2026.3 möglich; vorher PR an `brands` Repo.
- **`quality_scale.yaml`** Format kann sich punktuell ändern – im Zweifel an einer aktuellen Bronze‑Integration im Core ausrichten (z. B. `homeassistant/components/peblar/`).
- **Python 3.13** kam mit HA 2024.12 in HA OS / Container (laut offiziellem Release‑Blog automatisch ausgerollt) und ist seit HA 2025.2 verbindliche Mindestversion für eigenständige Core‑Installationen. Ältere `from __future__` Tricks sind nicht mehr nötig, schaden aber nicht.
- **`update_before_add`** in `async_add_entities` ist mit Coordinator‑Pattern obsolet – nicht mehr setzen.
- **HACS 2.x** ist die aktuelle Major‑Linie und benötigt selbst HA Core 2024.4.1+. Das `hacs`‑Feld in `hacs.json` sollte mindestens `2.0.0` sein, nicht mehr die alte 1.34.x. `hacs/action@main` immer auf `main` pinnen lässt CI gegen aktuelle Regeln laufen.
- **Quality Scale Rules** können sich ändern (laut ADR‑0022 explizit erwartet); bei jedem Major‑Release prüfen. Als Ankerpunkt gilt aktuell die Checklist‑Datei vom 20. Nov 2024 mit 18+10+21+3 Regeln.

> Wenn du, Claude Code, an einer Stelle unsicher bist (z. B. exakte aktuelle Pflichtfelder im Manifest, neue Coordinator‑Methoden, Änderung an HACS‑Validation), **fetch die entsprechende Doku‑URL aus §20** statt zu raten oder veraltetes Wissen zu reproduzieren. Better safe than reproducible bug.