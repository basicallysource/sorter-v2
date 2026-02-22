// Simple Arduino serial protocol for motor control
// Commands are comma-separated: command,arg1,arg2,...
// N - return device name (for auto-discovery)
// P,pin,mode - set pin mode (0=INPUT, 1=OUTPUT)
// D,pin,value - digital write (0=LOW, 1=HIGH)
// A,pin,value - analog/PWM write (0-255)
// S,pin,angle - servo write (0-180 degrees)
//
// Responses (sensors can send data back):
// R,sensor_id,value - sensor reading
// Future: register callback in Python for message types starting with 'R'

#include <Servo.h>

bool parseIntStrict(String s, long &out) {
  if (s.length() == 0) return false;
  int i = 0;
  bool negative = false;
  if (s.charAt(0) == '-') {
    negative = true;
    i = 1;
    if (s.length() == 1) return false;
  }

  long value = 0;
  for (; i < s.length(); i++) {
    char c = s.charAt(i);
    if (c < '0' || c > '9') return false;
    value = value * 10 + (c - '0');
  }

  out = negative ? -value : value;
  return true;
}

bool parseIntRange(String s, int start, int end, long &out) {
  if (start < 0 || end < start || end > s.length()) return false;
  return parseIntStrict(s.substring(start, end), out);
}

bool isAllowedServoPin(int pin) {
  return pin == 4 || pin == 5 || pin == 6 || pin == 11;
}

bool isAllowedStepperPair(int step_pin, int dir_pin) {
  return
    (step_pin == 36 && dir_pin == 34) ||
    (step_pin == 26 && dir_pin == 28) ||
    (step_pin == 46 && dir_pin == 48) ||
    (step_pin == 60 && dir_pin == 61) ||
    (step_pin == 54 && dir_pin == 55);
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for serial port to connect
  }
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command.length() > 0) {
      processCommand(command);
    }
  }
}

