# micropython
# MIT license
# Copyright (c) 2022 Roman Shevchik   goctaprog@gmail.com
import micropython
from micropython import const
import array

from sensor_pack_2 import bus_service
from sensor_pack_2.base_sensor import DeviceEx, check_value
from sensor_pack_2.bmp_common import IBaseAirPresSensor, OversamplingCoeff, MeasChannels, SensorID

# ВНИМАНИЕ: не подключайте питание датчика к 5В, иначе датчик выйдет из строя! Только 3.3В!!!
# WARNING: do not connect "+" to 5V or the sensor will be damaged!


_MSK_BIT_SCO = const(0b10_0000)
_CONV_TIME_PRESS = const((5, 8, 14, 26))  # по индексу OSS
# Регистры BMP180
_REG_ID = const(0xD0)
_REG_SOFT_RESET = const(0xE0)
_REG_CTRL = const(0xF4)
_REG_OUT_MSB = const(0xF6)
_PRESSURE_MEAS = const(0x14)
_TEMPERATURE_MEAS = const(0x0E)

def _calibration_regs_addr() -> iter:
    """возвращает итератор с адресами внутренних регистров датчика, хранящих калибровочные коэффициенты."""
    return range(0xAA, 0xBF, 2)


class Bmp180(IBaseAirPresSensor):
    """Класс для работы с датчиком давления воздуха Bosch BMP180.
    BMP180 измеряет T и P строго последовательно. Расчёт давления
    требует свежей температуры для компенсации (_B5). При включении обоих
    каналов в set_channels(True, True) итератор __next__() отдаёт приоритет
    давлению, а температуру считывает автоматически только при отсутствии
    кэша _B5."""

    def __init__(self, adapter: bus_service.I2cAdapter, address: int = 0x77, oss=0b11):
        """i2c - объект класса I2C; oss (oversample_settings) (0..3) - точность измерения 0-грубо, но быстро,
        3-медленно, но точно; address - адрес датчика на шине."""
        self._connection = DeviceEx(adapter=adapter, address=address, big_byte_order=True)
        #
        self._ch_temp = True      # канал температуры включён по умолчанию
        self._ch_press = True     # канал давления включён по умолчанию
        #
        self._press4 = None  # for precalculate
        self._press3 = None  # for precalculate
        self._press2 = None  # for precalculate
        self._press1 = None  # for precalculate
        self._press0 = None  # for precalculate
        self._tmp1 = None    # for precalculate
        self._tmp0 = None    # for precalculate
        self._B5 = None      # for precalculate
        #
        self._oversample_press = None
        self.set_oversampling(temp=0, press=oss)
        # массив, хранящий калибровочные коэффициенты (11 штук)
        self._cfa = array.array("l")  # signed long elements
        # считываю калибровочные коэффициенты
        self._read_calibration_data()
        # предварительный расчет
        self._precalculate()

    @staticmethod
    def _check_cc(index: int):
        """Проверяет на верность индекс калибровочного коэффициента."""
        check_value(value=index, valid_range=range(11), error_msg=f"Invalid index value: {index}")

    @micropython.native
    def get_calibration(self, index: int | None) -> int:
        """возвращает калибровочный коэффициент по его индексу (0..10).
        returns the calibration coefficient by its index (0..10)"""
        if index is None:
            return len(self._cfa)
        Bmp180._check_cc(index)
        return self._cfa[index]

    @micropython.native
    def _precalculate(self):
        """предварительно вычисленные значения. precomputed values"""
        # для расчета температуры/for temperature calculation
        get_cc = self.get_calibration
        self._tmp0 = get_cc(4) / 2 ** 15  #
        self._tmp1 = get_cc(9) * 2 ** 11  #
        # для расчета давления/for pressure calculation
        self._press0 = get_cc(7) / 2 ** 23
        self._press1 = get_cc(1) / 2 ** 11
        self._press2 = get_cc(2) / 2 ** 13
        self._press3 = get_cc(6) / 2 ** 28
        self._press4 = abs(get_cc(3)) / 2 ** 15

    @staticmethod
    @micropython.native
    def _validate_cc(index: int, value: int) -> tuple[bool, str | None]:
        """Проверка калибровочного коэффициента по индексу и значению.
        Индексы: 0-AC1, 1-AC2, 2-AC3, 3-AC4, 4-AC5, 5-AC6,
                 6-B1,  7-B2,  8-MB,  9-MC,  10-MD."""
        Bmp180._check_cc(index)

        # Границы допустимых значений (минимум и максимум для индексов 0..10)
        _MIN = (-32768, -32768, -32768, 0, 0, 0, -32768, -32768, -32768, -15000, -32768)
        _MAX = (32767, 32767, 32767, 65535, 65535, 65535, 32767, 32767, 32767, 15000, 32767)

        min_v, max_v = _MIN[index], _MAX[index]

        # Проверка границ
        if value < min_v or value > max_v:
            # Индекс 9 (MC) — единственный не важный, только предупреждение
            if 9 == index:
                return True, f"WARN: MC={value} out of typical range"
            return False, f"ERR: coeff {index} out of bounds [{min_v}..{max_v}]"

        # AC4, AC5, AC6 (индексы 3..5) в рабочих датчиках всегда > 1000
        if index in range(3, 6) and value < 1000:
            return False, f"ERR: coeff {index}={value} low value!"

        # "мусор", пустой EEPROM или поддельный чип
        if value in (0x0000, 0xFFFF, 0x7FFF, 0x8000):
            return False, f"ERR: coeff. {index}=0x{value:x} looks invalid!"

        return True, None

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
            is_ok, msg = Bmp180._validate_cc(index, rv)
            if not is_ok:
                raise ValueError(msg)
            self._cfa.append(rv)
        return len(self._cfa)

    def get_id(self) -> SensorID:
        """Возвращает идентификатор датчика. Правильное значение - 0х55.
        Returns the ID of the sensor. The correct value is 0x55."""
        conn = self._connection
        res = conn.read_reg(_REG_ID, 1)
        return SensorID(int(res[0]), None, None, None)

    def soft_reset(self):
        """программный сброс датчика.
        software reset of the sensor"""
        conn = self._connection
        conn.write_reg(_REG_SOFT_RESET, 0xB6, 1)

    @micropython.native
    def start_measurement(self):
        """Запускает процесс измерения температуры или давления датчиком.
        Если measure_temperature==Истина тогда будет выполнен запуск измерения температуры иначе давления!
        Вы должны подождать результата 5 мс после запуска измерения температуры.
        Время ожидания результата после запуска измерения давления зависит от значения, возвращаемого методом get_oversample()
        oversample      задержка, мс
        0               5
        1               8
        2               14
        3               26"""
        measure_temp = False if self._ch_press else self._ch_temp
        if not self._ch_press and not self._ch_temp:
            return  # оба канала выключены

        loc_oss = self.set_oversampling(None, None).pressure
        start_conversion = 0b0010_0000   # bit 5 - запуск преобразования (1)
        bit_4_0 = _PRESSURE_MEAS  # измеряю давление
        if measure_temp:
            bit_4_0 = _TEMPERATURE_MEAS  # измеряю температуру
            loc_oss = 0  # обнуляю OSS при измерении температуры
        val = loc_oss << 6 | start_conversion | bit_4_0
        self._connection.write_reg(_REG_CTRL, val, 1)
        # Сброс кэша температуры. Чтобы данные давления были поточнее!
        # self._B5 = None

    def _get_temp_raw(self) -> int:
        """Возвращает сырое значение температуры."""
        # считывание сырого значения
        conn = self._connection
        raw = conn.read_reg(_REG_OUT_MSB, 2)
        return conn.unpack("H", raw)[0]  # unsigned short

    @micropython.native
    def get_temperature(self) -> float:
        """возвращает значение температуры, измеренное датчиком в Цельсиях.
        returns the temperature value measured by the sensor in Celsius"""
        get_cc = self.get_calibration
        raw_t = self._get_temp_raw()
        a = self._tmp0 * (raw_t - get_cc(5))
        b = self._tmp1 / (a + get_cc(10))
        self._B5 = a + b  #
        return 6.25E-3 * (a + b + 8)

    def _get_press_raw(self) -> int:
        """Возвращает сырое значение атмосферного давления."""
        # считывание сырого значения (три байта)
        raw = self._connection.read_reg(_REG_OUT_MSB, 3)
        msb, lsb, xlsb = raw
        oss = self.set_oversampling(None, None).pressure
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
        uncompensated = self._get_press_raw()
        b6 = self._B5-4000
        x1 = self._press0 * b6 ** 2  #
        x2 = self._press1 * b6
        x3 = x1 + x2
        oss = self.set_oversampling(None, None).pressure
        b3 = (2 + ((x3 + 4 * self.get_calibration(0)) * 2**oss)) / 4

        x1 = b6 * self._press2
        x2 = self._press3 * b6 ** 2
        x3 = (2+x1+x2) / 4

        b4 = self._press4 * (x3+32768)
        b7 = (abs(uncompensated)-b3) * (50000 / 2**oss)

        curr_pressure = 2 * b7 / b4
        x1 = 7.073394953E-7 * curr_pressure ** 2
        x2 = -0.1122589111328125 * curr_pressure

        return curr_pressure + 6.25E-2 * (x1 + x2 + 3791)


    def set_channels(self, temp_en, press_en) -> None | MeasChannels:
        """Управляет программной логикой выбора измерений.

        Аппаратно BMP180 не поддерживает отключение каналов —
        температура и давление всегда доступны, но измеряются последовательно.

        Когда оба параметра метода None (None, None), возвращает MeasChannels(True, True),
        так как оба канала аппаратно активны.

        Обновляет внутренний кэш для:
          - Приоритета возврата значения из __next__()
          - Выбора типа измерения в start_measurement()
        """
        if temp_en is None and press_en is None:
            return MeasChannels(temperature=True, pressure=True)
        if temp_en is not None:
            self._ch_temp = temp_en
        if press_en is not None:
            self._ch_press = press_en
        #
        return None

    def set_oversampling(self, temp: int | None = None, press: int | None = None) -> None | OversamplingCoeff:
        """Устанавливает коэффициент избыточной (oversampling ratio) выборки измерения давления (0: однократный, 1: 2 раза, 2: 4 раза, 3: 8 раз)."""
        if press is None and temp is None:
            return OversamplingCoeff(temperature=0, pressure=self._oversample_press)
        if press is not None:
            self._oversample_press = check_value(press, range(4), f"Invalid oversample settings: {press}")
        # Запись OSS в регистр происходит только при start_measurement()
        return None

    def get_conversion_cycle_time(self) -> int:
        """Возвращает время в мс преобразования сигнала в цифровой код и готовности его для чтения по шине!
        Для текущих настроек датчика. При изменении настроек следует заново вызвать этот метод!"""
        cct = _CONV_TIME_PRESS
        _os_p = self.set_oversampling(None,None).pressure
        # Если включено давление, то время преобразования зависит от OSS, иначе фиксировано для T
        return cct[_os_p] if self._ch_press else cct[0]

    def get_measurement_value(self, value_index: int) -> float:
        """Возвращает измеренное датчиком значение(значения) по его индексу/номеру.
        0 - температура воздуха;
        1 - атмосферное давление воздуха;"""
        if 0 == value_index:
            return self.get_temperature()
        if 1 == value_index:
            return self.get_pressure()
        raise ValueError(f"Неверное значение value_index: {value_index}")

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
        raw_val = self._connection.read_reg(_REG_CTRL, 1)[0]
        if raw:
            return raw_val
        return 0 == (raw_val & _MSK_BIT_SCO)

    def set_iir_filter(self, temp: int | None = None, press: int | None = None) -> tuple[int, int]:
        """BMP180 не имеет аппаратного ФНЧ. Любая попытка записи вызывает ошибку."""
        if temp is not None or press is not None:
            raise NotImplementedError("BMP180: аппаратный IIR фильтр отсутствует")
        return 0, 0  # всегда возвращает "выключено"

    def refresh_config(self):
        """Перечитывает регистр управления 0xF4 (CTRL_MEAS) и синхронизирует внутренний кэш.

        ВНИМАНИЕ: Вызывать ТОЛЬКО когда датчик завершил преобразование (бит SCO=0,
        данные готовы). Вызов во время работы АЦП приведёт к чтению 'сырых' битов!

        Преобразование аппаратных битов в программные флаги:
            - Биты 7:6 -> OSS (точность давления)   -> self._oversample_press
            - Бит 4    -> MEAS (тип след. измерения) -> self._ch_press (1) / self._ch_temp (0)

        Безопасный вызов:
            sensor.start_measurement()
            while not sensor.get_data_status(raw=False): pass  # ждём SCO=0
            sensor.refresh_config()
        """
        reg = self._connection.read_reg(_REG_CTRL, 1)[0]
        self._oversample_press = (reg >> 6) & 0x03

        # Аппаратный регистр хранит только тип СЛЕДУЮЩЕГО измерения.
        # Синхронизирую программные флаги с состоянием чипа:
        is_pressure_next = bool(reg & 0x10)
        self._ch_press = is_pressure_next
        self._ch_temp = not is_pressure_next

    def set_power_mode(self, value: int | None = None) -> int:
        """BMP180 не поддерживает аппаратные режимы (Sleep/Normal).
        Датчик всегда находится в состоянии готовности к Forced-измерению.
        Метод игнорирует запись и всегда возвращает 1 (Forced).

        Args:
            value: Игнорируется.
        Returns:
            int: 1 (всегда Forced).
        """
        return 1

    def set_sampling_period(self, period: int | None = None) -> int:
        """BMP180 не имеет регистра ODR. Частота измерений управляется программно хостом.
        Возвращает 0, чтобы обозначить отсутствие аппаратной настройки периода.

        Args:
            period: Игнорируется.
        Returns:
            int: 0.
        """
        return 0