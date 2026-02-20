/*
 * CRC-32 Calculation Function
 * Copyright (C) 2026 Jose I Romero
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

#include "crc.h"
#include <stddef.h>
#include <stdint.h>

/** \brief Calculate CRC-32 of a given data buffer
 *
 * \param data Pointer to the data buffer
 * \param length Length of the data buffer in bytes
 * \return Calculated CRC-32 value
 */
uint32_t crc32(const void *data, size_t length) {
    uint32_t crc = 0xFFFFFFFF; // Initialize with -1

    for (size_t i = 0; i < length; i++) {
        crc ^= ((const uint8_t *)data)[i];
        for (int j = 0; j < 8; j++) {
            // If the LSB is set, shift and XOR with polynomial
            if (crc & 1) {
                crc = (crc >> 1) ^ 0xEDB88320;
            } else {
                crc >>= 1;
            }
        }
    }
    // Invert the final CRC value
    return ~crc;
}