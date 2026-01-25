# Overview of RPi Pico, MicroPython, & TMC2209
## Physical Connections:
see diagram here:
https://app.mural.co/invitation/team/sandbox52356?code=19e1987b4d46466cbbc7b390f4f7fa32&sender=u6cacbf5f221c9b10a16d8400&returnUrl=%2Ft%2Fsandbox52356%2Fm%2Fsandbox52356%2F1765925668197%2F61cab98ecc26e27c1749745424307a242406455a%3Fsender%3Du6cacbf5f221c9b10a16d8400

Based on proven working implementation with Big Tree Tech (BTT) TMC2209

- RPI Pico GPIO 0 ---- 1k resistor ---- RPI Pico GPIO 1 ---- RX pin (BTT TMC2209)
- RPI Pico Ground ---- All GND pins (BTT TMC2209) ---- GND on bench power supply
- RPI Pico 3.3V ---- VIO pin (BTT TMC2209)
- V+ on Bench power supply ---- VS pin (BTT TMC2209)
- RPI Pico GPIO 2 ---- STEP pin (BTT TMC2209)
- RPI Pico GPIO 3 ---- DIR pin (BTT TMC2209)
- RPI Pico GPIO 6 ---- EN pin (BTT TMC2209)

## Setup raspberry pi pico:
- connect usb from PC to RPi Pico
- copy latest micropython .uf2 onto RPi Pico using file explorer
- power cycle pico

## Interacting with pico file system
Host PC commands:
`python3 -m pip install --user mpremote`

list usb devices:
`mpremote connect list`

RPi pico should look like:
`/dev/cu.usbmodem...`

Connect to RPi Pico terminal:
`mpremote connect /dev/cu.usbmodem* repl`

use fs to run file system commands:
list files on pico:
`mpremote connect /dev/cu.usbmodem* fs ls`

copy host main.py onto pico file system (:)
`mpremote connect /dev/cu.usbmodem* fs cp main.py :`

copy host file (checkout.py) onto pico file system with new name (main.py):
`mpremote connect /dev/cu.usbmodem* fs cp checkout.py :main.py`

pico will run main.py automatically on startup. Use the following line to reset the pico to run main.py again:
`mpremote connect /dev/cu.usbmodem* reset`

## syncing and running the code:
1. `cd software/firmware/micropython/tmc2209_lib/`
2. copy library onto pico:
    - `mpremote connect /dev/cu.usbmodem* fs cp tmc2209.py :`
3. copy checkout script onto pico as main.py to ensure autostart on reset:
    - `mpremote connect /dev/cu.usbmodem* fs cp checkout_tmc2209.py :main.py`
4. reset pico to autostart main.py:
    - `mpremote connect /dev/cu.usbmodem* reset`
5. connect to pico's terminal to see output:
    - `mpremote connect /dev/cu.usbmodem* repl`
6. click enter to begin checkout


