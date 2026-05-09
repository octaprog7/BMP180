# micropython
# mail: goctaprog@gmail.com
# MIT license
#
# Universal main.py for pressure sensors:
# BMP180, BMP280, BMP390, BMP581, LPS22CH
# Auto-detection by chip_id, unified measurement interface.
#

import time
from machine import I2C, Pin
from micropython import const
from sensor_pack_2.bus_service import I2cAdapter
from sensor_pack_2.bmp_common import (
    IBaseAirPresSensor, OversamplingCoeff, MeasChannels,
    MeasuredParams, SensorID
)

# Import drivers safely
try:
    import bmp180
except ImportError:
    bmp180 = None
try:
    import bmp280mod as bmp280
except ImportError:
    bmp280 = None
try:
    import bmp390mod as bmp390
except ImportError:
    bmp390 = None
try:
    import bmp581mod as bmp581
except ImportError:
    bmp581 = None
try:
    import lps22ch
except ImportError:
    lps22ch = None

# Configuration constants
I2C_ID: int = const(1)
SCL_PIN: int = const(7)
SDA_PIN: int = const(6)
I2C_FREQ: int = const(400_000)
ITERATIONS: int = const(50)

# Default addresses
ADDR_BMP180 = const(0x77)
ADDR_BMP280 = const(0x76)
ADDR_BMP390 = const(0x76)
ADDR_BMP581 = const(0x47)
ADDR_LPS22CH = const(0x5C)

# Chip IDs
CHIP_BMP180 = const(0x55)
CHIP_BMP280 = const(0x58)
CHIP_BMP390 = const(0x60)
CHIP_BMP581 = const(0x50)
CHIP_LPS22CH = const(0xB3)


def pa_to_unit(value_pa: float, unit: str = 'hpa') -> float:
    """Convert pressure from Pa to target unit."""
    if unit == 'hpa':
        return value_pa * 0.01
    if unit == 'mmhg':
        return value_pa * 0.00750061561303
    if unit == 'psi':
        return value_pa * 0.00014503773773
    if unit == 'atm':
        return value_pa * 9.86923266716e-06
    return value_pa


def smooth_ema(new_val: float, prev_ema: float | None, alpha: float = 0.25) -> float:
    """Exponential Moving Average (EMA)."""
    if prev_ema is None:
        return new_val
    alpha = max(0.0, min(1.0, alpha))
    return alpha * new_val + (1.0 - alpha) * prev_ema


def smooth_ma(window_vals: list, window: int = 4) -> float:
    """Simple Moving Average."""
    if not window_vals:
        return 0.0
    start = max(0, len(window_vals) - window)
    return sum(window_vals[start:]) / (len(window_vals) - start)


def format_press(value_pa: float, unit: str = 'hpa', decimals: int = 2) -> str:
    """Format pressure for output."""
    val = pa_to_unit(value_pa, unit)
    labels = {
        'pa': 'Pa', 'hpa': 'hPa', 'mmhg': 'mmHg',
        'psi': 'PSI', 'atm': 'atm'
    }
    return f"{val:.{decimals}f} {labels.get(unit, 'Pa')}"


# Filter settings
USE_FILTER = False
FILTER_METHOD = 'ema'
EMA_ALPHA = 0.15
MA_WINDOW = 4
OUTPUT_UNIT = 'mmhg'


def detect_sensor(bus: I2C, adapt: I2cAdapter) -> IBaseAirPresSensor | None:
    """
    Автоопределение датчика по chip_id.
    Формат: (Адрес, Регистр_ID, Ожидаемый_ID, Модуль, Имя, Класс)
    """
    # Обратите внимание: для BMP180 регистр ID это 0xD0, для BMP581 это 0x01
    candidates = (
        (0x47, 0x01, CHIP_BMP581, bmp581, 'BMP581', 'Bmp581'),
        (0x76, 0x00, CHIP_BMP390, bmp390, 'BMP390', 'Bmp390'),
        (0x77, 0x00, CHIP_BMP390, bmp390, 'BMP390', 'Bmp390'),
        (0x5C, 0x0F, CHIP_LPS22CH, lps22ch, 'LPS22CH', 'Lps22ch'),
        (0x76, 0xD0, CHIP_BMP280, bmp280, 'BMP280', 'Bmp280'),
        (0x77, 0xD0, CHIP_BMP180, bmp180, 'BMP180', 'Bmp180'),
    )

    for addr, id_reg, exp_id, mod, name, cls_name in candidates:
        if mod is None:
            continue
        try:
            chip_id = bus.readfrom_mem(addr, id_reg, 1)[0]
            if chip_id == exp_id:
                print(f"Найден {name} at 0x{addr:02X} (ID: 0x{chip_id:02X})")
                return getattr(mod, cls_name)(adapter=adapt, address=addr)
        except OSError:
            pass

    print("Датчик не найден! Проверьте соединения и адреса.")
    return None


