"""
Sensor management module for Raspberry Pi robot.

Provides dynamic sensor registration, real-time readings, history tracking,
and warning detection. Emits events via SocketIO for live dashboard updates.
"""

import logging
import json
import os
from datetime import datetime
from collections import deque

# Module-level logger
logger = logging.getLogger(__name__)

# Module-level SocketIO reference — set by the application at startup
_socketio = None


def init_socketio(socketio_instance):
    """Bind a SocketIO instance so this module can emit events."""
    global _socketio
    _socketio = socketio_instance
    logger.info("Sensor module: SocketIO instance bound")


# ---------------------------------------------------------------------------
# Sensor data class
# ---------------------------------------------------------------------------

class Sensor:
    """Represents a single sensor with metadata, current reading, and history."""

    def __init__(self, code, name, unit, icon, min_val=0.0, max_val=100.0,
                 warn_high=None, warn_low=None, color="#ffffff"):
        """
        Parameters
        ----------
        code : str
            Single-letter code identifying the sensor (e.g. 'T', 'H', 'G', 'D').
        name : str
            Human-readable name (e.g. "Temperature").
        unit : str
            Measurement unit (e.g. "°C", "%", "ppm", "cm").
        icon : str
            Icon identifier or emoji for display.
        min_val : float
            Minimum expected value.
        max_val : float
            Maximum expected value.
        warn_high : float or None
            Threshold above which a high-warning is triggered.
        warn_low : float or None
            Threshold below which a low-warning is triggered.
        color : str
            Hex color string for chart / UI display.
        """
        self.code = code.upper()
        self.name = name
        self.unit = unit
        self.icon = icon
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.warn_high = float(warn_high) if warn_high is not None else None
        self.warn_low = float(warn_low) if warn_low is not None else None
        self.color = color

        self.value = None
        self.timestamp = None
        self.history = deque(maxlen=100)
        self.warning = None  # None | "high" | "low"

        logger.debug("Sensor created: %s [%s] (%s — %s %s)",
                     self.code, self.name, self.unit, self.min_val, self.max_val)

    # -- serialization helpers ------------------------------------------------

    def to_dict(self):
        """Return a plain dict summarising the sensor's current state."""
        return {
            "code": self.code,
            "name": self.name,
            "unit": self.unit,
            "icon": self.icon,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "warn_high": self.warn_high,
            "warn_low": self.warn_low,
            "color": self.color,
            "value": self.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "warning": self.warning,
        }

    def to_config_dict(self):
        """Return a dict suitable for saving to a configuration file."""
        cfg = {
            "code": self.code,
            "name": self.name,
            "unit": self.unit,
            "icon": self.icon,
            "min": self.min_val,
            "max": self.max_val,
            "warn_high": self.warn_high,
            "warn_low": self.warn_low,
            "color": self.color,
        }
        return cfg

    @classmethod
    def from_config_dict(cls, d):
        """Create a Sensor instance from a configuration dict."""
        return cls(
            code=d["code"],
            name=d["name"],
            unit=d["unit"],
            icon=d["icon"],
            min_val=d.get("min", 0.0),
            max_val=d.get("max", 100.0),
            warn_high=d.get("warn_high"),
            warn_low=d.get("warn_low"),
            color=d.get("color", "#ffffff"),
        )


# ---------------------------------------------------------------------------
# SensorManager
# ---------------------------------------------------------------------------

