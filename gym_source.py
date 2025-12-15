import cv2
import numpy as np
import time
import pyautogui
import mss
import keyboard
import threading
import tkinter as tk
from tkinter import Label, font
import os
import sys

# --- Скрытие консоли ---
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32')
    user32 = ctypes.WinDLL('user32')
    
    # Найти консольное окно
    hWnd = kernel32.GetConsoleWindow()
    if hWnd:
        user32.ShowWindow(hWnd, 0)  # 0 = SW_HIDE

# --- КОНФИГУРАЦИЯ ---

# Область для захвата кругов
ROI_X = 660 
ROI_Y = 300
ROI_W = 600
ROI_H = 500

# Область для плашки окончания подхода
END_REGION = (650, 1015, 620, 39)  # x, y, width, height
END_THRESHOLD = 0.75  # Порог совпадения с шаблоном (75%)
END_STABLE_TIME = 0.7  # Время стабильного отображения плашки (сек)

# Время отдыха
REST_TIME = 30

# Параметры для кругов
MIN_GAP = 8
MAX_GAP = 25
PRESS_COOLDOWN = 0.25

# Цветовые диапазоны (HSV)
WHITE_LOWER = np.array([0, 0, 180])
WHITE_UPPER = np.array([180, 70, 255])
GREEN_LOWER = np.array([25, 40, 40])
GREEN_UPPER = np.array([95, 255, 255])

# Минимальные радиусы
MIN_WHITE_RADIUS = 15
MIN_GREEN_RADIUS = 30

# Глобальные флаги
is_running = False
is_paused = True
current_status = "ОЖИДАНИЕ"
last_space_time = 0

# --- УНИВЕРСАЛЬНАЯ ФУНКЦИЯ ЗАГРУЗКИ ИЗОБРАЖЕНИЙ ---
def load_image_any_path(path, grayscale=True):
    """
    Универсальная функция загрузки изображений, работающая с любыми путями
    """
    try:
        # Способ 1: Чтение как двоичного файла с последующим декодированием
        with open(path, 'rb') as f:
            img_bytes = bytearray(f.read())
        
        # Преобразуем байты в numpy массив
        nparr = np.frombuffer(img_bytes, np.uint8)
        
        # Декодируем изображение
        if grayscale:
            img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        else:
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
        return img
    except Exception as e:
        return None

# --- ЗАГРУЗКА ШАБЛОНА ПЛАШКИ ---
def load_end_template():
    """Загружает шаблон плашки окончания подхода"""
    # Получаем путь к скрипту
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Пробуем разные варианты имени файла
    possible_names = [
        "end_approach.png",
        "end_approach.jpg",
        "end_approach.jpeg",
        "END_APPROACH.PNG",
        "END_APPROACH.JPG"
    ]
    
    for filename in possible_names:
        template_path = os.path.join(script_dir, filename)
        if os.path.exists(template_path):
            template = load_image_any_path(template_path, grayscale=True)
            if template is not None:
                return template, True
    
    return None, False

# Загружаем шаблон
END_TEMPLATE, TEMPLATE_LOADED = load_end_template()

