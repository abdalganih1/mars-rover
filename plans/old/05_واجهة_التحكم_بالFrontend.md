# 05 - بناء واجهة التحكم بالحركة (Frontend)

## الهدف
إنشاء واجهة تحكم متجاوبة تعمل على الموبايل والكمبيوتر مع دعم الضغط المطول والتوقف عند رفع الإصبع.

## الملفات
- `templates/index.html` — الصفحة الرئيسية
- `static/css/style.css` + `controls.css` — الأنماط
- `static/js/controls.js` — منطق التحكم

## تصميم الصفحة الرئيسية

### التخطيط (Layout)

```
┌──────────────────────────────────┐
│          شريط العنوان            │
│  🤖 Robot Control    ⚙️ إعدادات  │
├──────────────────────────────────┤
│                                  │
│        🔴 بث الكاميرا المباشر     │
│         (يعرض هنا)               │
│                                  │
├──────────────────────────────────┤
│     قراءات الحساسات (شريط)       │
│  🌡️ 25°C  💨 0.2  💧 60%        │
├──────────────────────────────────┤
│                                  │
│         ▲ أمام (F)               │
│                                  │
│  ◄ يسار   ⬛ توقف   يمين ►       │
│  (L)                    (R)      │
│                                  │
│         ▼ خلف (B)                │
│                                  │
├──────────────────────────────────┤
│     🎛️ تحكم بالسرعة              │
│  M1: [━━━━━━━━●━━━] 200         │
│  M2: [━━━━━━━━●━━━] 200         │
│  السرعة العامة: [━━●━━━━━] 60%   │
├──────────────────────────────────┤
│  📊 المحركات  │  📷 كاميرا │ ... │
└──────────────────────────────────┘
```

## قسم أزرار الحركة — التفاصيل الدقيقة

### ⚠️ مشكلة الضغط المطول
المشكلة: على الموبايل، الضغط المطول على زر قد يفعل:
- قائمة السياق (context menu)
- اختيار النص
- تضخيم الشاشة (zoom)
- touch events غير متسقة

### ✅ الحل: Touch Events + Pointer Events

```javascript
class MovementButton {
    constructor(elementId, command) {
        this.element = document.getElementById(elementId);
        this.command = command;
        this.isPressed = false;
        this.pressInterval = null;
        
        this.setupEvents();
    }
    
    setupEvents() {
        // منع السلوك الافتراضي
        this.element.addEventListener('contextmenu', (e) => e.preventDefault());
        this.element.addEventListener('selectstart', (e) => e.preventDefault());
        this.element.addEventListener('dragstart', (e) => e.preventDefault());
        
        // Touch Events (موبايل)
        this.element.addEventListener('touchstart', (e) => {
            e.preventDefault();
            this.onPress();
        }, { passive: false });
        
        this.element.addEventListener('touchend', (e) => {
            e.preventDefault();
            this.onRelease();
        }, { passive: false });
        
        this.element.addEventListener('touchcancel', (e) => {
            e.preventDefault();
            this.onRelease();
        }, { passive: false });
        
        // Mouse Events (كمبيوتر)
        this.element.addEventListener('mousedown', (e) => {
            e.preventDefault();
            this.onPress();
        });
        
        this.element.addEventListener('mouseup', (e) => {
            e.preventDefault();
            this.onRelease();
        });
        
        this.element.addEventListener('mouseleave', (e) => {
            if (this.isPressed) {
                this.onRelease();
            }
        });
        
        // Keyboard (إضافي - WASD)
        document.addEventListener('keydown', (e) => {
            if (!this.isPressed && this.matchesKey(e.key)) {
                this.onPress();
            }
        });
        
        document.addEventListener('keyup', (e) => {
            if (this.isPressed && this.matchesKey(e.key)) {
                this.onRelease();
            }
        });
    }
    
    onPress() {
        this.isPressed = true;
        this.element.classList.add('active');
        this.sendCommand();
        // إرسال متكرر كل 100ms لضمان الاستمرارية
        this.pressInterval = setInterval(() => {
            this.sendCommand();
        }, 100);
    }
    
    onRelease() {
        this.isPressed = false;
        this.element.classList.remove('active');
        clearInterval(this.pressInterval);
        // إرسال أمر توقف فوراً
        socket.emit('stop');
    }
    
    sendCommand() {
        socket.emit('move', {
            direction: this.command,
            speed: currentSpeed
        });
    }
    
    matchesKey(key) {
        const keyMap = {
            'F': ['w', 'W', 'ArrowUp'],
            'B': ['s', 'S', 'ArrowDown'],
            'L': ['a', 'A', 'ArrowLeft'],
            'R': ['d', 'D', 'ArrowRight']
        };
        return keyMap[this.command]?.includes(key);
    }
}
```

### CSS للأزرار

```css
.movement-btn {
    width: 80px;
    height: 80px;
    border: none;
    border-radius: 50%;
    background: linear-gradient(145deg, #2a2a2a, #1a1a1a);
    color: #fff;
    font-size: 24px;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
    touch-action: manipulation;  /* منع التضخيم */
    transition: all 0.1s ease;
    box-shadow: 0 4px 15px rgba(0,0,0,0.3);
}

.movement-btn.active {
    background: linear-gradient(145deg, #00b894, #00a381);
    transform: scale(0.95);
    box-shadow: 0 2px 8px rgba(0,184,148,0.5);
}

/* منع context menu على الموبايل */
.movement-btn {
    -webkit-touch-callout: none;
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
}

/* تأثير اهتزاز خفيف عند الضغط */
@keyframes vibrate {
    0% { transform: scale(1); }
    50% { transform: scale(0.95); }
    100% { transform: scale(1); }
}
```

