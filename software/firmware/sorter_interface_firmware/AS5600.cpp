#include "AS5600.h"

static const uint8_t REG_STATUS = 0x0B;
static const uint8_t REG_RAW_ANGLE = 0x0C; // two bytes, MSB first, 12 bits used
static const uint8_t REG_AGC = 0x1A;
static const uint32_t XFER_TIMEOUT_US = 1000;

bool AS5600::readRegisters(uint8_t reg, uint8_t *buf, size_t len) {
    if (i2c_write_timeout_us(_port, _address, &reg, 1, true, XFER_TIMEOUT_US) != 1) return false;
    return i2c_read_timeout_us(_port, _address, buf, len, false, XFER_TIMEOUT_US) == (int)len;
}

bool AS5600::readRawAngle(uint16_t *out) {
    uint8_t b[2];
    if (!readRegisters(REG_RAW_ANGLE, b, 2)) return false;
    *out = (uint16_t)(((b[0] & 0x0F) << 8) | b[1]);
    return true;
}

bool AS5600::readStatus(uint8_t *out) { return readRegisters(REG_STATUS, out, 1); }
bool AS5600::readAgc(uint8_t *out) { return readRegisters(REG_AGC, out, 1); }