# --- OVERLAY GUI ---
class OverlayGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Качалка")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.geometry("+10+10")
        self.root.configure(bg='#0a0a0a')
        
        # Создаем полупрозрачный фон
        self.root.wm_attributes("-alpha", 0.9)
        
        # Главный фрейм
        main_frame = tk.Frame(self.root, bg='#0a0a0a', padx=15, pady=10)
        main_frame.pack()
        
        # Заголовок
        title_label = tk.Label(main_frame, text="Качалка", 
                              font=("Segoe UI", 11, "bold"),
                              fg="#00ff00", bg='#0a0a0a')
        title_label.pack()
        
        # Статус
        self.status_label = tk.Label(main_frame, text=current_status,
                                    font=("Segoe UI", 10),
                                    fg="white", bg='#0a0a0a')
        self.status_label.pack(pady=(5, 0))
        
        # Клавиши управления
        keys_frame = tk.Frame(main_frame, bg='#0a0a0a')
        keys_frame.pack(pady=(8, 0))
        
        # Динамическое отображение клавиш управления
        self.keys_label = tk.Label(keys_frame, 
                                  text=self.get_keys_text(),
                                  font=("Segoe UI", 9),
                                  fg="#aaaaaa", bg='#0a0a0a')
        self.keys_label.pack()
        
        # Линия разделитель
        separator = tk.Frame(main_frame, height=1, width=150, bg='#333333')
        separator.pack(pady=(8, 0))
        
        self.update_label()
        self.root.mainloop()
    
    def get_keys_text(self):
        if not is_running or is_paused:
            return "F7 - Запуск"
        else:
            return "F8 - Пауза | F9 - Выход"
    
    def update_label(self):
        global current_status
        
        # Обновляем статус
        if "РАБОТАЕТ" in current_status: 
            color = "#00FF00"
        elif "ПАУЗА" in current_status: 
            color = "#FFFF00"
        elif "ОТДЫХ" in current_status: 
            color = "#00FFFF"
        elif "НАЖИМАЮ" in current_status:
            color = "#FF9900"
        else: 
            color = "#FFFFFF"
        
        self.status_label.config(text=current_status, fg=color)
        
        # Обновляем клавиши управления
        self.keys_label.config(text=self.get_keys_text())
        
        self.root.after(200, self.update_label)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def press_e():
    """Нажимает клавишу E"""
    keyboard.press('e')
    time.sleep(0.05)
    keyboard.release('e')