def configure_sensor(sens: IBaseAirPresSensor, use_pressure: bool = True,
                     osr_temp: int = 2, osr_press: int = 4,
                     mode: int = 1, odr_index: int = 0x17) -> None:
    """
    Настраивает датчик через единый интерфейс.
    Автоматически снижает oversampling до допустимых пределов BMP180,
    сохраняя высокие значения для BMP280/390/581.
    """
    cls_name = sens.__class__.__name__

    # BMP180 имеет жёсткие аппаратные ограничения
    max_temp = 0 if cls_name == 'Bmp180' else 7
    max_press = 3 if cls_name == 'Bmp180' else 7

    osr_temp = min(osr_temp, max_temp)
    osr_press = min(osr_press, max_press)

    # Включаем каналы
    sens.set_channels(temp_en=True, press_en=use_pressure)

    # Настраиваем oversampling
    sens.set_oversampling(temp=osr_temp, press=osr_press if use_pressure else None)

    # Настраиваем IIR фильтр (если поддерживается)
    try:
        if hasattr(sens, 'set_iir_filter'):
            sens.set_iir_filter(temp=3, press=3 if use_pressure else None)
    except (TypeError, ValueError, OSError):
        pass

    # Настраиваем режим и ODR
    sens.set_power_mode(mode)
    try:
        sens.set_sampling_period(odr_index)
    except NotImplementedError:
        pass


def run_measurement_loop(sens, iterations=ITERATIONS, use_forced_mode=False):
    ema_state = None
    ma_history = []
    min_temp, max_temp = 100.0, -100.0
    min_press, max_press = 200000.0, 0.0

    cls_name = sens.__class__.__name__

    # 1. Определяем режим работы
    is_forced_only = (cls_name == 'Bmp180')
    requested_mode = 2 if (use_forced_mode or is_forced_only) else 1

    # 2. Применяем конфигурацию под конкретный датчик
    if is_forced_only:
        # BMP180: Forced mode, макс. точность
        sens.set_channels(temp_en=True, press_en=True)
        sens.set_oversampling(temp=0, press=3)
        sens.set_power_mode(requested_mode)
    elif cls_name == 'Bmp581':
        # BMP581: Индекс 15 = 10 Гц (Безопасно для OSR_P=2)
        sens.set_channels(temp_en=True, press_en=True)
        sens.set_oversampling(temp=1, press=2)
        sens.set_sampling_period(15)  # <- 15 (10 Гц)
        # разрешаю источник DRDY в INT_SOURCE (0x15)
        _str = 'init_hardware'
        if hasattr(sens, _str):
            print(f"Вызов {_str}")
            sens.init_hardware()
        sens.set_power_mode(requested_mode)
    else:
        # BMP280 / BMP390 / LPS22CH: Стандартные настройки
        sens.set_channels(temp_en=True, press_en=True)
        sens.set_oversampling(temp=2, press=4)
        sens.set_power_mode(requested_mode)
        sens.set_sampling_period(5)

    # 3. Заголовок
    mode_names = ("Режим ожидания", "Нормальный", "Принудительный", "Непрерывный")
    # Берем запрошенный режим для вывода, так как он точно известен
    mode_str = mode_names[requested_mode] if 0 <= requested_mode < len(mode_names) else f"Неизвестный({requested_mode})"
    sensor_name = cls_name[:3].upper() + cls_name[3:] if cls_name[:3] in ("Bmp", "Lps") else cls_name

    print(f"\nЗапуск измерений: {sensor_name}, режим={mode_str}")
    print("-" * 60)

    # 4. Запуск цикла
    if not is_forced_only and requested_mode == 1:
        sens.start_measurement()
        cycle_time = int(sens.get_conversion_cycle_time()) + 10
        print(f"Запущен непрерывный режим. ~{cycle_time} [мс] на измерение.")
    else:
        cycle_time = 0

    for i in range(iterations):
        if is_forced_only or requested_mode == 2:
            sens.start_measurement()
            cycle_time = int(sens.get_conversion_cycle_time()) + 5

        time.sleep_ms(cycle_time)

        if not sens.is_data_ready():
            print(f"Ожидание готовности данных...")
            continue

        temp = sens.get_temperature()
        press = sens.get_pressure()

        # Фильтрация
        if USE_FILTER and temp is not None:
            if FILTER_METHOD == 'ema':
                temp = smooth_ema(temp, ema_state, EMA_ALPHA)
                ema_state = temp
            else:
                ma_history.append(temp)
                temp = smooth_ma(ma_history, MA_WINDOW)
                if len(ma_history) > max(MA_WINDOW * 2, 32):
                    ma_history.pop(0)

        if USE_FILTER and press is not None:
            if FILTER_METHOD == 'ema':
                press = smooth_ema(press, ema_state, EMA_ALPHA)
                ema_state = press
            else:
                ma_history.append(press)
                press = smooth_ma(ma_history, MA_WINDOW)
                if len(ma_history) > max(MA_WINDOW * 2, 32):
                    ma_history.pop(0)

        # Статистика
        if temp is not None:
            min_temp = min(min_temp, temp)
            max_temp = max(max_temp, temp)
        if press is not None:
            min_press = min(min_press, press)
            max_press = max(max_press, press)

        temp_str = f"{temp:.2f} C" if temp is not None else "N/A"
        press_unit_str = format_press(press, OUTPUT_UNIT) if press is not None else "N/A"
        press_pa_str = f"{press:.0f} Pa" if press is not None else "N/A"

        print(
            f"T: {temp_str:8s} | P: {press_unit_str:12s} | {press_pa_str:10s} | min/max: {format_press(min_press, OUTPUT_UNIT)}/{format_press(max_press, OUTPUT_UNIT)}")

    print("\n" + "=" * 70)
    print(f"Статистика на {iterations} измерений:")
    print(f"   Температура: {min_temp:.2f} .. {max_temp:.2f} C")
    if min_press < 200000:
        print(f"   Давление:  {format_press(min_press, OUTPUT_UNIT)} .. {format_press(max_press, OUTPUT_UNIT)}")
        print(f"              {min_press:.0f} .. {max_press:.0f} Pa")
    print("=" * 70)


