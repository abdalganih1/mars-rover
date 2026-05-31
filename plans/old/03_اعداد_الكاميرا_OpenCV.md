# 03 - إعداد الكاميرا مع OpenCV

## الهدف
إنشاء نظام بث حي (live stream) لكاميرا الراسبيري بي مع إمكانية التحكم بالمرشحات والألوان.

## الملف المسؤول
- `modules/camera.py`

## تفاصيل الوحدة: `camera.py`

### الكلاس: `CameraManager`

```python
class CameraManager:
    def __init__(self):
        self.camera_index = 0              # رقم الكاميرا (/dev/video0)
        self.cap = None                    # كائن VideoCapture
        self.is_running = False
        self.frame_width = 640
        self.frame_height = 480
        self.fps = 24
        self.jpeg_quality = 70             # جودة البث (1-100)
        
        # إعدادات الألوان والمرشحات
        self.color_mode = "RGB"            # RGB | BGR | Grayscale | Binary
        self.brightness = 50               # 0-100
        self.contrast = 50                 # 0-100
        self.saturation = 50               # 0-100
        self.hue = 0                       # 0-180
        
        # إعدادات متقدمة
        self.apply_edge_detection = False
        self.apply_blur = False
        self.blur_kernel = 5
        self.apply_threshold = False
        self.threshold_value = 128
        self.apply_roi = False             # Region of Interest
        self.roi_rect = None               # (x, y, w, h)
        
        # تحجيم
        self.resize_factor = 1.0           # 0.25 to 2.0
```

### الدوال المطلوبة

#### 1. `start() -> bool`
- يفتح الكاميرا عبر OpenCV:
  ```python
  self.cap = cv2.VideoCapture(self.camera_index)
  self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
  self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
  self.cap.set(cv2.CAP_PROP_FPS, self.fps)
  self.cap.set(cv2.CAP_PROP_BRIGHTNESS, self.brightness / 100.0)
  self.cap.set(cv2.CAP_PROP_CONTRAST, self.contrast / 100.0)
  self.cap.set(cv2.CAP_PROP_SATURATION, self.saturation / 100.0)
  ```
- يتحقق من نجاح الفتح
- يشغل خيط القراءة في الخلفية

#### 2. `stop() -> bool`
- يوقف خيط القراءة
- يحرر الكاميرا:
  ```python
  self.cap.release()
  ```

#### 3. `get_frame() -> bytes`
- يلتقط إطار من الكاميرا
- يطبق المرشحات المفعلة:
  ```python
  # 1. تحويل الألوان
  if self.color_mode == "Grayscale":
      frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
      frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)  # للبث عبر JPEG
  elif self.color_mode == "RGB":
      frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
  elif self.color_mode == "Binary":
      gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
      _, frame = cv2.threshold(gray, self.threshold_value, 255, cv2.THRESH_BINARY)
      frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
  # BGR هو الافتراضي من OpenCV (لا تحويل مطلوب)
  
  # 2. Edge Detection (Canny)
  if self.apply_edge_detection:
      edges = cv2.Canny(frame, 100, 200)
      frame = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
  
  # 3. Blur
  if self.apply_blur:
      frame = cv2.GaussianBlur(frame, (self.blur_kernel, self.blur_kernel), 0)
  
  # 4. ROI
  if self.apply_roi and self.roi_rect:
      x, y, w, h = self.roi_rect
      frame = frame[y:y+h, x:x+w]
  
  # 5. Resize
  if self.resize_factor != 1.0:
      frame = cv2.resize(frame, None, fx=self.resize_factor, fy=self.resize_factor)
  ```
- يحول الإطار إلى JPEG:
  ```python
  _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
  return buffer.tobytes()
  ```

#### 4. `capture_photo(filename: str) -> bool`
- يلتقط صورة بدقة عالية ويحفظها

#### 5. `start_recording(filename: str) -> bool`
- يبدأ تسجيل فيديو

#### 6. `stop_recording() -> str`
- يوقف التسجيل ويرجع مسار الملف

#### 7. `update_settings(settings: dict)`
- يحدث الإعدادات ديناميكياً:
  ```python
  def update_settings(self, settings):
      if "color_mode" in settings:
          self.color_mode = settings["color_mode"]
      if "brightness" in settings:
          self.brightness = settings["brightness"]
          if self.cap:
              self.cap.set(cv2.CAP_PROP_BRIGHTNESS, settings["brightness"] / 100.0)
      # ... باقي الإعدادات
  ```

