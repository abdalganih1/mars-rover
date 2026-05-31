"""
serial_comm.py — وحدة الاتصال السيريال عبر PySerial
تغلف PySerial مع قفل خيوط لمنع التعارض
"""

import serial
import threading
import logging
import json

logger = logging.getLogger(__name__)


class SerialCommunicator:
    """يغلف PySerial مع قفل خيوط لمنع تعارض القراءة/الكتابة"""

    def __init__(self, port: str, baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self.connection = None
        self.lock = threading.Lock()

    def open(self) -> bool:
        """يفتح الاتصال السيريال"""
        try:
            self.connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=1,
            )
            # انتظار قصير لاستقرار الاتصال
            if self.connection.isOpen():
                self.connection.reset_input_buffer()
                self.connection.reset_output_buffer()
            logger.info(f"Serial opened: {self.port} @ {self.baudrate}")
            return True
        except serial.SerialException as e:
            logger.error(f"Failed to open serial {self.port}: {e}")
            return False

    def close(self) -> bool:
        """يغلق الاتصال"""
        try:
            if self.connection and self.connection.is_open:
                self.connection.close()
            logger.info(f"Serial closed: {self.port}")
            return True
        except Exception as e:
            logger.error(f"Error closing serial: {e}")
            return False

    def write(self, data: bytes) -> int:
        """يكتب بيانات خام"""
        with self.lock:
            try:
                if self.connection and self.connection.is_open:
                    return self.connection.write(data)
            except Exception as e:
                logger.error(f"Serial write error: {e}")
        return 0

    def write_line(self, line: str) -> bool:
        """يكتب سطر نصي + newline"""
        with self.lock:
            try:
                if self.connection and self.connection.is_open:
                    self.connection.write((line + "\n").encode("utf-8"))
                    self.connection.flush()
                    return True
            except Exception as e:
                logger.error(f"Serial write_line error: {e}")
        return False

    def read_line(self, timeout: float = 1.0) -> str:
        """يقرأ سطر واحد من السيريال (حتى \\n)"""
        with self.lock:
            try:
                if self.connection and self.connection.is_open:
                    old_timeout = self.connection.timeout
                    self.connection.timeout = timeout
                    line = self.connection.readline()
                    self.connection.timeout = old_timeout
                    if line:
                        return line.decode("utf-8", errors="ignore").strip()
            except Exception as e:
                logger.debug(f"Serial read error: {e}")
        return ""

    def read_json(self, timeout: float = 1.0) -> dict:
        """يقرأ سطر ويحوله من JSON إلى dict"""
        line = self.read_line(timeout)
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                logger.debug(f"Invalid JSON from serial: {line}")
        return None

    def is_open(self) -> bool:
        """هل الاتصال مفتوح؟"""
        return self.connection is not None and self.connection.is_open

    def flush(self):
        """يمسح المخزن المؤقت"""
        try:
            if self.connection and self.connection.is_open:
                self.connection.reset_input_buffer()
                self.connection.reset_output_buffer()
        except Exception:
            pass