if __name__ == '__main__':
    print("Универсальная демонстрация датчика давления окруж. воздуха для MicroPython")
    print(f"   Выводы платы: SCL={SCL_PIN}, SDA={SDA_PIN}, I2C={I2C_ID}")
    print("-" * 60)

    try:
        i2c = I2C(id=I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
        adapter = I2cAdapter(i2c)
        print("Инициализация I2C завершена.")
    except Exception as e:
        print(f"Сбой инициализации I2C: {e}")
        print("\tПроверьте контакты и частоту обмена!")
        raise

    sensor = detect_sensor(i2c, adapter)
    if sensor is None:
        print("\nПодсказка: проверьте:")
        print("   - SDA/SCL соединения")
        print("   - Напряжение питания (1.8-3.6В, не 5В!)")
        print("   - Адрес датчика на шине")
        raise SystemExit(1)
    print("Выполнение программной перезагрузки...")
    sensor.soft_reset()
    time.sleep_ms(5)  # Подождите завершения сброса
    print("Перезагрузка выполнена!")
    if hasattr(sensor, 'refresh_config'):
        sensor.refresh_config()

    try:
        sensor_id = sensor.get_id()
        if isinstance(sensor_id, SensorID):
            rev = sensor_id.revision_id if sensor_id.revision_id is not None else 0
            print(f"   SensorID: chip=0x{sensor_id.chip_id:02X}, rev=0x{rev:02X}")
        else:
            print(f"   Chip ID: 0x{sensor_id:02X}")
    except (TypeError, ValueError, OSError):
        pass

    configure_sensor(
        sens=sensor,
        use_pressure=True,
        osr_temp=2,
        osr_press=4,
        mode=1,
        odr_index=5
    )

    try:
        run_measurement_loop(sensor, iterations=ITERATIONS, use_forced_mode=False)
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
    finally:
        try:
            sensor.set_power_mode(0)
            print("Датчик переведён в спящий режим.")
        except (TypeError, ValueError, OSError):
            pass

    print("\nКУ!")