import requests
import time

API_BASE = "http://localhost:7125"
BLINK_INTERVAL = 0.5  # seconds


def sendGcode(command):
    response = requests.post(
        f"{API_BASE}/printer/gcode/script",
        json={"script": command}
    )
    return response.json()


def blinkLed():
    print("Blinking LED...")
    while True:
        sendGcode("SET_PIN PIN=status_led VALUE=1")
        time.sleep(BLINK_INTERVAL)
        sendGcode("SET_PIN PIN=status_led VALUE=0")
        time.sleep(BLINK_INTERVAL)


def main():
    blinkLed()


if __name__ == "__main__":
    main()
