# micropython

# ВНИМАНИЕ: не подключайте питание датчика к 5В, иначе датчик выйдет из строя! Только 3.3В!!!
# WARNING: do not connect "+" to 5V or the sensor will be damaged!
from machine import I2C
import bmp180
import time
from sensor_pack_2.bus_service import I2cAdapter

# fromPaToMmHg
def fromPaToMmHg(value: float) -> float:
    """Convert air pressure from Pa to mm Hg"""
    if isinstance(value, float):
        return 7.50062E-3 * value
    return None


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
    print([ps.get_calibration_data(i) for i in range(11)])

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
    print(20 * "*_")
    print("Reading pressure using an iterator!")
    for index, press in enumerate(ps):
        if press is None:
            continue
        time.sleep_ms(delay)  # delay for pressure measurement
        ps.start_measurement(measure_temperature=False)
        min_press = min(press, min_press)
        max_press = max(press, max_press)
        average_press = 0.5 * (min_press + max_press)
        # print(f"Air pressure: {press} Pa\t{fromPaToMmHg(press)} mm Hg\tDelay: {delay} [ms]")
        mmhg = fromPaToMmHg(average_press)
        print(f"Air pressure min max average [Pa]: {min_press} {max_press} {average_press}/{mmhg} Pa/mmHg")
