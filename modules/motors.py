"""
MotorController module for Raspberry Pi robot.

Controls 4 DC motors (M1-M4: -255 to 255) and 2 Servo motors (S1, S2: 0-180°).
Sends commands to the Arduino/MCU via BluetoothManager and emits status via SocketIO.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MotorController:
    """Manages DC and servo motors with direction commands, direct JSON control,
    speed ramping, and emergency stop."""

    # ── Motor limits ────────────────────────────────────────────────────
    DC_MIN = -255
    DC_MAX = 255
    SERVO_MIN = 0
    SERVO_MAX = 180
    SERVO_CENTER = 90
    RAMP_STEP = 10  # speed change per ramp tick
    RAMP_DELAY = 0.05  # seconds between ramp ticks

    # ── Preset direction command table ──────────────────────────────────
    # Each entry maps a command key to left/right side speed values.
    # l = left side (m1 + m3), r = right side (m2 + m4)
    DIRECTION_PRESETS: Dict[str, Dict[str, int]] = {
        "F":        {"l": 200, "r": 200},
        "B":        {"l": -200, "r": -200},
        "L":        {"l": -150, "r": 150},
        "R":        {"l": 150, "r": -150},
        "S":        {"l": 0, "r": 0},
        "FL":       {"l": 100, "r": 200},
        "FR":       {"l": 200, "r": 100},
        "BL":       {"l": -100, "r": -200},
        "BR":       {"l": -200, "r": -100},
        "SPIN_L":   {"l": -200, "r": 200},
        "SPIN_R":   {"l": 200, "r": -200},
    }

    def __init__(self, bt_manager: Any, socketio: Any = None) -> None:
        """
        Initialise the MotorController.

        Args:
            bt_manager: A BluetoothManager instance with a ``send_json(data)`` method.
            socketio:    Optional SocketIO instance for emitting ``motor_status`` events.
        """
        self._bt_manager = bt_manager
        self._socketio = socketio

        # Current motor state — 4 DC motors + 2 servos
        self._m1_speed: int = 0
        self._m2_speed: int = 0
        self._m3_speed: int = 0
        self._m4_speed: int = 0
        self._s1_angle: int = self.SERVO_CENTER
        self._s2_angle: int = self.SERVO_CENTER

        # Ramping state
        self._ramp_thread: Optional[threading.Thread] = None
        self._ramp_stop_event = threading.Event()
        self._ramp_targets: Dict[str, int] = {}

        self._lock = threading.Lock()

        logger.info("MotorController initialised (bt_manager=%s)", type(bt_manager).__name__)

    # ── Public helpers ──────────────────────────────────────────────────

    def emergency_stop(self) -> Dict[str, Any]:
        """Immediately halt all motors and center servos.

        Cancels any in-progress ramp, zeroes DC motors, and returns servos
        to their centre position (90°).
        """
        logger.warning("EMERGENCY STOP triggered")
        self._cancel_ramp()

        with self._lock:
            self._m1_speed = 0
            self._m2_speed = 0
            self._m3_speed = 0
            self._m4_speed = 0
            self._s1_angle = self.SERVO_CENTER
            self._s2_angle = self.SERVO_CENTER

        payload = self._build_command(
            m1=0, m2=0, m3=0, m4=0,
            s1=self.SERVO_CENTER,
            s2=self.SERVO_CENTER,
        )
        self._send(payload)
        self._emit_status("emergency_stop")
        return {"status": "ok", "action": "emergency_stop"}

    def center_servos(self) -> Dict[str, Any]:
        """Move both servos to the centre position (90°)."""
        logger.info("Centering servos")
        return self.set_servo_angle(s1=self.SERVO_CENTER, s2=self.SERVO_CENTER)

    # ── DC motor control ────────────────────────────────────────────────

    def set_motor_speed(
        self,
        m1: Optional[int] = None,
        m2: Optional[int] = None,
        ramp: bool = False,
    ) -> Dict[str, Any]:
        """Set DC motor speeds directly (m1/m2 side-paired with m3/m4).

        Args:
            m1:   Speed for motor 1 (-255 … 255). ``None`` leaves unchanged.
                  m3 mirrors m1 (left side).
            m2:   Speed for motor 2 (-255 … 255). ``None`` leaves unchanged.
                  m4 mirrors m2 (right side).
            ramp: If True, smoothly ramp to the target speed instead of
                  setting it immediately.
        """
        with self._lock:
            target_m1 = self._clamp_dc(m1 if m1 is not None else self._m1_speed)
            target_m2 = self._clamp_dc(m2 if m2 is not None else self._m2_speed)

        if ramp:
            logger.info("Ramping motors → m1=%d, m2=%d", target_m1, target_m2)
            self._start_ramp(target_m1, target_m2)
            return {"status": "ok", "action": "ramp", "targets": {"m1": target_m1, "m2": target_m2}}

        with self._lock:
            self._m1_speed = target_m1
            self._m2_speed = target_m2
            self._m3_speed = target_m1  # mirrors left side
            self._m4_speed = target_m2  # mirrors right side

        payload = self._build_command(m1=target_m1, m2=target_m2,
                                      m3=target_m1, m4=target_m2)
        self._send(payload)
        self._emit_status("set_motor_speed")
        return {"status": "ok", "action": "set_motor_speed",
                "m1": target_m1, "m2": target_m2,
                "m3": target_m1, "m4": target_m2}

    def set_side_speed(self, left: int, right: int) -> Dict[str, Any]:
        """Set left-side (m1/m3) and right-side (m2/m4) speeds directly.

        Args:
            left:  Speed for the left side motors (-255 … 255).
            right: Speed for the right side motors (-255 … 255).
        """
        l = self._clamp_dc(left)
        r = self._clamp_dc(right)

        with self._lock:
            self._m1_speed = l
            self._m2_speed = r
            self._m3_speed = l
            self._m4_speed = r

        payload = self._build_command(m1=l, m2=r, m3=l, m4=r)
        self._send(payload)
        self._emit_status("set_side_speed")
        return {"status": "ok", "action": "set_side_speed",
                "m1": l, "m2": r, "m3": l, "m4": r}

    # ── Servo control ───────────────────────────────────────────────────

    def set_servo_angle(
        self,
        s1: Optional[int] = None,
        s2: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Set servo angles (0–180°).

        Args:
            s1: Angle for servo 1. ``None`` leaves unchanged.
            s2: Angle for servo 2. ``None`` leaves unchanged.
        """
        with self._lock:
            angle_s1 = self._clamp_servo(s1 if s1 is not None else self._s1_angle)
            angle_s2 = self._clamp_servo(s2 if s2 is not None else self._s2_angle)
            self._s1_angle = angle_s1
            self._s2_angle = angle_s2

        payload = self._build_command(s1=angle_s1, s2=angle_s2)
        self._send(payload)
        self._emit_status("set_servo_angle")
        logger.info("Servos set → s1=%d°, s2=%d°", angle_s1, angle_s2)
        return {"status": "ok", "action": "set_servo_angle", "s1": angle_s1, "s2": angle_s2}

    # ── High-level move command ─────────────────────────────────────────

    def execute_move(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a move command.

        Accepts two formats:

        1. **Direction command** – ``{"direction": "F"}`` (or any key in
           ``DIRECTION_PRESETS``).  An optional ``"speed"`` key (0–100) scales
           the preset values proportionally.

        2. **Direct JSON command** – ``{"m1": 150, "m2": -100, "s1": 45}``
           containing raw motor/servo values. m3/m4 are also supported.

        Returns a status dict describing what was executed.
        """
        if not isinstance(data, dict):
            logger.error("execute_move received non-dict data: %s", data)
            return {"status": "error", "message": "data must be a dict"}

        direction = data.get("direction")

        # ── Preset direction command ─────────────────────────────────────
        if direction is not None:
            direction = str(direction).upper()
            if direction not in self.DIRECTION_PRESETS:
                logger.warning("Unknown direction command: '%s'", direction)
                return {"status": "error", "message": f"unknown direction: {direction}"}

            preset = self.DIRECTION_PRESETS[direction]
            speed_scale = max(0, min(100, int(data.get("speed", 100)))) / 100.0

            # l = left side, r = right side
            l = int(preset["l"] * speed_scale)
            r = int(preset["r"] * speed_scale)

            m1 = self._clamp_dc(l)
            m2 = self._clamp_dc(r)
            m3 = m1  # rear-left mirrors front-left
            m4 = m2  # rear-right mirrors front-right

            with self._lock:
                self._m1_speed = m1
                self._m2_speed = m2
                self._m3_speed = m3
                self._m4_speed = m4

            payload = self._build_command(m1=m1, m2=m2, m3=m3, m4=m4)
            self._send(payload)
            self._emit_status(f"direction:{direction}")

            logger.info(
                "Direction '%s' executed → m1=%d, m2=%d, m3=%d, m4=%d (scale=%.0f%%)",
                direction, m1, m2, m3, m4, speed_scale * 100,
            )
            return {
                "status": "ok",
                "action": "direction",
                "direction": direction,
                "m1": m1, "m2": m2, "m3": m3, "m4": m4,
            }

        # ── Direct JSON motor/servo command ──────────────────────────────
        logger.debug("Processing direct JSON command: %s", data)

        m1 = data.get("m1")
        m2 = data.get("m2")
        m3 = data.get("m3")
        m4 = data.get("m4")
        s1 = data.get("s1")
        s2 = data.get("s2")
        ramp = bool(data.get("ramp", False))

        result: Dict[str, Any] = {"status": "ok", "action": "direct"}

        # Handle motors (with optional ramping)
        if m1 is not None or m2 is not None or m3 is not None or m4 is not None:
            if ramp:
                target_m1 = self._clamp_dc(int(m1)) if m1 is not None else self._m1_speed
                target_m2 = self._clamp_dc(int(m2)) if m2 is not None else self._m2_speed
                self._start_ramp(target_m1, target_m2)
                result["ramp"] = {"m1": target_m1, "m2": target_m2}
            else:
                with self._lock:
                    if m1 is not None:
                        self._m1_speed = self._clamp_dc(int(m1))
                    if m2 is not None:
                        self._m2_speed = self._clamp_dc(int(m2))
                    if m3 is not None:
                        self._m3_speed = self._clamp_dc(int(m3))
                    else:
                        # m3 defaults to mirror m1 if m1 was given and m3 not explicit
                        if m1 is not None:
                            self._m3_speed = self._m1_speed
                    if m4 is not None:
                        self._m4_speed = self._clamp_dc(int(m4))
                    else:
                        # m4 defaults to mirror m2 if m2 was given and m4 not explicit
                        if m2 is not None:
                            self._m4_speed = self._m2_speed

                payload = self._build_command(
                    m1=self._m1_speed, m2=self._m2_speed,
                    m3=self._m3_speed, m4=self._m4_speed,
                )
                self._send(payload)
                result["m1"] = self._m1_speed
                result["m2"] = self._m2_speed
                result["m3"] = self._m3_speed
                result["m4"] = self._m4_speed

        # Handle servos
        if s1 is not None or s2 is not None:
            if s1 is not None:
                self._s1_angle = self._clamp_servo(int(s1))
            if s2 is not None:
                self._s2_angle = self._clamp_servo(int(s2))
            payload = self._build_command(s1=self._s1_angle, s2=self._s2_angle)
            self._send(payload)
            result["s1"] = self._s1_angle
            result["s2"] = self._s2_angle

        self._emit_status("direct_command")
        logger.info("Direct command executed → %s", result)
        return result

    # ── State query ─────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        """Return the current motor and servo state."""
        with self._lock:
            return {
                "m1": self._m1_speed,
                "m2": self._m2_speed,
                "m3": self._m3_speed,
                "m4": self._m4_speed,
                "s1": self._s1_angle,
                "s2": self._s2_angle,
            }

    # ── Speed ramping (background thread) ───────────────────────────────

    def _start_ramp(self, target_m1: int, target_m2: int) -> None:
        """Start a background thread to ramp motor speeds smoothly."""
        self._cancel_ramp()
        self._ramp_stop_event.clear()
        self._ramp_targets = {"m1": target_m1, "m2": target_m2}

        self._ramp_thread = threading.Thread(
            target=self._ramp_worker,
            name="motor-ramp",
            daemon=True,
        )
        self._ramp_thread.start()
        logger.debug("Ramp thread started → m1=%d, m2=%d", target_m1, target_m2)

    def _cancel_ramp(self) -> None:
        """Stop any running ramp thread."""
        if self._ramp_thread is not None and self._ramp_thread.is_alive():
            self._ramp_stop_event.set()
            self._ramp_thread.join(timeout=1.0)
            logger.debug("Previous ramp thread cancelled")

    def _ramp_worker(self) -> None:
        """Background worker that gradually adjusts motor speeds."""
        while not self._ramp_stop_event.is_set():
            with self._lock:
                cur_m1 = self._m1_speed
                cur_m2 = self._m2_speed

            tgt_m1 = self._ramp_targets.get("m1", cur_m1)
            tgt_m2 = self._ramp_targets.get("m2", cur_m2)

            new_m1 = self._ramp_step(cur_m1, tgt_m1)
            new_m2 = self._ramp_step(cur_m2, tgt_m2)

            with self._lock:
                self._m1_speed = new_m1
                self._m2_speed = new_m2
                self._m3_speed = new_m1  # mirror left
                self._m4_speed = new_m2  # mirror right

            payload = self._build_command(m1=new_m1, m2=new_m2,
                                          m3=new_m1, m4=new_m2)
            self._send(payload)
            self._emit_status("ramp_tick")

            # Check if we have reached the targets
            if new_m1 == tgt_m1 and new_m2 == tgt_m2:
                logger.debug("Ramp complete → m1=%d, m2=%d", new_m1, new_m2)
                break

            if self._ramp_stop_event.wait(timeout=self.RAMP_DELAY):
                break  # cancelled

        logger.debug("Ramp worker exiting")

    @staticmethod
    def _ramp_step(current: int, target: int) -> int:
        """Compute one ramp step towards *target* from *current*."""
        diff = target - current
        if diff == 0:
            return current
        step = MotorController.RAMP_STEP if diff > 0 else -MotorController.RAMP_STEP
        new_val = current + step
        # Don't overshoot
        if (step > 0 and new_val > target) or (step < 0 and new_val < target):
            return target
        return new_val

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _build_command(
        m1: Optional[int] = None,
        m2: Optional[int] = None,
        m3: Optional[int] = None,
        m4: Optional[int] = None,
        s1: Optional[int] = None,
        s2: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Construct a JSON command payload, omitting ``None`` values.

        Note: "type" key is intentionally omitted per unified JSON protocol
        (04_json_protocol.md). The Arduino ignores it anyway.
        """
        cmd: Dict[str, Any] = {}
        if m1 is not None:
            cmd["m1"] = m1
        if m2 is not None:
            cmd["m2"] = m2
        if m3 is not None:
            cmd["m3"] = m3
        if m4 is not None:
            cmd["m4"] = m4
        if s1 is not None:
            cmd["s1"] = s1
        if s2 is not None:
            cmd["s2"] = s2
        return cmd

    def _send(self, payload: Dict[str, Any]) -> None:
        """Send a JSON payload via the Bluetooth manager."""
        try:
            self._bt_manager.send_json(payload)
            logger.debug("Sent BT payload: %s", payload)
        except Exception:
            logger.exception("Failed to send BT payload: %s", payload)

    def _emit_status(self, source: str) -> None:
        """Emit a ``motor_status`` SocketIO event with the current state."""
        if self._socketio is None:
            return
        try:
            state = self.get_state()
            state["source"] = source
            self._socketio.emit("motor_status", state)
            logger.debug("Emitted motor_status (source=%s)", source)
        except Exception:
            logger.exception("Failed to emit motor_status event")

    @classmethod
    def _clamp_dc(cls, value: int) -> int:
        """Clamp a DC motor speed to [-255, 255]."""
        return max(cls.DC_MIN, min(cls.DC_MAX, int(value)))

    @classmethod
    def _clamp_servo(cls, value: int) -> int:
        """Clamp a servo angle to [0, 180]."""
        return max(cls.SERVO_MIN, min(cls.SERVO_MAX, int(value)))
