# micropython

# ВНИМАНИЕ: не подключайте питание датчика к 5В, иначе датчик выйдет из строя! Только 3.3В!!!
# WARNING: do not connect "+" to 5V or the sensor will be damaged!
from machine import I2C
import bmp180
import time
from sensor_pack_2.bus_service import I2cAdapter

# преобразование и фильтрация давления
def pa_to_unit(value_pa: float, unit: str = 'hpa') -> float:
    """Преобразует давление из Па в нужную единицу."""
    if unit == 'hpa':
        return value_pa * 0.01
    if unit == 'mmhg':
        return value_pa * 0.00750061561303
    if unit == 'psi':
        return value_pa * 0.00014503773773
    if unit == 'atm':
        return value_pa * 9.86923266716e-06
    return value_pa  # 'pa' или неизвестная единица


def smooth_ema(new_val: float, prev_ema: float | None, alpha: float = 0.25) -> float:
    """Экспоненциальное скользящее среднее (EMA).
    alpha: 0.1..0.3 — плавное сглаживание, 0.4..0.6 — быстрый отклик."""
    if prev_ema is None:
        return new_val
    # Ограничение alpha
    if alpha < 0.0:
        alpha = 0.0
    elif alpha > 1.0:
        alpha = 1.0
    return alpha * new_val + (1.0 - alpha) * prev_ema


def smooth_ma(window_vals: list, window: int = 4) -> float:
    """Простое скользящее среднее по последним `window` значениям."""
    if not window_vals:
        return 0.0
    # срез без создания лишнего списка, если в окне больше данных
    if len(window_vals) <= window:
        return sum(window_vals) / len(window_vals)
    # суммирование последних `window` элементов
    total, count = 0, 0
    for i in range(len(window_vals) - window, len(window_vals)):
        total += window_vals[i]
        count += 1
    return total / count


def format_press(value_pa: float, unit: str = 'hpa', decimals: int = 2) -> str:
    """Форматирует давление для вывода: '1013.25 гПа'. Без словарей."""
    # Получаем конвертированное значение
    val = pa_to_unit(value_pa, unit)
    # Выбор метки через if/elif
    if unit == 'pa':
        label = 'Па'
    elif unit == 'hpa':
        label = 'гПа'
    elif unit == 'mmhg':
        label = 'мм рт. ст.'
    elif unit == 'psi':
        label = 'PSI'
    elif unit == 'atm':
        label = 'атм'
    else:
        label = 'Па'  # по умолчанию
    return f"{val:.{decimals}f} {label}"

# Для погодной станции (точность важнее скорости):
USE_FILTER = not True
FILTER_METHOD = 'ema'
EMA_ALPHA = 0.15    # очень плавная кривая
MA_WINDOW = 4       # размер окна для MA. MA = Moving Average (простое скользящее среднее).

# Для высотомера (минимум задержки):
# USE_FILTER = True
# FILTER_METHOD = 'ema'
# EMA_ALPHA = 0.4   # быстрый отклик

# Для отладки (видеть "сырые" данные):
# USE_FILTER = False

# --- состояние фильтра ---
ema_state = None
ema_history = []


if __name__ == '__main__':
    # пожалуйста установите выводы scl и sda в конструкторе для вашей платы, иначе ничего не заработает!
    # please set scl and sda pins for your board, otherwise nothing will work!
    # https://docs.micropython.org/en/latest/library/machine.I2C.html#machine-i2c
    # i2c = I2C(0, scl=Pin(13), sda=Pin(12), freq=400_000) # для примера
    # bus =  I2C(scl=Pin(4), sda=Pin(5), freq=100000)   # на esp8266    !
    # Внимание!!!
    # Замените id=1 на id=0, если пользуетесь первым портом I2C !!!
    # Warning!!!
    # Replace id=1 with id=0 if you are using the first I2C port !!!
    adaptor = I2cAdapter(I2C(1, freq=400_000))
    # ps - pressure sensor
    ps = bmp180.Bmp180(adaptor)

    # если у вас посыпались исключения EIO, то проверьте все соединения.
    # if you have EIO exceptions, then check all connections.
    res = ps.get_id()
    print(f"chip_id: 0x{res:x}")

    print("Calibration data:")
    print([ps.get_calibration(i) for i in range(11)])

    print(20 * "*_")
    print("Reading temperature in a cycle.")
    for i in range(333):
        ps.start_measurement(measure_temperature=True)  # switch to temperature
        delay = ps.get_conversion_cycle_time()
        time.sleep_ms(delay)    # delay for temperature measurement
        print(f"Air temperature: {ps.get_temperature()} \xB0 С\tDelay: {delay} [ms]")

    ps.start_measurement(measure_temperature=False)     # switch to pressure
    delay = ps.get_conversion_cycle_time()
    time.sleep_ms(delay)  # delay for pressure measurement

    min_press, max_press, average_press = 1E6, 0.0, 0.0
    _unit = 'mmhg'
    print(20 * "*_")
    print("Reading pressure using an iterator!")
    for index, press in enumerate(ps):
        if press is None:
            continue

        press_filtered = press
        # фильтрация старт
        if USE_FILTER:
            if FILTER_METHOD == 'ema':
                press_filtered = smooth_ema(press, ema_state, EMA_ALPHA)
                ema_state = press_filtered  # сохраняем состояние для следующего шага
            else:  # 'ma'
                ema_history.append(press)
                press_filtered = smooth_ma(ema_history, MA_WINDOW)
                if len(ema_history) > 16:  # ограничиваем рост памяти
                    ema_history.pop(0)
        # фильтрация стоп

        # Обновляем мин/макс по фильтрованному значению
        min_press = min(press_filtered, min_press)
        max_press = max(press_filtered, max_press)

        # Вывод: сырое и фильтрованное + конвертация
        mmhg_raw = pa_to_unit(value_pa=press_filtered, unit=_unit)
        mmhg_filt = pa_to_unit(value_pa=press_filtered, unit=_unit)

        if USE_FILTER:
            print(f"P: {press:.1f} Pa → {press_filtered:.1f} Pa | {mmhg_filt:.3f} mmHg | min/max: {min_press:.1f}/{max_press:.1f} Pa")
        else:
            print(f"Air pressure: {press:.1f} Pa | {mmhg_raw:.3f} mmHg | min/max: {min_press:.1f}/{max_press:.1f} Pa")

        time.sleep_ms(delay)  # delay for pressure measurement
        ps.start_measurement(measure_temperature=False)

