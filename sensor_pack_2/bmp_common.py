# MIT license
# Copyright (c) 2022-2026 Roman Shevchik

"""
Соглашение для методов set_*:
    - Если все аргументы == None -> метод работает как геттер, возвращает текущее значение.
    - Если передан хотя бы один аргумент != None -> метод работает как сеттер, возвращает None.
    - Пример:
        bmp.set_oversampling(None, None)  # read -> OversamplingCoeff(0, 3)
        bmp.set_oversampling(press=2)     # write -> None
"""

from collections import namedtuple
# настройки oversampling (int, int)
OversamplingCoeff = namedtuple("OversamplingCoeff", "temperature pressure")
# возвращает активность каналов измерения (Истина->канал активен)
MeasChannels = namedtuple("MeasChannels", "temperature pressure")

class IBMPCommon:
    """
    Унифицированный интерфейс для датчиков давления атмосферного воздуха.

    Для документации:
        get_calibration(index: int) -> int
        set_oversampling(temp: int|None, press: int|None) -> (int, int)
        set_iir_filter(coeff: int) -> int
        set_channels(temp_en: bool|None, press_en: bool|None) -> (bool, bool)
        refresh_config() -> None
    """

    def get_calibration(self, index: int | None) -> int:
        """Возвращает калибровочный коэффициент по индексу (int).
        Если index is None, возвращает кол-во калибровочных коэффициентов.
        Коэффициенты считываются из датчика 'приватным' методом."""
        raise NotImplementedError()

    def set_oversampling(self, temp: int | None = None, press: int | None = None) -> None | OversamplingCoeff:
        """
        Устанавливает oversampling. None = не менять.
        Возвращает фактические значения, если temp и pressure в None: (temp, pressure) -> (int, int).
        """
        raise NotImplementedError()

    def set_iir_filter(self, coeff: int | None):
        """
        Устанавливает коэффициент ФНЧ (int, 0..N).
        Возвращает фактическое значение (int), если coeff в None.
        Бросает NotImplementedError, если не поддерживается.
        """
        raise NotImplementedError()

    def set_channels(self, temp_en, press_en) -> None | MeasChannels:
        """
        Включает/выключает каналы измерения. None = не менять.
        Возвращает фактические состояния, если temp_en и press_en в None: (temp_en, press_en) -> (bool, bool).
        """
        raise NotImplementedError()

    def refresh_config(self):
        """Перечитывает настройки из регистров датчика во внутренний кэш."""
        raise NotImplementedError()