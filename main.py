# micropython

# ВНИМАНИЕ: не подключайте питание датчика к 5В, иначе датчик выйдет из строя! Только 3.3В!!!
# WARNING: do not connect "+" to 5V or the sensor will be damaged!
from machine import I2C
import bmp180
import time
from sensor_pack.bus_service import I2cAdapter


def pa_mmhg(value: float) -> float:
    """Convert air pressure from Pa to mm Hg"""
    return value*7.50062E-3


if __name__ == '__main__':
    # пожалуйста установите выводы scl и sda в конструкторе для вашей платы, иначе ничего не заработает!
    # please set scl and sda pins for your board, otherwise nothing will work!
    # https://docs.micropython.org/en/latest/library/machine.I2C.html#machine-i2c
    # i2c = I2C(0, scl=Pin(13), sda=Pin(12), freq=400_000) № для примера
    # bus =  I2C(scl=Pin(4), sda=Pin(5), freq=100000)   # на esp8266    !
    adaptor = I2cAdapter(I2C(0, freq=400_000))
    # ps - pressure sensor
    ps = bmp180.Bmp180(adaptor)

    # если у вас посыпались исключения, чего у меня на макетной плате с али и проводами МГТВ не наблюдается,
    # то проверьте все соединения.
    # Радиотехника - наука о контактах! РТФ-Чемпион!
    res = ps.get_id()
    print(f"chip_id: {hex(res)}")

    cdl = [ps.get_calibration_data(i) for i in range(11)]
    print("Calibration data from registers:")
    print(cdl)

    for i in range(10):
        ps.start_measurement()
        delay = bmp180.get_conversion_cycle_time(ps.temp_or_press, ps.oss)
        time.sleep_ms(delay)    # delay for temperature measurement
        print(f"Temperature from BMP180: {ps.get_temperature()} \xB0 С\tDelay: {delay} [ms]")

    ps.start_measurement(False)
    delay = bmp180.get_conversion_cycle_time(ps.temp_or_press, ps.oss)
    time.sleep_ms(delay)  # delay for pressure measurement
    for index, press in enumerate(ps):
        time.sleep_ms(delay)  # delay for pressure measurement
        ps.start_measurement(False)
        print(f"Pressure from BMP180: {press} Pa\t{pa_mmhg(press)} mm hg\tDelay: {delay} [ms]")
        if index > 9:
            break