class SensorManager:
    """Registry and orchestrator for all sensors on the robot."""

    DEFAULT_CONFIG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "config", "sensors.json"
    )

    def __init__(self, config_path=None):
        self.sensors: dict[str, Sensor] = {}
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        logger.info("SensorManager initialised (config_path=%s)", self.config_path)

    # -- registration ---------------------------------------------------------

    def register_sensor(self, sensor: Sensor):
        """Register a Sensor object. Replaces any existing sensor with the same code."""
        if not isinstance(sensor, Sensor):
            raise TypeError("Expected a Sensor instance")
        code = sensor.code
        self.sensors[code] = sensor
        logger.info("Registered sensor %s [%s]", code, sensor.name)
        self._emit_sensor_data(sensor)

    def register_sensor_from_params(self, code, name, unit, icon, **kwargs):
        """Convenience: register a sensor by keyword parameters."""
        sensor = Sensor(code=code, name=name, unit=unit, icon=icon, **kwargs)
        self.register_sensor(sensor)
        return sensor

    def remove_sensor(self, code: str):
        """Remove a sensor by its code letter. Returns True if removed."""
        code = code.upper()
        if code in self.sensors:
            removed = self.sensors.pop(code)
            logger.info("Removed sensor %s [%s]", code, removed.name)
            return True
        logger.warning("Attempted to remove unknown sensor code '%s'", code)
        return False

    # -- readings & warnings --------------------------------------------------

    def update(self, readings: dict):
        """
        Accept a dict of {code: value} pairs, update each sensor, record history,
        check thresholds, and emit WebSocket events.

        Parameters
        ----------
        readings : dict
            Mapping of sensor code letters to numeric values, e.g.
            {"T": 24.5, "H": 62.0, "G": 350, "D": 18.3}
        """
        now = datetime.now()
        emitted_codes = []

        for code, value in readings.items():
            code = code.upper()
            if code not in self.sensors:
                logger.warning("Update received for unregistered sensor '%s' — skipping", code)
                continue

            sensor = self.sensors[code]

            # Validate range
            try:
                value = float(value)
            except (TypeError, ValueError):
                logger.error("Non-numeric value for sensor %s: %r — skipping", code, value)
                continue

            # Clamp to min/max
            if value < sensor.min_val:
                logger.debug("Sensor %s value %s clamped to min %s", code, value, sensor.min_val)
                value = sensor.min_val
            elif value > sensor.max_val:
                logger.debug("Sensor %s value %s clamped to max %s", code, value, sensor.max_val)
                value = sensor.max_val

            # Update state
            sensor.value = value
            sensor.timestamp = now
            sensor.history.append({"value": value, "timestamp": now.isoformat()})
            emitted_codes.append(code)

            # Check warnings
            prev_warning = sensor.warning
            sensor.warning = self._check_thresholds(sensor)

            if sensor.warning != prev_warning:
                self._emit_sensor_warning(sensor, now)

            self._emit_sensor_data(sensor)

        if emitted_codes:
            logger.debug("Updated sensors: %s", ", ".join(emitted_codes))

    @staticmethod
    def _check_thresholds(sensor: Sensor):
        """Return "high", "low", or None depending on warning thresholds."""
        if sensor.warn_high is not None and sensor.value is not None and sensor.value >= sensor.warn_high:
            return "high"
        if sensor.warn_low is not None and sensor.value is not None and sensor.value <= sensor.warn_low:
            return "low"
        return None

    # -- query methods --------------------------------------------------------

    def get_all(self):
        """Return a list of dicts for every registered sensor."""
        return [s.to_dict() for s in self.sensors.values()]

    def get(self, code: str):
        """Return the Sensor object for *code*, or None."""
        return self.sensors.get(code.upper())

    def get_history(self, code: str, limit: int = 100):
        """
        Return the reading history for a sensor as a list of
        {value, timestamp} dicts (most recent last).

        Parameters
        ----------
        code : str
            Sensor code letter.
        limit : int
            Maximum number of entries to return (1–100).
        """
        sensor = self.sensors.get(code.upper())
        if sensor is None:
            logger.warning("get_history: unknown sensor '%s'", code)
            return []
        limit = max(1, min(limit, 100))
        # history is a deque; return the last *limit* entries
        return list(sensor.history)[-limit:]

    def get_chart_data(self, code: str = None, limit: int = 100):
        """
        Return data formatted for chart rendering.

        If *code* is given, returns a single dict:
            {code: {"name", "unit", "color", "data": [{value, timestamp}]}}
        If *code* is None, returns the same structure for every sensor.
        """
        limit = max(1, min(limit, 100))

        if code is not None:
            sensor = self.sensors.get(code.upper())
            if sensor is None:
                logger.warning("get_chart_data: unknown sensor '%s'", code)
                return {}
            return {
                sensor.code: {
                    "name": sensor.name,
                    "unit": sensor.unit,
                    "color": sensor.color,
                    "data": list(sensor.history)[-limit:],
                }
            }

        # All sensors
        result = {}
        for sensor in self.sensors.values():
            result[sensor.code] = {
                "name": sensor.name,
                "unit": sensor.unit,
                "color": sensor.color,
                "data": list(sensor.history)[-limit:],
            }
        return result

    # -- default sensors ------------------------------------------------------

    def load_default_sensors(self):
        """Register a built-in set of common robot sensors."""
        defaults = [
            Sensor(code="T", name="Temperature", unit="°C", icon="🌡️",
                   min_val=-40.0, max_val=125.0, warn_high=80.0, warn_low=-10.0,
                   color="#e74c3c"),
            Sensor(code="H", name="Humidity", unit="%", icon="💧",
                   min_val=0.0, max_val=100.0, warn_high=90.0, warn_low=10.0,
                   color="#3498db"),
            Sensor(code="G", name="Gas", unit="ppm", icon="☁️",
                   min_val=0.0, max_val=5000.0, warn_high=1000.0, warn_low=None,
                   color="#2ecc71"),
            Sensor(code="D", name="Distance", unit="cm", icon="📏",
                   min_val=2.0, max_val=400.0, warn_high=None, warn_low=10.0,
                   color="#9b59b6"),
            Sensor(code="L", name="Light", unit="lux", icon="☀️",
                   min_val=0.0, max_val=100000.0, warn_high=80000.0, warn_low=5.0,
                   color="#f1c40f"),
            Sensor(code="P", name="Pressure", unit="hPa", icon="🔻",
                   min_val=300.0, max_val=1100.0, warn_high=1050.0, warn_low=500.0,
                   color="#1abc9c"),
        ]
        for s in defaults:
            self.register_sensor(s)
        logger.info("Loaded %d default sensors", len(defaults))

    # -- persistence ----------------------------------------------------------

    def save_config(self, path=None):
        """
        Persist the current sensor configuration to a JSON file.
        Only metadata (not readings/history) is saved.
        """
        filepath = path or self.config_path
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            data = [s.to_config_dict() for s in self.sensors.values()]
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            logger.info("Saved sensor config to %s (%d sensors)", filepath, len(data))
        except Exception as exc:
            logger.error("Failed to save sensor config to %s: %s", filepath, exc)
            raise

    def load_config(self, path=None):
        """
        Load sensor configuration from a JSON file and register each sensor.
        Returns the number of sensors loaded.
        """
        filepath = path or self.config_path
        if not os.path.isfile(filepath):
            logger.warning("Sensor config file not found: %s", filepath)
            return 0
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            count = 0
            for entry in data:
                sensor = Sensor.from_config_dict(entry)
                self.register_sensor(sensor)
                count += 1
            logger.info("Loaded %d sensors from %s", count, filepath)
            return count
        except Exception as exc:
            logger.error("Failed to load sensor config from %s: %s", filepath, exc)
            raise

    # -- SocketIO helpers -----------------------------------------------------

    @staticmethod
    def _emit(event, data):
        """Safely emit a SocketIO event; silently skip if _socketio is not bound."""
        if _socketio is not None:
            try:
                _socketio.emit(event, data)
            except Exception as exc:
                logger.error("SocketIO emit error on '%s': %s", event, exc)
        else:
            logger.debug("SocketIO not bound — skipping emit for '%s'", event)

    def _emit_sensor_data(self, sensor: Sensor):
        """Emit a `sensor_data` event with the sensor's current state."""
        self._emit("sensor_data", sensor.to_dict())

    def _emit_sensor_warning(self, sensor: Sensor, ts: datetime):
        """Emit a `sensor_warning` event when a threshold is crossed."""
        self._emit("sensor_warning", {
            "code": sensor.code,
            "name": sensor.name,
            "value": sensor.value,
            "unit": sensor.unit,
            "warning": sensor.warning,
            "warn_high": sensor.warn_high,
            "warn_low": sensor.warn_low,
            "timestamp": ts.isoformat(),
        })
        logger.warning("Sensor %s %s warning: value=%s %s",
                       sensor.code, sensor.warning, sensor.value, sensor.unit)
