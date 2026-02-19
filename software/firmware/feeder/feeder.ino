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
      int pin = args.substring(0, secondComma).toInt();
      int mode = args.substring(secondComma + 1).toInt();
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
      int pin = args.substring(0, secondComma).toInt();
      int value = args.substring(secondComma + 1).toInt();
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
      int pin = args.substring(0, secondComma).toInt();
      int value = args.substring(secondComma + 1).toInt();
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
      int step_pin = args.substring(0, c1).toInt();
      int dir_pin = args.substring(c1 + 1, c2).toInt();
      int steps = args.substring(c2 + 1, c3).toInt();
      int min_delay_us = c4 == -1 ? args.substring(c3 + 1).toInt() : args.substring(c3 + 1, c4).toInt();
      int start_delay_us = c4 == -1 ? min_delay_us : args.substring(c4 + 1, c5 == -1 ? args.length() : c5).toInt();
      int accel_steps = c5 == -1 ? 0 : args.substring(c5 + 1, c6 == -1 ? args.length() : c6).toInt();
      int decel_steps = c6 == -1 ? accel_steps : args.substring(c6 + 1).toInt();

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
      int pin = args.substring(0, secondComma).toInt();
      int angle = args.substring(secondComma + 1).toInt();
      
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
  }
}