void processCommand(String cmd) {
  char cmdType = cmd.charAt(0);

  switch (cmdType) {
    case 'N': {
      Serial.println("feeder");
      break;
    }

    case 'P': {
      int firstComma = cmd.indexOf(',');
      if (firstComma == -1) return;
      String args = cmd.substring(firstComma + 1);
      int secondComma = args.indexOf(',');
      if (secondComma == -1) return;
      if (args.indexOf(',', secondComma + 1) != -1) return;

      long pin_long = 0;
      long mode_long = 0;
      if (!parseIntRange(args, 0, secondComma, pin_long)) return;
      if (!parseIntRange(args, secondComma + 1, args.length(), mode_long)) return;
      if (mode_long != 0 && mode_long != 1) return;

      int pin = (int)pin_long;
      int mode = (int)mode_long;
      pinMode(pin, mode == 1 ? OUTPUT : INPUT);
      Serial.print("Pin ");
      Serial.print(pin);
      Serial.print(" mode set to ");
      Serial.println(mode == 1 ? "OUTPUT" : "INPUT");
      break;
    }

    case 'D': {
      int firstComma = cmd.indexOf(',');
      if (firstComma == -1) return;
      String args = cmd.substring(firstComma + 1);
      int secondComma = args.indexOf(',');
      if (secondComma == -1) return;
      if (args.indexOf(',', secondComma + 1) != -1) return;

      long pin_long = 0;
      long value_long = 0;
      if (!parseIntRange(args, 0, secondComma, pin_long)) return;
      if (!parseIntRange(args, secondComma + 1, args.length(), value_long)) return;
      if (value_long != 0 && value_long != 1) return;

      int pin = (int)pin_long;
      int value = (int)value_long;
      digitalWrite(pin, value == 1 ? HIGH : LOW);
      Serial.print("Digital pin ");
      Serial.print(pin);
      Serial.print(" set to ");
      Serial.println(value == 1 ? "HIGH" : "LOW");
      break;
    }

    case 'A': {
      int firstComma = cmd.indexOf(',');
      if (firstComma == -1) return;
      String args = cmd.substring(firstComma + 1);
      int secondComma = args.indexOf(',');
      if (secondComma == -1) return;
      if (args.indexOf(',', secondComma + 1) != -1) return;

      long pin_long = 0;
      long value_long = 0;
      if (!parseIntRange(args, 0, secondComma, pin_long)) return;
      if (!parseIntRange(args, secondComma + 1, args.length(), value_long)) return;
      if (value_long < 0 || value_long > 255) return;

      int pin = (int)pin_long;
      int value = (int)value_long;
      analogWrite(pin, value);
      Serial.print("PWM pin ");
      Serial.print(pin);
      Serial.print(" set to ");
      Serial.println(value);
      break;
    }

    case 'T': {
      int firstComma = cmd.indexOf(',');
      if (firstComma == -1) return;
      String args = cmd.substring(firstComma + 1);
      int c1 = args.indexOf(',');
      int c2 = args.indexOf(',', c1 + 1);
      int c3 = args.indexOf(',', c2 + 1);
      int c4 = args.indexOf(',', c3 + 1);
      int c5 = c4 == -1 ? -1 : args.indexOf(',', c4 + 1);
      int c6 = c5 == -1 ? -1 : args.indexOf(',', c5 + 1);
      if (c1 == -1 || c2 == -1 || c3 == -1) return;
      if (c6 != -1 && args.indexOf(',', c6 + 1) != -1) return;

      long step_pin_long = 0;
      long dir_pin_long = 0;
      long steps_long = 0;
      long min_delay_us_long = 0;
      long start_delay_us_long = 0;
      long accel_steps_long = 0;
      long decel_steps_long = 0;

      if (!parseIntRange(args, 0, c1, step_pin_long)) return;
      if (!parseIntRange(args, c1 + 1, c2, dir_pin_long)) return;
      if (!parseIntRange(args, c2 + 1, c3, steps_long)) return;

      if (c4 == -1) {
        if (!parseIntRange(args, c3 + 1, args.length(), min_delay_us_long)) return;
        start_delay_us_long = min_delay_us_long;
        accel_steps_long = 0;
        decel_steps_long = 0;
      } else {
        if (!parseIntRange(args, c3 + 1, c4, min_delay_us_long)) return;
        int start_end = c5 == -1 ? args.length() : c5;
        if (!parseIntRange(args, c4 + 1, start_end, start_delay_us_long)) return;
        if (c5 == -1) {
          accel_steps_long = 0;
          decel_steps_long = 0;
        } else {
          int accel_end = c6 == -1 ? args.length() : c6;
          if (!parseIntRange(args, c5 + 1, accel_end, accel_steps_long)) return;
          if (c6 == -1) {
            decel_steps_long = accel_steps_long;
          } else {
            if (!parseIntRange(args, c6 + 1, args.length(), decel_steps_long)) return;
          }
        }
      }

      int step_pin = (int)step_pin_long;
      int dir_pin = (int)dir_pin_long;
      if (!isAllowedStepperPair(step_pin, dir_pin)) return;

      int steps = (int)steps_long;
      int min_delay_us = (int)min_delay_us_long;
      int start_delay_us = (int)start_delay_us_long;
      int accel_steps = (int)accel_steps_long;
      int decel_steps = (int)decel_steps_long;

      if (min_delay_us < 1) min_delay_us = 1;
      if (start_delay_us < min_delay_us) start_delay_us = min_delay_us;
      if (accel_steps < 0) accel_steps = 0;
      if (decel_steps < 0) decel_steps = 0;

      digitalWrite(dir_pin, steps >= 0 ? HIGH : LOW);
      int abs_steps = steps >= 0 ? steps : -steps;
      int accel_zone = accel_steps;
      int decel_zone = decel_steps;
      if (accel_zone + decel_zone > abs_steps) {
        accel_zone = abs_steps / 2;
        decel_zone = abs_steps - accel_zone;
      }
      long delay_delta = (long)start_delay_us - (long)min_delay_us;

      for (int i = 0; i < abs_steps; i++) {
        int step_delay_us = min_delay_us;
        if (delay_delta > 0 && accel_zone > 0 && i < accel_zone) {
          step_delay_us = start_delay_us - (int)((delay_delta * (long)(i + 1)) / (long)accel_zone);
        }
        if (delay_delta > 0 && decel_zone > 0 && i >= abs_steps - decel_zone) {
          int decel_index = i - (abs_steps - decel_zone);
          step_delay_us = min_delay_us + (int)((delay_delta * (long)(decel_index + 1)) / (long)decel_zone);
        }
        digitalWrite(step_pin, HIGH);
        delayMicroseconds(step_delay_us);
        digitalWrite(step_pin, LOW);
        delayMicroseconds(step_delay_us);
      }
      Serial.print("Stepper ");
      Serial.print(steps);
      Serial.println(" steps done");
      break;
    }

    case 'S': {
      int firstComma = cmd.indexOf(',');
      if (firstComma == -1) return;
      String args = cmd.substring(firstComma + 1);
      int secondComma = args.indexOf(',');
      if (secondComma == -1) return;
      if (args.indexOf(',', secondComma + 1) != -1) return;

      long pin_long = 0;
      long angle_long = 0;
      if (!parseIntRange(args, 0, secondComma, pin_long)) return;
      if (!parseIntRange(args, secondComma + 1, args.length(), angle_long)) return;
      if (!isAllowedServoPin((int)pin_long)) return;
      if (angle_long < 0 || angle_long > 180) return;

      int pin = (int)pin_long;
      int angle = (int)angle_long;
      
      Servo servo;
      servo.attach(pin);
      servo.write(angle);
      delay(500);
      servo.detach();
      
      Serial.print("Servo pin ");
      Serial.print(pin);
      Serial.print(" set to ");
      Serial.print(angle);
      Serial.println(" degrees");
      break;
    }

    default: {
      break;
    }
  }
}
