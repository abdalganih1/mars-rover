"""
camera.py — نظام الكاميرا مع OpenCV
بث حي + مرشحات (RGB, BGR, Grayscale, Binary) + إعدادات كاملة
"""

import cv2
import base64
import threading
import time
import os
import logging
import numpy as np

logger = logging.getLogger(__name__)


class CameraManager:
    """إدارة كاميرا الراسبيري بي مع OpenCV"""

    def __init__(self, config: dict):
        cfg = config or {}
        self.camera_index = cfg.get("camera_index", 0)
        self.frame_width = cfg.get("width", 640)
        self.frame_height = cfg.get("height", 480)
        self.fps = cfg.get("fps", 24)
        self.jpeg_quality = cfg.get("jpeg_quality", 70)

        # إعدادات الألوان
        self.color_mode = cfg.get("default_color_mode", "RGB")
        self.brightness = cfg.get("brightness", 50)
        self.contrast = cfg.get("contrast", 50)
        self.saturation = cfg.get("saturation", 50)

        # مرشحات
        self.edge_detection = cfg.get("edge_detection", False)
        self.blur = cfg.get("blur", False)
        self.blur_kernel = cfg.get("blur_kernel", 5)
        self.threshold_value = cfg.get("threshold_value", 128)

        # تحجيم و ROI
        self.resize_factor = cfg.get("resize_factor", 1.0)
        self.roi_enabled = cfg.get("roi_enabled", False)
        self.roi_rect = tuple(cfg.get("roi_rect", [0, 0, 640, 480]))

        # مسارات
        self.photo_path = cfg.get("photo_path", "/home/user/program/photos")
        self.recording_path = cfg.get("recording_path", "/home/user/program/recordings")

        # حالة
        self.cap = None
        self.is_running = False
        self._socketio = None
        self._stream_thread = None
        self._recording = False
        self._video_writer = None

    # ─────────────────── بدء/إيقاف ───────────────────

    def start(self) -> bool:
        """يفتح الكاميرا ويبدأ البث"""
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                logger.error(f"Cannot open camera {self.camera_index}")
                return False

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            self.cap.set(cv2.CAP_PROP_BRIGHTNESS, self.brightness / 100.0)
            self.cap.set(cv2.CAP_PROP_CONTRAST, self.contrast / 100.0)
            self.cap.set(cv2.CAP_PROP_SATURATION, self.saturation / 100.0)

            self.is_running = True
            logger.info(f"Camera started: {self.frame_width}x{self.frame_height} @ {self.fps}fps")
            return True
        except Exception as e:
            logger.error(f"Camera start error: {e}")
            return False

    def stop(self) -> bool:
        """يوقف الكاميرا"""
        self.is_running = False
        if self._recording:
            self.stop_recording()
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info("Camera stopped")
        return True

    # ─────────────────── التقاط إطار ───────────────────

    def get_frame(self) -> bytes:
        """يلتقط إطار ويطبق المرشحات ويرجع JPEG bytes"""
        if not self.cap or not self.cap.isOpened():
            return b""

        ret, frame = self.cap.read()
        if not ret:
            return b""

        frame = self._apply_filters(frame)

        # تحويل إلى JPEG
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        success, buffer = cv2.imencode(".jpg", frame, encode_params)
        if success:
            return buffer.tobytes()
        return b""

    def _apply_filters(self, frame: np.ndarray) -> np.ndarray:
        """يطبق المرشحات المفعلة على الإطار"""

        # 1. تحويل الألوان
        if self.color_mode == "RGB":
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        elif self.color_mode == "Grayscale":
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif self.color_mode == "Binary":
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            _, frame = cv2.threshold(
                gray, self.threshold_value, 255, cv2.THRESH_BINARY
            )
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        # BGR = الافتراضي من OpenCV (لا تحويل)

        # 2. Edge Detection
        if self.edge_detection:
            edges = cv2.Canny(frame, 100, 200)
            frame = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

        # 3. Blur
        if self.blur:
            k = self.blur_kernel if self.blur_kernel % 2 == 1 else self.blur_kernel + 1
            frame = cv2.GaussianBlur(frame, (k, k), 0)

        # 4. ROI
        if self.roi_enabled and self.roi_rect:
            x, y, w, h = self.roi_rect
            h_img, w_img = frame.shape[:2]
            x = max(0, min(x, w_img - 1))
            y = max(0, min(y, h_img - 1))
            w = min(w, w_img - x)
            h = min(h, h_img - y)
            if w > 0 and h > 0:
                frame = frame[y : y + h, x : x + w]

        # 5. Resize
        if self.resize_factor != 1.0 and self.resize_factor > 0:
            frame = cv2.resize(
                frame,
                None,
                fx=self.resize_factor,
                fy=self.resize_factor,
                interpolation=cv2.INTER_LINEAR,
            )

        return frame

    # ─────────────────── صور وتسجيل ───────────────────

    def capture_photo(self, filename: str = None) -> str:
        """يلتقط صورة ويحفظها"""
        if not self.cap or not self.cap.isOpened():
            return ""

        if not filename:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"photo_{timestamp}.jpg"

        os.makedirs(self.photo_path, exist_ok=True)
        filepath = os.path.join(self.photo_path, filename)

        ret, frame = self.cap.read()
        if ret:
            frame = self._apply_filters(frame)
            cv2.imwrite(filepath, frame)
            logger.info(f"Photo saved: {filepath}")
            return filepath
        return ""

    def start_recording(self, filename: str = None) -> bool:
        """يبدأ تسجيل فيديو"""
        if not self.cap or not self.cap.isOpened():
            return False

        if not filename:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.avi"

        os.makedirs(self.recording_path, exist_ok=True)
        filepath = os.path.join(self.recording_path, filename)

        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        self._video_writer = cv2.VideoWriter(
            filepath, fourcc, self.fps, (self.frame_width, self.frame_height)
        )
        self._recording = True
        logger.info(f"Recording started: {filepath}")
        return True

    def stop_recording(self) -> str:
        """يوقف التسجيل"""
        self._recording = False
        filepath = ""
        if self._video_writer:
            filepath = self._video_writer.release() or ""
            self._video_writer = None
        logger.info("Recording stopped")
        return filepath

    # ─────────────────── إعدادات ───────────────────

    def update_settings(self, settings: dict):
        """يحدث الإعدادات ديناميكياً"""
        if "color_mode" in settings:
            self.color_mode = settings["color_mode"]
        if "brightness" in settings:
            self.brightness = settings["brightness"]
            if self.cap:
                self.cap.set(cv2.CAP_PROP_BRIGHTNESS, self.brightness / 100.0)
        if "contrast" in settings:
            self.contrast = settings["contrast"]
            if self.cap:
                self.cap.set(cv2.CAP_PROP_CONTRAST, self.contrast / 100.0)
        if "saturation" in settings:
            self.saturation = settings["saturation"]
            if self.cap:
                self.cap.set(cv2.CAP_PROP_SATURATION, self.saturation / 100.0)
        if "jpeg_quality" in settings:
            self.jpeg_quality = settings["jpeg_quality"]
        if "edge_detection" in settings:
            self.edge_detection = settings["edge_detection"]
        if "blur" in settings:
            self.blur = settings["blur"]
        if "blur_kernel" in settings:
            self.blur_kernel = settings["blur_kernel"]
        if "threshold_value" in settings:
            self.threshold_value = settings["threshold_value"]
        if "resize_factor" in settings:
            self.resize_factor = settings["resize_factor"]
        if "roi_enabled" in settings:
            self.roi_enabled = settings["roi_enabled"]
        if "roi_rect" in settings:
            self.roi_rect = tuple(settings["roi_rect"])
        if "fps" in settings:
            self.fps = settings["fps"]
        if "width" in settings and "height" in settings:
            self.frame_width = settings["width"]
            self.frame_height = settings["height"]
            if self.cap:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)

    def get_settings(self) -> dict:
        """يرجع كل الإعدادات الحالية"""
        return {
            "camera_index": self.camera_index,
            "width": self.frame_width,
            "height": self.frame_height,
            "fps": self.fps,
            "jpeg_quality": self.jpeg_quality,
            "color_mode": self.color_mode,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "saturation": self.saturation,
            "edge_detection": self.edge_detection,
            "blur": self.blur,
            "blur_kernel": self.blur_kernel,
            "threshold_value": self.threshold_value,
            "resize_factor": self.resize_factor,
            "roi_enabled": self.roi_enabled,
            "roi_rect": list(self.roi_rect),
        }

    # ─────────────────── بث عبر WebSocket ───────────────────

    def start_stream(self, socketio):
        """يبدأ خيط بث الكاميرا"""
        self._socketio = socketio
        self._stream_thread = threading.Thread(
            target=self._stream_loop, daemon=True
        )
        self._stream_thread.start()
        logger.info("Camera stream started")

    def stop_stream(self):
        """يوقف البث"""
        self.is_running = False

    def _stream_loop(self):
        """بث إطارات الكاميرا عبر WebSocket"""
        while self.is_running:
            try:
                if not self.cap or not self.cap.isOpened():
                    time.sleep(1)
                    continue

                ret, frame = self.cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue

                # تسجيل الإطار لو مفعل
                if self._recording and self._video_writer:
                    self._video_writer.write(frame)

                # تطبيق المرشحات
                frame = self._apply_filters(frame)

                # تحويل إلى JPEG ثم base64
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
                success, buffer = cv2.imencode(".jpg", frame, encode_params)
                if success and self._socketio:
                    encoded = base64.b64encode(buffer.tobytes()).decode("utf-8")
                    self._socketio.emit("camera_frame", {"data": encoded})

                # التحكم بالـ FPS
                time.sleep(1.0 / self.fps)

            except Exception as e:
                logger.error(f"Stream error: {e}")
                time.sleep(0.5)

    # ─────────────────── معلومات ───────────────────

    def get_available_cameras(self) -> list:
        """يرجع قائمة الكاميرات المتاحة"""
        cameras = []
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                cameras.append(i)
                cap.release()
        return cameras
