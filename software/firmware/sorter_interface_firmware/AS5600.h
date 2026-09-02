#ifndef AS5600_H
#define AS5600_H
#include "hardware/i2c.h"
#include <stdint.h>

// AMS AS5600 12-bit magnetic rotary encoder on I2C (fixed address 0x36).
// Only the registers the stepper position check needs: RAW_ANGLE, STATUS, AGC.
class AS5600 {
  public:
    static const uint8_t DEFAULT_ADDRESS = 0x36;
    static const uint16_t COUNTS_PER_REV = 4096;
    // STATUS bits
    static const uint8_t STATUS_MAGNET_HIGH = 0x08;     // MH: magnet too strong
    static const uint8_t STATUS_MAGNET_LOW = 0x10;      // ML: magnet too weak
    static const uint8_t STATUS_MAGNET_DETECTED = 0x20; // MD

    AS5600(i2c_inst_t *port, uint8_t address = DEFAULT_ADDRESS) : _port(port), _address(address) {}
    // All return true on success; a failed transfer leaves *out untouched.
    bool readRawAngle(uint16_t *out);
    bool readStatus(uint8_t *out);
    bool readAgc(uint8_t *out);

  private:
    bool readRegisters(uint8_t reg, uint8_t *buf, size_t len);
    i2c_inst_t *_port;
    uint8_t _address;
};
#endif
