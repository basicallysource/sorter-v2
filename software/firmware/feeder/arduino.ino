// Simple Arduino serial protocol for motor control
// Commands are comma-separated: command,arg1,arg2,...
// P,pin,mode - set pin mode (0=INPUT, 1=OUTPUT)
// D,pin,value - digital write (0=LOW, 1=HIGH)
// A,pin,value - analog/PWM write (0-255)
//
// Responses (sensors can send data back):
// S,sensor_id,value - sensor reading
// Future: register callback in Python for message types starting with 'S'

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
  int firstComma = cmd.indexOf(',');
  if (firstComma == -1) return;

  char cmdType = cmd.charAt(0);
  String args = cmd.substring(firstComma + 1);

  switch (cmdType) {
    case 'P': {
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
  }
}
