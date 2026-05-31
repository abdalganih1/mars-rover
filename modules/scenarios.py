"""
Scenario Manager Module for Raspberry Pi Robot.

Provides ScenarioManager, Scenario, and ScenarioStep classes for creating,
running, and managing motor command sequences (scenarios) with JSON persistence.

Scenarios are stored as JSON files in <project_root>/scenarios/.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCENARIOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios")


class ScenarioStep:
    """Represents a single step in a scenario with motor commands and duration."""

    def __init__(self, motors: Dict[str, Any], duration: int):
        """
        Initialize a ScenarioStep.

        Args:
            motors: Dict with motor/direction commands. Supported keys (case-insensitive):
                    m1, m2, m3, m4   — DC motor speeds (-255..255)
                    s1, s2           — servo angles (0..180)
                    direction        — direction preset key (F, B, L, R, FL, etc.)
                    speed            — speed scale for direction presets (0..100)
            duration: Duration of this step in milliseconds.

        Keys are normalised to lowercase so that execute_move receives
        the format it expects (fixes F12 — M1/M2 vs m1/m2 case mismatch).
        direction and speed fields are also preserved (F14).
        """
        # Normalise all keys to lowercase (F12)
        raw = {k.lower(): v for k, v in motors.items()}

        # Build the motors dict with known motor/servo keys, dropping None values
        self.motors: Dict[str, Any] = {}

        # DC motors (F12: accept both M1/m1 via normalisation above)
        for key in ("m1", "m2", "m3", "m4"):
            if key in raw and raw[key] is not None:
                self.motors[key] = raw[key]

        # Servo angles
        for key in ("s1", "s2"):
            if key in raw and raw[key] is not None:
                self.motors[key] = raw[key]

        # Direction preset support (F14)
        if "direction" in raw and raw["direction"] is not None:
            self.motors["direction"] = raw["direction"]
        if "speed" in raw and raw["speed"] is not None:
            self.motors["speed"] = raw["speed"]

        self.duration: int = duration

    def to_dict(self) -> dict:
        """Serialize this step to a dictionary."""
        return {
            "motors": dict(self.motors),
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScenarioStep":
        """Deserialize a ScenarioStep from a dictionary."""
        return cls(
            motors=data.get("motors", {}),
            duration=data.get("duration", 0),
        )

    def __repr__(self) -> str:
        return (
            f"ScenarioStep(motors={self.motors}, duration={self.duration}ms)"
        )


class Scenario:
    """Represents a named sequence of motor command steps."""

    def __init__(
        self,
        name: str,
        description: str = "",
        steps: Optional[List[ScenarioStep]] = None,
        loop: bool = False,
    ):
        """
        Initialize a Scenario.

        Args:
            name: Unique name identifying this scenario.
            description: Human-readable description of the scenario.
            steps: Ordered list of ScenarioStep objects.
            loop: If True, the scenario repeats until explicitly stopped.
        """
        self.name: str = name
        self.description: str = description
        self.steps: List[ScenarioStep] = steps if steps is not None else []
        self.loop: bool = loop

    def add_step(self, step: ScenarioStep) -> None:
        """Append a step to the scenario."""
        self.steps.append(step)
        logger.debug("Added step to scenario '%s': %s", self.name, step)

    def remove_step(self, index: int) -> None:
        """Remove the step at the given index."""
        if 0 <= index < len(self.steps):
            removed = self.steps.pop(index)
            logger.debug(
                "Removed step %d from scenario '%s': %s", index, self.name, removed
            )
        else:
            logger.warning(
                "Cannot remove step %d from scenario '%s': index out of range",
                index,
                self.name,
            )

    def to_dict(self) -> dict:
        """Serialize this scenario to a dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "loop": self.loop,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Scenario":
        """Deserialize a Scenario from a dictionary."""
        steps = [ScenarioStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            steps=steps,
            loop=data.get("loop", False),
        )

    def __repr__(self) -> str:
        return (
            f"Scenario(name='{self.name}', steps={len(self.steps)}, loop={self.loop})"
        )