#### 8. `get_settings() -> dict`
- يرجع كل الإعدادات الحالية

#### 9. `get_available_cameras() -> list`
- يبحث عن الكاميرات المتاحة
- يرجع قائمة بأرقام الكاميرات

## بث الكاميرا عبر WebSocket

### آلية البث
```python
# في خيط الخلفية (background thread)
def _stream_loop(self):
    while self.is_running:
        frame = self.get_frame()
        if frame:
            # إرسال الإطار لكل العملاء المتصلين عبر SocketIO
            socketio.emit('camera_frame', {'data': base64.b64encode(frame).decode('utf-8')})
        time.sleep(1.0 / self.fps)  # التحكم بالـ FPS
```

### استقبال في Frontend
```javascript
socket.on('camera_frame', function(data) {
    const img = document.getElementById('camera-feed');
    img.src = 'data:image/jpeg;base64,' + data.data;
});
```

## إعدادات الكاميرا (في config.yaml)

```yaml
camera:
  enabled: true
  camera_index: 0
  width: 640
  height: 480
  fps: 24
  jpeg_quality: 70
  
  # الألوان
  default_color_mode: "RGB"         # RGB | BGR | Grayscale | Binary
  
  # تعديلات الصورة
  brightness: 50                    # 0-100
  contrast: 50                      # 0-100
  saturation: 50                    # 0-100
  
  # مرشحات متقدمة
  edge_detection: false
  blur: false
  blur_kernel: 5
  
  # تحجيم
  resize_factor: 1.0
  
  # ROI (Region of Interest)
  roi_enabled: false
  roi_rect: [0, 0, 640, 480]
  
  # Binary threshold
  threshold_value: 128
  
  # تسجيل
  recording_path: "/home/user/program/recordings"
  photo_path: "/home/user/program/photos"
```

## واجهة إعدادات الكاميرا (Frontend)

### عناصر التحكم المطلوبة في صفحة الإعدادات:

#### قسم: وضع الألوان
- **Radio buttons** للاختيار بين:
  - `RGB` (أحمر أخضر أزرق - طبيعي)
  - `BGR` (أزرق أخضر أحمر - OpenCV الافتراضي)
  - `Grayscale` (تدرج رمادي)
  - `Binary` (أبيض وأسود فقط - threshold)

#### قسم: تعديلات الصورة
- **Brightness slider** (0-100)
- **Contrast slider** (0-100)
- **Saturation slider** (0-100)
- **JPEG Quality slider** (10-100) — جودة البث

#### قسم: مرشحات متقدمة
- **Edge Detection toggle** — كشف الحواف (Canny)
- **Blur toggle** + kernel size slider (3, 5, 7, 9)
- **Threshold slider** (0-255) — لوضع Binary

#### قسم: التحجيم
- **Resize factor slider** (0.25x - 2.0x)

#### قسم: ROI
- **ROI toggle** — تفعيل منطقة الاهتمام
- **X, Y, Width, Height inputs** — إحداثيات المنطقة
- أو **سحب بالماوس** على صورة الكاميرا لتحديد المنطقة

#### قسم: الدقة و FPS
- **Resolution dropdown**: 320x240, 640x480, 1280x720
- **FPS dropdown**: 15, 24, 30

#### أزرار:
- **📸 التقاط صورة** — يحفظ صورة فورية
- **⏺ بدء تسجيل** — يبدأ تسجيل فيديو
- **⏹ إيقاف تسجيل** — يوقف التسجيل

## معالجة الأخطاء

| الخطأ | المعالجة |
|-------|----------|
| الكاميرا غير متصلة | إعلام المستخدم + إعادة محاولة كل 5 ثواني |
| إطار فارغ | تسجيل تحذير + متابعة |
| FPS منخفض جداً | تقليل الدقة تلقائياً |
| مشكلة في الترميز | تسجيل خطأ + إرسال إطار أسود |

## اختبار الوحدة
```python
cam = CameraManager()
cam.start()

# اختبار التقاط إطار
frame = cam.get_frame()
print(f"Frame size: {len(frame)} bytes")

# اختبار تغيير الوضع
cam.update_settings({"color_mode": "Grayscale"})

# اختبار التقاط صورة
cam.capture_photo("/home/user/test_photo.jpg")

cam.stop()
```