def get_radii(img_hsv):
    """Определяет радиусы белого и зеленого кругов"""
    mask_white = cv2.inRange(img_hsv, WHITE_LOWER, WHITE_UPPER)
    contours_w, _ = cv2.findContours(mask_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask_green = cv2.inRange(img_hsv, GREEN_LOWER, GREEN_UPPER)
    contours_g, _ = cv2.findContours(mask_green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    r_white = 0
    r_green = 0
    
    for cnt in contours_w:
        area = cv2.contourArea(cnt)
        if area > 50:  # Фильтр шума
            ((x, y), radius) = cv2.minEnclosingCircle(cnt)
            if radius > r_white: 
                r_white = radius
            
    for cnt in contours_g:
        area = cv2.contourArea(cnt)
        if area > 100:  # Фильтр шума
            ((x, y), radius) = cv2.minEnclosingCircle(cnt)
            if radius > r_green: 
                r_green = radius
            
    return r_green, r_white

def can_press_space(r_green, r_white, current_time):
    """Проверяет все условия для нажатия Space"""
    global last_space_time
    
    # 1. Проверка КД
    if current_time - last_space_time < PRESS_COOLDOWN:
        return False
    
    # 2. Минимальные размеры кругов
    if r_white < MIN_WHITE_RADIUS or r_green < MIN_GREEN_RADIUS:
        return False
    
    # 3. Белый должен быть внутри зеленого
    if r_white >= r_green:
        return False
    
    # 4. Проверка разницы радиусов
    diff = r_green - r_white
    if not (MIN_GAP <= diff <= MAX_GAP):
        return False
    
    # Все условия выполнены
    last_space_time = current_time
    return True

def check_end_approach(img_gray):
    """Проверяет наличие плашки окончания подхода по шаблону"""
    if END_TEMPLATE is None:
        return False, 0.0
    
    # Проверяем размеры
    if END_TEMPLATE.shape[0] > img_gray.shape[0] or END_TEMPLATE.shape[1] > img_gray.shape[1]:
        return False, 0.0
    
    # Сравниваем шаблон
    res = cv2.matchTemplate(img_gray, END_TEMPLATE, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    
    return max_val >= END_THRESHOLD, max_val

def smart_sleep(seconds):
    """Умный сон с проверкой паузы/остановки"""
    global is_paused, is_running
    for _ in range(int(seconds * 10)):
        if not is_running or is_paused: 
            return False
        time.sleep(0.1)
    return True

# --- ОСНОВНАЯ ЛОГИКА БОТА ---
def bot_logic():
    global current_status, is_paused, is_running, last_space_time
    
    # Области захвата
    monitor_roi = {"top": ROI_Y, "left": ROI_X, "width": ROI_W, "height": ROI_H}
    monitor_end = {"top": END_REGION[1], "left": END_REGION[0], 
                   "width": END_REGION[2], "height": END_REGION[3]}
    
    with mss.mss() as sct:
        while True:
            if not is_running: 
                break
            
            if is_paused:
                current_status = "ПАУЗА (F7 - Продолжить)"
                time.sleep(0.1)
                continue

            # Сбрасываем время последнего нажатия Space
            last_space_time = 0
            
            # Нажимаем E для начала подхода
            current_status = "НАЖИМАЮ E..."
            press_e()
            
            # Короткая пауза для стабильности
            time.sleep(0.1)
            
            current_status = "РАБОТАЕТ: КАЧАЮСЬ"
            
            # Переменные для детекта окончания
            end_detected_since = None
            end_not_detected_count = 0
            
            # Основной цикл подхода
            while not is_paused and is_running:
                # Захватываем область с кругами
                img_roi = np.array(sct.grab(monitor_roi))
                img_bgr_roi = cv2.cvtColor(img_roi, cv2.COLOR_BGRA2BGR)
                img_hsv_roi = cv2.cvtColor(img_bgr_roi, cv2.COLOR_BGR2HSV)
                
                # Определяем радиусы кругов
                r_green, r_white = get_radii(img_hsv_roi)
                
                # Проверяем условия для нажатия Space
                current_time = time.time()
                if can_press_space(r_green, r_white, current_time):
                    pyautogui.press('space')
                    time.sleep(0.05)
                
                # Периодически проверяем плашку окончания (не каждый кадр для оптимизации)
                if end_not_detected_count % 3 == 0:  # Проверяем каждые 3 кадра (~0.06 сек)
                    # Захватываем область плашки
                    img_end = np.array(sct.grab(monitor_end))
                    img_gray_end = cv2.cvtColor(img_end[:, :, :3], cv2.COLOR_BGR2GRAY)
                    
                    # Проверяем плашку
                    end_found, accuracy = check_end_approach(img_gray_end)
                    
                    if end_found:
                        if end_detected_since is None:
                            end_detected_since = time.time()
                        elif time.time() - end_detected_since >= END_STABLE_TIME:
                            # Плашка стабильно видна - подход закончен
                            current_status = "ПОДХОД ЗАВЕРШЕН"
                            time.sleep(0.2)
                            break
                        end_not_detected_count = 0
                    else:
                        end_detected_since = None
                        end_not_detected_count += 1
                else:
                    end_not_detected_count += 1
                
                time.sleep(0.02)
            
            if is_paused: 
                continue
            
            # Отдых
            for i in range(REST_TIME, 0, -1):
                current_status = f"ОТДЫХ: {i} СЕК"
                if not smart_sleep(1): 
                    break

# --- СЛУШАТЕЛЬ КЛАВИШ ---
def key_listener():
    global is_running, is_paused, current_status
    while True:
        if keyboard.is_pressed('f7'):
            if not is_running:
                is_running = True
                is_paused = False
                t = threading.Thread(target=bot_logic)
                t.daemon = True
                t.start()
            else:
                is_paused = False
            time.sleep(0.3)
            
        if keyboard.is_pressed('f8'):
            is_paused = True
            current_status = "ПАУЗА (F7 - Продолжить)"
            time.sleep(0.3)
            
        if keyboard.is_pressed('f9'):
            is_running = False
            is_paused = True
            current_status = "ВЫХОД..."
            time.sleep(1)
            os._exit(0)
        
        time.sleep(0.05)

# --- ЗАПУСК ПРОГРАММЫ ---
if __name__ == "__main__":
    # Скрытие консоли
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32')
        user32 = ctypes.WinDLL('user32')
        hWnd = kernel32.GetConsoleWindow()
        if hWnd:
            user32.ShowWindow(hWnd, 0)
    
    # Запускаем поток слушателя клавиш
    tk_thread = threading.Thread(target=key_listener)
    tk_thread.daemon = True
    tk_thread.start()
    
    # Запускаем overlay GUI
    gui = OverlayGUI()