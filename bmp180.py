# micropython
# MIT license
# Copyright (c) 2022 Roman Shevchik   goctaprog@gmail.com
import micropython
import array

from sensor_pack import bus_service
from sensor_pack.base_sensor import BaseSensor, Iterator, check_value


# ВНИМАНИЕ: не подключайте питание датчика к 5В, иначе датчик выйдет из строя! Только 3.3В!!!
# WARNING: do not connect "+" to 5V or the sensor will be damaged!


@micropython.native
def get_conversion_cycle_time(temperature_or_pressure: bool, oversample_settings: int) -> int:
    """возвращает время преобразования в [мс] датчиком температуры или давления в зависимости от его настроек.
    returns the conversion time in [ms] by a temperature or pressure sensor depending on its settings"""
    delays_ms = 5, 8, 14, 26
    if temperature_or_pressure:
        return delays_ms[0]    # temperature
    # pressure
    return delays_ms[oversample_settings]


def _calibration_regs_addr() -> iter:
    """возвращает итератор с адресами внутренних регистров датчика, хранящих калибровочные коэффициенты.
    returns an iterator with the addresses of the sensor's internal registers that
    store the calibration coefficients."""
    return range(0xAA, 0xBF, 2)


class Bmp180(BaseSensor, Iterator):
    """Class for work with Bosh BMP180 pressure sensor"""

    def __init__(self, adapter: bus_service.I2cAdapter, address: int = 0xEE >> 1, oversample_settings=0b11):
        """i2c - объект класса I2C; oversample_settings (0..3) - точность измерения 0-грубо но быстро,
        3-медленно, но точно; address - адрес датчика (0xEF (read) and 0xEE (write) from datasheet)

        i2c is an object of the I2C class; oversample_settings (0..3) - measurement
        reliability 0-coarse but fast, 3-slow but accurate;"""
        super().__init__(adapter, address, True)
        # self.adapter = adapter
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
        self.oversample = oversample_settings
        # массив, хранящий калибровочные коэффициенты (11 штук)
        # array storing calibration coefficients (11 elements)
        self._cfa = array.array("l")  # signed long elements
        # считываю калибровочные коэффициенты
        self._read_calibration_data()
        # предварительный расчет
        self.precalculate()

    def _write_register(self, reg_addr, value: int, bytes_count=2) -> int:
        """записывает данные value в датчик, по адресу reg_addr.
        bytes_count - кол-во записываемых данных"""
        byte_order = self._get_byteorder_as_str()[0]
        return self.adapter.write_register(self.address, reg_addr, value, bytes_count, byte_order)

    @micropython.native
    def get_calibration_data(self, index: int) -> int:
        """возвращает калибровочный коэффициент по его индексу (0..10).
        returns the calibration coefficient by its index (0..10)"""
        check_value(index, range(0, 11), f"Invalid index value: {index}")
        return self._cfa[index]

    @micropython.native
    def precalculate(self):
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
        for index, addr in enumerate(_calibration_regs_addr()):
            reg_val = self.adapter.read_register(self.address, addr, 2)
            rv = self.unpack("H" if 2 < index < 6 else "h", reg_val)[0]
            # check
            if rv == 0x00 or rv == 0xFFFF:
                raise ValueError(f"Invalid register addr: {addr} value: {hex(rv)}")
            self._cfa.append(rv)
        return len(self._cfa)

    def get_id(self) -> int:
        """Возвращает идентификатор датчика. Правильное значение - 0х55.
        Returns the ID of the sensor. The correct value is 0x55."""
        res = self.adapter.read_register(self.address, 0xD0, 1)
        return int(res[0])

    def soft_reset(self):
        """программный сброс датчика.
        software reset of the sensor"""
        self._write_register(0xE0, 0xB6, 1)

    @micropython.native
    def start_measurement(self, temperature_or_pressure: bool = True):
        """Start measurement process in sensor.
        Если temperature_or_pressure==Истина тогда будет выполнен запуск измерения температуры иначе давления!
        Вы должны подождать результата 5 мс после запуска измерения температуры.
        Время ожидания результата после запуска измерения давления зависит от переменной self._оss.
        self.оss     задержка, мс
        0               5
        1               8
        2               14
        3               26"""
        self._temp_or_press = temperature_or_pressure
        loc_oss = self.oversample
        start_conversion = 0b00100000   # bit 5 - запуск преобразования (1)
        bit_4_0 = 0x14  # давление
        if temperature_or_pressure:
            bit_4_0 = 0x0E  # температура
            loc_oss = 0  # обнуляю OSS при температуре
        val = loc_oss << 6 | start_conversion | bit_4_0
        self._write_register(0xF4, val, 1)

    @micropython.native
    def get_temperature(self) -> float:
        """возвращает значение температуры, измеренное датчиком в Цельсиях.
        returns the temperature value measured by the sensor in Celsius"""
        # считывание сырого значения
        raw = self.adapter.read_register(self.address, 0xF6, 2)
        temp = self.unpack("H", raw)[0]  # unsigned short
        a = self._tmp0 * (temp - self.get_calibration_data(5))
        b = self._tmp1 / (a + self.get_calibration_data(10))
        self._B5 = a + b  #
        return 6.25E-3 * (a + b + 8)

    @micropython.native
    def get_pressure(self) -> float:
        """возвращает значение давления, измеренное датчиком в Паскалях (Pa).
        До вызова этого метода нужно вызвать хотя-бы один раз метод get_temperature.
        Лучше вызывайте метод парами:
        get_temperature
        get_pressure

        returns the pressure value measured by the sensor in Pascals (Pa).
        Before calling this method, you need to call the get_temperature method at least once.
        Better call the method in pairs:
        get_temperature
        get_pressure"""
        # считывание сырого значения (три байта)
        raw = self.adapter.read_register(self.address, 0xF6, 3)
        msb, lsb, xlsb = raw
        uncompensated = ((msb << 16)+(lsb << 8)+xlsb) >> (8-self.oversample)
        b6 = self._B5-4000
        x1 = self._press0 * b6 ** 2  #
        x2 = self._press1 * b6
        x3 = x1 + x2
        b3 = (2 + ((x3 + 4 * self.get_calibration_data(0)) * 2**self.oversample)) / 4

        x1 = b6 * self._press2
        x2 = self._press3 * b6 ** 2
        x3 = (2+x1+x2) / 4

        b4 = self._press4 * (x3+32768)
        b7 = (abs(uncompensated)-b3) * (50000 / 2**self.oversample)

        curr_pressure = 2 * b7 / b4
        x1 = 7.073394953E-7 * curr_pressure ** 2
        x2 = -0.1122589111328125 * curr_pressure

        return curr_pressure + 6.25E-2 * (x1 + x2 + 3791)

    """Call start_measurement(...) before call __next__ !!!"""
    def __next__(self):
        """For support iterating.
        Return current temperature or pressure"""
        if self.temp_or_press:
            return self.get_temperature()
        return self.get_pressure()

    @property
    def temp_or_press(self) -> bool:
        return self._temp_or_press

    @property
    def oversample(self) -> int:
        return self._oss

    @oversample.setter
    def oversample(self, value: int):
        self._oss = check_value(value, range(0, 4), f"Invalid oversample settings: {value}")
