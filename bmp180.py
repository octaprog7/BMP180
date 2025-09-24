# micropython
# MIT license
# Copyright (c) 2022 Roman Shevchik   goctaprog@gmail.com
import micropython
from micropython import const
import array

from sensor_pack_2 import bus_service
from sensor_pack_2.base_sensor import IBaseSensorEx, Iterator, IDentifier, DeviceEx, check_value

# ВНИМАНИЕ: не подключайте питание датчика к 5В, иначе датчик выйдет из строя! Только 3.3В!!!
# WARNING: do not connect "+" to 5V or the sensor will be damaged!


def _calibration_regs_addr() -> iter:
    """возвращает итератор с адресами внутренних регистров датчика, хранящих калибровочные коэффициенты."""
    return range(0xAA, 0xBF, 2)


class Bmp180(IBaseSensorEx, IDentifier, Iterator):
    """Класс для работы с датчиком давления воздуха Bosch BMP180"""

    # Регистры BMP180
    REG_ID = const(0xD0)
    REG_SOFT_RESET = const(0xE0)
    REG_CTRL = const(0xF4)
    REG_OUT_MSB = const(0xF6)


    def __init__(self, adapter: bus_service.I2cAdapter, address: int = 0x77, oss=0b11):
        """i2c - объект класса I2C; oss (oversample_settings) (0..3) - точность измерения 0-грубо, но быстро,
        3-медленно, но точно; address - адрес датчика на шине."""
        self._connection = DeviceEx(adapter=adapter, address=address, big_byte_order=True)
        #
        self._temp_or_press = True
        self._press4 = None  # for precalculate
        self._press3 = None  # for precalculate
        self._press2 = None  # for precalculate
        self._press1 = None  # for precalculate
        self._press0 = None  # for precalculate
        self._tmp1 = None    # for precalculate
        self._tmp0 = None    # for precalculate
        self._B5 = None      # for precalculate
        #
        self._oversample = None
        self.set_oversample(oss)
        # массив, хранящий калибровочные коэффициенты (11 штук)
        # array storing calibration coefficients (11 elements)
        self._cfa = array.array("l")  # signed long elements
        # считываю калибровочные коэффициенты
        self._read_calibration_data()
        # предварительный расчет
        self._precalculate()

    @micropython.native
    def get_calibration_data(self, index: int) -> int:
        """возвращает калибровочный коэффициент по его индексу (0..10).
        returns the calibration coefficient by its index (0..10)"""
        check_value(index, range(11), f"Invalid index value: {index}")
        return self._cfa[index]

    @micropython.native
    def _precalculate(self):
        """предварительно вычисленные значения. precomputed values"""
        # для расчета температуры/for temperature calculation
        self._tmp0 = self.get_calibration_data(4) / 2 ** 15  #
        self._tmp1 = self.get_calibration_data(9) * 2 ** 11  #
        # для расчета давления/for pressure calculation
        self._press0 = self.get_calibration_data(7) / 2 ** 23
        self._press1 = self.get_calibration_data(1) / 2 ** 11
        self._press2 = self.get_calibration_data(2) / 2 ** 13
        self._press3 = self.get_calibration_data(6) / 2 ** 28
        self._press4 = abs(self.get_calibration_data(3)) / 2 ** 15

    def _read_calibration_data(self) -> int:
        """Читает калибровочные значение из датчика.
        read calibration values from sensor. return count read values"""
        if len(self._cfa):
            raise ValueError(f"calibration data array already filled!")
        conn = self._connection
        for index, addr in enumerate(_calibration_regs_addr()):
            reg_val = conn.read_reg(addr, 2)
            rv = conn.unpack("H" if 2 < index < 6 else "h", reg_val)[0]
            # check
            if rv == 0x00 or rv == 0xFFFF:
                raise ValueError(f"Invalid register addr: {addr} value: {hex(rv)}")
            self._cfa.append(rv)
        return len(self._cfa)

    def get_id(self) -> int:
        """Возвращает идентификатор датчика. Правильное значение - 0х55.
        Returns the ID of the sensor. The correct value is 0x55."""
        conn = self._connection
        res = conn.read_reg(Bmp180.REG_ID, 1)
        return int(res[0])

    def soft_reset(self):
        """программный сброс датчика.
        software reset of the sensor"""
        conn = self._connection
        conn.write_reg(Bmp180.REG_SOFT_RESET, 0xB6, 1)

    @micropython.native
    def start_measurement(self, measure_temperature: bool = True):
        """Запускает процесс измерения температуры или давления датчиком.
        Если measure_temperature==Истина тогда будет выполнен запуск измерения температуры иначе давления!
        Вы должны подождать результата 5 мс после запуска измерения температуры.
        Время ожидания результата после запуска измерения давления зависит от значения, возвращаемого методом get_oversample()
        oversample      задержка, мс
        0               5
        1               8
        2               14
        3               26"""
        loc_oss = self.get_oversample()
        start_conversion = 0b0010_0000   # bit 5 - запуск преобразования (1)
        bit_4_0 = 0x14  # давление
        if measure_temperature:
            bit_4_0 = 0x0E  # температура
            loc_oss = 0  # обнуляю OSS при температуре
        val = loc_oss << 6 | start_conversion | bit_4_0
        self._connection.write_reg(Bmp180.REG_CTRL, val, 1)
        self.set_temperature_measurement(measure_temperature)

    def _get_temp_raw(self) -> int:
        """Возвращает сырое значение температуры."""
        # считывание сырого значения
        conn = self._connection
        raw = conn.read_reg(Bmp180.REG_OUT_MSB, 2)
        return conn.unpack("H", raw)[0]  # unsigned short

    @micropython.native
    def get_temperature(self) -> float:
        """возвращает значение температуры, измеренное датчиком в Цельсиях.
        returns the temperature value measured by the sensor in Celsius"""
        raw_t = self._get_temp_raw()
        a = self._tmp0 * (raw_t - self.get_calibration_data(5))
        b = self._tmp1 / (a + self.get_calibration_data(10))
        self._B5 = a + b  #
        return 6.25E-3 * (a + b + 8)

    def _get_press_raw(self) -> int:
        """Возвращает сырое значение атмосферного давления."""
        # считывание сырого значения (три байта)
        raw = self._connection.read_reg(Bmp180.REG_OUT_MSB, 3)
        msb, lsb, xlsb = raw
        oss = self.get_oversample()
        return ((msb << 16) + (lsb << 8) + xlsb) >> (8 - oss)

    @micropython.native
    def get_pressure(self) -> float:
        """возвращает значение давления, измеренное датчиком в Паскалях (Pa).
        До вызова этого метода нужно вызвать хотя-бы один раз метод get_temperature.
        Лучше вызывайте метод парами:
        get_temperature
        get_pressure"""
        if self._B5 is None:
            raise RuntimeError("Call get_temperature() before get_pressure()")
        #
        oss = self.get_oversample()
        uncompensated = self._get_press_raw()
        b6 = self._B5-4000
        x1 = self._press0 * b6 ** 2  #
        x2 = self._press1 * b6
        x3 = x1 + x2
        b3 = (2 + ((x3 + 4 * self.get_calibration_data(0)) * 2**oss)) / 4

        x1 = b6 * self._press2
        x2 = self._press3 * b6 ** 2
        x3 = (2+x1+x2) / 4

        b4 = self._press4 * (x3+32768)
        b7 = (abs(uncompensated)-b3) * (50000 / 2**oss)

        curr_pressure = 2 * b7 / b4
        x1 = 7.073394953E-7 * curr_pressure ** 2
        x2 = -0.1122589111328125 * curr_pressure

        return curr_pressure + 6.25E-2 * (x1 + x2 + 3791)

    """Call start_measurement(...) before call __next__ !!!"""
    def __next__(self) -> float:
        """Для поддержки итераций. Возврат текущей температуры или давления"""
        if not self.get_data_status(False):
            return None # данные не готовы!
        if self.is_temperature_measurement():
            return self.get_temperature()
        return self.get_pressure()

    def set_temperature_measurement(self, value: bool):
        """Если value Истина, тогда после вызова start_measurement, будет выполнен запуск измерения температуры иначе давления!"""
        self._temp_or_press = value

    def is_temperature_measurement(self) -> bool:
        """Если возвращает Истина, тогда после вызова start_measurement, будет выполнен запуск измерения температуры иначе давления!"""
        return self._temp_or_press

    def get_oversample(self) -> int:
        """Возвращает коэффициент избыточной (oversampling ratio) выборки измерения давления (0: однократный, 1: 2 раза, 2: 4 раза, 3: 8 раз)."""
        return self._oversample

    def set_oversample(self, value: int):
        """Устанавливает коэффициент избыточной (oversampling ratio) выборки измерения давления (0: однократный, 1: 2 раза, 2: 4 раза, 3: 8 раз)."""
        self._oversample = check_value(value, range(4), f"Invalid oversample settings: {value}")

    def get_conversion_cycle_time(self) -> int:
        """Возвращает время в мс преобразования сигнала в цифровой код и готовности его для чтения по шине!
        Для текущих настроек датчика. При изменении настроек следует заново вызвать этот метод!"""
        delays_ms = 5, 8, 14, 26
        if self.is_temperature_measurement():
            return delays_ms[0]    # temperature
        # pressure
        return delays_ms[self.get_oversample()]

    def get_measurement_value(self, value_index: int) -> float:
        """Возвращает измеренное датчиком значение(значения) по его индексу/номеру.
        0 - температура воздуха;
        1 - атмосферное давление воздуха;"""
        if 0 == value_index:
            return self.get_temperature()
        if 1 == value_index:
            return self.get_pressure()
        return None

    def is_single_shot_mode(self) -> bool:
        """Возвращает Истина, когда датчик находится в режиме однократных измерений,
        каждое из которых запускается методом start_measurement"""
        return True

    def is_continuously_mode(self) -> bool:
        """Возвращает Истина, когда датчик находится в режиме многократных измерений,
        производимых автоматически. Процесс запускается методом start_measurement"""
        return False

    def get_data_status(self, raw: bool = True):
        """Возвращает состояние готовности данных для считывания?
        Тип возвращаемого значения выбирайте сами!
        Если raw Истина, то возвращается сырое/не обработанное значение состояния!
        Для определения готовности данных температуры или давления у датчика BMP180 нужно читать
        бит SCO (Start of Conversion) в регистре управления измерениями _REG_CTRL.
        Пока бит SCO равен 1 — преобразование в процессе.
        Когда SCO в 0 — преобразование завершено, данные готовы для чтения из регистров результата."""
        raw_val = self._connection.read_reg(Bmp180.REG_CTRL, 1)[0]
        if raw:
            return raw_val
        return 0 == (raw_val & 0b10_0000)