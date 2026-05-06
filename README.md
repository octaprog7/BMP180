# BMP180
Micropython module for BMP180 pressure&temperature sensor.

## [На русском](README_RU.md)

# Warning
Attention, ATtiny enthusiasts, masters of assembly and C! This project may cause you to experience uncontrollable fits of anger and rage!
The code is written in MicroPython and deliberately ignores the following bare-metal development principles:

    «Every byte counts» -> ~8 KB of RAM here? No problem.
    «Direct register access» -> set_*(...) here with foolproofing.
    «Counting cycles is mandatory» -> time.sleep_ms() here and let the hardware wait.

If you've just experienced a fit of rage, congratulations, you've come to the right place.
But if you need speed, reliability, and a unified API for BMP180/280/390, welcome to a world where code reads like a book.


# Connections
Just connect your BMP180 board to Arduino, ESP or any other board with MicroPython firmware.

Supply voltage BMP180 3.3 Volts! Not 5 volts! Use four wires to connect.
1. +3.3 V
2. GND
3. SDA
4. SCL

Upload micropython firmware to the NANO(ESP, etc) board, and then two files: main.py and bmp180.py. 
Then open main.py in your IDE and run it.

# Pictures

## IDE

![alt text](https://github.com/octaprog7/BMP180/blob/master/pics/ide_180.png)

## Breadboard

![alt text](https://github.com/octaprog7/BMP180/blob/master/pics/breadboard_180.jpg)

## Display 
Example of displaying atmospheric air pressure read from a bmp180 on a segment display: https://github.com/octaprog7/seg_displays
