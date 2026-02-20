/*
 * Sorter Interface Firmware - Consistent Overhead Byte Stuffing (COBS) Functions
 * Copyright (C) 2017-2026 Jose I Romero
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

#include "cobs.h"


/** \brief Decode a COBS (Consistent Overhead Byte Stuffing) encoded buffer into the original message.
 * 
 *  Only supports messages up to 253 bytes long.
 * 
 * \param encoded_buf Pointer to the COBS encoded buffer
 * \param encoded_size Size of the COBS encoded message in bytes
 * \param msg_buf Pointer to the output buffer where the decoded message will be stored
 * \param msg_buf_size Size of the output buffer in bytes
 * 
 * \return Number of bytes written to the message buffer on success, -1 if output buffer is too small, -2 if framing error.
 */
int COBS_decode(const uint8_t *encoded_buf, uint8_t encoded_size, uint8_t *msg_buf, uint8_t msg_buf_size) {
    int ret = 0;
    uint8_t i, counter;

    int msg_size = encoded_size - 1; // Exclude the initial count byte
    if (msg_size > msg_buf_size) {
        return -1; // Output buffer too small
    }

    counter = encoded_buf[0];

    for (i=0; i<msg_size; i++) {
        uint8_t data_byte = encoded_buf[i+1];
        if (data_byte == 0) {
            return -2; // Framing error: stuffed data must have no 0s
        }
        if (counter == 1) { // Reached the end of a block, insert zero and take new count
            msg_buf[i] = 0;
            counter = data_byte;
        } else {
            msg_buf[i] = data_byte;
            counter--;
        }
    }

    // Framing error: corrupted count, or message cut short.
    if (counter > 1) return -2;

    return msg_size;
}


/** \brief Encode a message using COBS (Consistent Overhead Byte Stuffing).
 * 
 *  Only supports messages up to 253 bytes long.
 * 
 * \param msg_buf Pointer to the original message buffer
 * \param msg_size Size of the original message in bytes
 * \param encoded_buf Pointer to the output buffer where the COBS encoded message will be stored
 * \param encoded_buf_size Size of the output buffer in bytes
 * 
 * \return Number of bytes written to the encoded buffer on success, -1 if output buffer is too small, -2 if message is too large to encode.
 */
int COBS_encode(const uint8_t *msg_buf, uint8_t msg_size, uint8_t *encoded_buf, uint8_t encoded_buf_size) {
    uint8_t *counter;
    uint8_t *encoded_start = encoded_buf;
    const uint8_t *msg_end;
    if ((msg_size+2) > encoded_buf_size) {
        return -1; // Buffer too small, must be able to fit overhead and delimiter
    }
    if (msg_size > 253) {
        return -2; // Message too large
    }
    msg_end = msg_buf + msg_size;

    *encoded_buf = 1;
    counter = encoded_buf;
    encoded_buf++;
    // Copy bytes and increment counter until a zero is found, then start a new block by moving the counter variable.
    while (msg_buf < msg_end){
        if (*msg_buf == 0){
            counter = encoded_buf;
        }
        *encoded_buf++ = *msg_buf++;
        (*counter)++;
    }
    *encoded_buf++ = 0; // Add delimiter byte

    return encoded_buf - encoded_start;
}