class ScenarioManager:
    """Manages creation, execution, persistence, and deletion of scenarios."""

    def __init__(self, motor_controller, bt_manager=None, socketio=None):
        """
        Initialize the ScenarioManager.

        Args:
            motor_controller: Object with execute_move(dict) and emergency_stop() methods.
            bt_manager: Optional Bluetooth manager instance.
            socketio: Optional SocketIO instance for emitting scenario_progress events.
        """
        self.motor_controller = motor_controller
        self.bt_manager = bt_manager
        self._socketio = socketio

        self._scenarios: Dict[str, Scenario] = {}
        self._running: bool = False
        self._stop_event: threading.Event = threading.Event()
        self._run_thread: Optional[threading.Thread] = None
        self._current_scenario_name: Optional[str] = None
        self._lock = threading.Lock()

        os.makedirs(SCENARIOS_DIR, exist_ok=True)
        logger.info("ScenarioManager initialized. Scenarios dir: %s", SCENARIOS_DIR)

    # ── Scenario CRUD ────────────────────────────────────────────────────

    def create_scenario(
        self,
        name: str,
        description: str = "",
        steps: Optional[List[Dict]] = None,
        loop: bool = False,
    ) -> Scenario:
        """
        Create a new scenario and register it in memory.

        Args:
            name: Unique scenario name.
            description: Human-readable description.
            steps: List of step dicts, each with 'motors' and 'duration' keys.
            loop: Whether the scenario should loop when run.

        Returns:
            The created Scenario object.

        Raises:
            ValueError: If a scenario with the same name already exists.
        """
        if name in self._scenarios:
            logger.warning("Scenario '%s' already exists.", name)
            raise ValueError(f"Scenario '{name}' already exists.")

        scenario_steps = []
        if steps:
            for s in steps:
                scenario_steps.append(
                    ScenarioStep(
                        motors=s.get("motors", {}),
                        duration=s.get("duration", 0),
                    )
                )

        scenario = Scenario(
            name=name,
            description=description,
            steps=scenario_steps,
            loop=loop,
        )

        with self._lock:
            self._scenarios[name] = scenario

        logger.info("Created scenario '%s' with %d steps (loop=%s).", name, len(scenario_steps), loop)
        return scenario

    def delete_scenario(self, name: str) -> bool:
        """
        Delete a scenario from memory and remove its JSON file.

        Args:
            name: Name of the scenario to delete.

        Returns:
            True if deleted, False if not found.
        """
        with self._lock:
            if name not in self._scenarios:
                logger.warning("Cannot delete '%s': scenario not found.", name)
                return False
            del self._scenarios[name]

        # Also remove the persisted file if it exists
        filepath = os.path.join(SCENARIOS_DIR, f"{name}.json")
        if os.path.isfile(filepath):
            os.remove(filepath)
            logger.info("Deleted scenario file: %s", filepath)

        logger.info("Deleted scenario '%s'.", name)
        return True

    def list_scenarios(self) -> List[str]:
        """Return a list of all registered scenario names."""
        with self._lock:
            return list(self._scenarios.keys())

    def get_scenario(self, name: str) -> Optional[Scenario]:
        """
        Retrieve a scenario by name.

        Args:
            name: Scenario name.

        Returns:
            The Scenario object, or None if not found.
        """
        with self._lock:
            return self._scenarios.get(name)

    # ── Scenario Execution ───────────────────────────────────────────────

    def run_scenario(self, name: str) -> bool:
        """
        Start running a scenario in a background thread.

        Args:
            name: Name of the scenario to run.

        Returns:
            True if the scenario was started, False otherwise.
        """
        if self._running:
            logger.warning("Cannot start '%s': another scenario is already running.", name)
            return False

        scenario = self.get_scenario(name)
        if scenario is None:
            logger.error("Scenario '%s' not found.", name)
            return False

        if not scenario.steps:
            logger.warning("Scenario '%s' has no steps to execute.", name)
            return False

        self._running = True
        self._stop_event.clear()
        self._current_scenario_name = name

        self._run_thread = threading.Thread(
            target=self._run_loop,
            args=(scenario,),
            name=f"scenario-{name}",
            daemon=True,
        )
        self._run_thread.start()
        logger.info("Started running scenario '%s' in background thread.", name)
        return True

    def _run_loop(self, scenario: Scenario) -> None:
        """
        Internal method that executes the scenario steps. Runs in a background thread.
        Respects the loop flag and stop_event for graceful termination.
        """
        total_steps = len(scenario.steps)
        logger.info(
            "Scenario '%s' execution begun: %d steps, loop=%s",
            scenario.name,
            total_steps,
            scenario.loop,
        )

        try:
            iteration = 0
            while True:
                iteration += 1
                for idx, step in enumerate(scenario.steps):
                    if self._stop_event.is_set():
                        logger.info(
                            "Scenario '%s' stopped at iteration %d, step %d/%d.",
                            scenario.name,
                            iteration,
                            idx + 1,
                            total_steps,
                        )
                        self._emit_progress(
                            scenario.name,
                            iteration=iteration,
                            step=idx + 1,
                            total_steps=total_steps,
                            status="stopped",
                        )
                        return

                    logger.debug(
                        "Scenario '%s' iter %d – step %d/%d: motors=%s, duration=%dms",
                        scenario.name,
                        iteration,
                        idx + 1,
                        total_steps,
                        step.motors,
                        step.duration,
                    )

                    # Emit progress before executing the step
                    self._emit_progress(
                        scenario.name,
                        iteration=iteration,
                        step=idx + 1,
                        total_steps=total_steps,
                        status="running",
                    )

                    # Execute motor command
                    try:
                        self.motor_controller.execute_move(step.motors)
                    except Exception as e:
                        logger.error(
                            "Motor error during scenario '%s' step %d: %s",
                            scenario.name,
                            idx + 1,
                            e,
                        )
                        self._emit_progress(
                            scenario.name,
                            iteration=iteration,
                            step=idx + 1,
                            total_steps=total_steps,
                            status="error",
                            error=str(e),
                        )
                        return

                    # Wait for the step duration (check stop_event every 50ms)
                    remaining_ms = step.duration
                    while remaining_ms > 0:
                        if self._stop_event.is_set():
                            break
                        chunk = min(remaining_ms, 50)
                        time.sleep(chunk / 1000.0)
                        remaining_ms -= chunk

                # If not looping, we're done
                if not scenario.loop:
                    break

                if self._stop_event.is_set():
                    break

                logger.debug("Scenario '%s' looping (iteration %d complete).", scenario.name, iteration)

        except Exception as e:
            logger.exception("Unexpected error in scenario '%s': %s", scenario.name, e)
            self._emit_progress(
                scenario.name,
                iteration=0,
                step=0,
                total_steps=total_steps,
                status="error",
                error=str(e),
            )
        finally:
            self._running = False
            self._current_scenario_name = None
            logger.info("Scenario '%s' execution finished.", scenario.name)
            self._emit_progress(
                scenario.name,
                iteration=0,
                step=0,
                total_steps=total_steps,
                status="completed",
            )

    def stop_scenario(self) -> bool:
        """
        Stop the currently running scenario.

        Returns:
            True if a scenario was running and stop was signalled, False otherwise.
        """
        if not self._running:
            logger.warning("No scenario is currently running.")
            return False

        logger.info("Stopping scenario '%s'...", self._current_scenario_name)
        self._stop_event.set()

        try:
            self.motor_controller.emergency_stop()
            logger.info("Emergency stop sent to motor controller.")
        except Exception as e:
            logger.error("Failed to send emergency stop: %s", e)

        # Wait for thread to finish (with timeout)
        if self._run_thread is not None and self._run_thread.is_alive():
            self._run_thread.join(timeout=5.0)
            if self._run_thread.is_alive():
                logger.warning("Scenario thread did not terminate within timeout.")

        return True

    @property
    def is_running(self) -> bool:
        """Whether a scenario is currently executing."""
        return self._running

    @property
    def current_scenario(self) -> Optional[str]:
        """Name of the currently running scenario, or None."""
        return self._current_scenario_name

    # ── SocketIO Emission ────────────────────────────────────────────────

    def _emit_progress(
        self,
        scenario_name: str,
        iteration: int,
        step: int,
        total_steps: int,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Emit a scenario_progress event via SocketIO if available."""
        if self._socketio is None:
            return

        payload = {
            "scenario": scenario_name,
            "iteration": iteration,
            "step": step,
            "total_steps": total_steps,
            "status": status,
        }
        if error is not None:
            payload["error"] = error

        try:
            self._socketio.emit("scenario_progress", payload)
            logger.debug("Emitted scenario_progress: %s", payload)
        except Exception as e:
            logger.error("Failed to emit scenario_progress: %s", e)

    # ── Persistence ──────────────────────────────────────────────────────

    def save_to_file(self, name: str) -> bool:
        """
        Save a scenario to a JSON file in the scenarios directory.

        Args:
            name: Name of the scenario to save.

        Returns:
            True if saved successfully, False otherwise.
        """
        scenario = self.get_scenario(name)
        if scenario is None:
            logger.error("Cannot save: scenario '%s' not found.", name)
            return False

        filepath = os.path.join(SCENARIOS_DIR, f"{name}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(scenario.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info("Saved scenario '%s' to %s", name, filepath)
            return True
        except OSError as e:
            logger.error("Failed to save scenario '%s': %s", name, e)
            return False

    def load_from_file(self, name: str) -> Optional[Scenario]:
        """
        Load a scenario from a JSON file and register it in memory.

        Args:
            name: Name of the scenario (must match filename without .json).

        Returns:
            The loaded Scenario, or None on failure.
        """
        filepath = os.path.join(SCENARIOS_DIR, f"{name}.json")
        if not os.path.isfile(filepath):
            logger.warning("Scenario file not found: %s", filepath)
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load scenario from %s: %s", filepath, e)
            return None

        scenario = Scenario.from_dict(data)

        with self._lock:
            self._scenarios[scenario.name] = scenario

        logger.info("Loaded scenario '%s' from %s", scenario.name, filepath)
        return scenario

    def load_all(self) -> int:
        """
        Load all JSON scenario files from the scenarios directory.

        Returns:
            Number of scenarios successfully loaded.
        """
        if not os.path.isdir(SCENARIOS_DIR):
            logger.warning("Scenarios directory does not exist: %s", SCENARIOS_DIR)
            return 0

        count = 0
        for filename in os.listdir(SCENARIOS_DIR):
            if not filename.endswith(".json"):
                continue
            scenario_name = filename[:-5]  # strip .json
            result = self.load_from_file(scenario_name)
            if result is not None:
                count += 1

        logger.info("Loaded %d scenario(s) from %s", count, SCENARIOS_DIR)
        return count
