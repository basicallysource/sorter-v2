from machine import Pin
import time

STEP_PIN = 2
DIR_PIN  = 3
EN_PIN   = 6   # <-- updated

step = Pin(STEP_PIN, Pin.OUT)
dir  = Pin(DIR_PIN, Pin.OUT)
en   = Pin(EN_PIN, Pin.OUT)

# Enable driver (LOW = enabled)
en.value(0)

# Initial direction
dir.value(1)

print("Stepper test starting")

while True:
    # 200 steps ≈ 1 rev for 1.8° motor (full-step)
    for i in range(200):
        step.value(1)
        time.sleep_us(500)
        step.value(0)
        time.sleep_us(500)

    time.sleep(1)

    # Reverse direction
    dir.toggle()