## HTML لأزرار الحركة

```html
<div class="movement-controls">
    <div class="movement-grid">
        <!-- صف أول: زر أمام -->
        <div class="grid-cell"></div>
        <div class="grid-cell">
            <button id="btn-forward" class="movement-btn" data-command="F">
                ▲
            </button>
        </div>
        <div class="grid-cell"></div>
        
        <!-- صف ثاني: يسار، توقف، يمين -->
        <div class="grid-cell">
            <button id="btn-left" class="movement-btn" data-command="L">
                ◄
            </button>
        </div>
        <div class="grid-cell">
            <button id="btn-stop" class="movement-btn stop-btn" data-command="S">
                ⬛
            </button>
        </div>
        <div class="grid-cell">
            <button id="btn-right" class="movement-btn" data-command="R">
                ►
            </button>
        </div>
        
        <!-- صف ثالث: زر خلف -->
        <div class="grid-cell"></div>
        <div class="grid-cell">
            <button id="btn-backward" class="movement-btn" data-command="B">
                ▼
            </button>
        </div>
        <div class="grid-cell"></div>
    </div>
</div>
```

## قسم التحكم بالسرعة

### تصميم الـ Sliders

```html
<div class="speed-controls">
    <!-- سرعة عامة -->
    <div class="speed-row">
        <label>🚀 السرعة العامة</label>
        <div class="slider-container">
            <input type="range" id="global-speed" min="0" max="255" value="200"
                   class="speed-slider">
            <span id="global-speed-value">200</span>
        </div>
    </div>
    
    <!-- سرعة المحرك 1 -->
    <div class="speed-row">
        <label>🔄 محرك 1 (M1)</label>
        <div class="slider-container">
            <input type="range" id="motor1-speed" min="0" max="255" value="200"
                   class="speed-slider">
            <span id="motor1-speed-value">200</span>
        </div>
    </div>
    
    <!-- سرعة المحرك 2 -->
    <div class="speed-row">
        <label>🔄 محرك 2 (M2)</label>
        <div class="slider-container">
            <input type="range" id="motor2-speed" min="0" max="255" value="200"
                   class="speed-slider">
            <span id="motor2-speed-value">200</span>
        </div>
    </div>
    
    <!-- ربط المحركين معاً -->
    <div class="link-motors">
        <label>
            <input type="checkbox" id="link-motors" checked>
            🔗 ربط المحركين معاً
        </label>
    </div>
</div>
```

### JavaScript للـ Sliders

```javascript
// سرعة عامة تغيّر كلا المحركين
document.getElementById('global-speed').addEventListener('input', (e) => {
    const speed = parseInt(e.target.value);
    document.getElementById('global-speed-value').textContent = speed;
    currentSpeed = speed;
    
    if (document.getElementById('link-motors').checked) {
        document.getElementById('motor1-speed').value = speed;
        document.getElementById('motor2-speed').value = speed;
        document.getElementById('motor1-speed-value').textContent = speed;
        document.getElementById('motor2-speed-value').textContent = speed;
    }
    
    // إرسال فوري عبر WebSocket
    socket.emit('motor_speed', {
        M1: parseInt(document.getElementById('motor1-speed').value),
        M2: parseInt(document.getElementById('motor2-speed').value)
    });
});
```

## تصميم متجاوب (Responsive)

### على الموبايل (< 768px):
```css
@media (max-width: 768px) {
    .camera-feed {
        width: 100%;
        height: auto;
        max-height: 40vh;
    }
    
    .movement-btn {
        width: 70px;
        height: 70px;
    }
    
    .speed-controls {
        padding: 10px;
    }
}
```

### على الكمبيوتر (> 768px):
```css
@media (min-width: 769px) {
    .camera-feed {
        max-width: 640px;
        margin: 0 auto;
    }
    
    .movement-btn {
        width: 90px;
        height: 90px;
    }
}
```

## اختصارات لوحة المفاتيح

| المفتاح | الأمر |
|---------|-------|
| `W` أو `↑` | أمام (F) |
| `S` أو `↓` | خلف (B) |
| `A` أو `←` | يسار (L) |
| `D` أو `→` | يمين (R) |
| `Space` | توقف طوارئ |
| `+` | زيادة السرعة |
| `-` | تقليل السرعة |
| `C` | التقاط صورة |
| `P` | إيقاف/تشغيل الكاميرا |

## معالجة حالة فقدان الاتصال

```javascript
socket.on('disconnect', () => {
    // عرض رسالة "غير متصل"
    showNotification('⚠️ فقدان الاتصال بالسيرفر', 'error');
    
    // تعطيل أزرار التحكم
    document.querySelectorAll('.movement-btn').forEach(btn => {
        btn.disabled = true;
    });
    
    // محاولة إعادة الاتصال
    socket.connect();
});

socket.on('connect', () => {
    showNotification('✅ تم الاتصال', 'success');
    
    // تفعيل أزرار التحكم
    document.querySelectorAll('.movement-btn').forEach(btn => {
        btn.disabled = false;
    });
});
```

## ألوان وتصميم
- خلفية داكنة (`#0a0a0a`)
- أزرار بلون رمادي غامق
- عند الضغط: أخضر مائل (`#00b894`)
- زر التوقف: أحمر (`#e74c3c`)
- Sliders بلون أزرق (`#0984e3`)
