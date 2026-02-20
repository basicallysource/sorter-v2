
/*
 * Message structures and processing
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

#include "message.h"
#include "cobs.h"
#include "crc.h"
#include <stdio.h>
#include <string.h>

BusMessageProcessor::BusMessageProcessor(uint8_t device_address, MasterCommandTable &command_tables,
                                         TXFunction transmit_function)
    : _device_address(device_address), _command_tables(command_tables), _transmit_function(transmit_function) {
    _rx_buffer_pos = 0;
    _msg_len = -1;
}

/** \brief Handle an incoming command message and produce a response.
 *
 * This function decodes the command and dispatches it to the appropriate
 * handler function. It also handles common error cases like invalid commands or
 * payload lengths or invalid channels and produces appropriate error responses.
 *
 * \param msg Reference to the incoming message struct containing the command to
 * process.
 * \param resp Reference to the message struct to write the response to. The
 * handler functions will set all fields of this struct.
 */
void BusMessageProcessor::handleMessage(const BusMessage &msg, BusMessage &resp) {
    const uint8_t table_index = (msg.command & 0x70) >> 4;
    const uint8_t command_index = msg.command & 0x0F;

    resp.dev_address = msg.dev_address;
    resp.command = msg.command;

    if (_command_tables[table_index] == nullptr ||
        _command_tables[table_index]->commands[command_index].handler == nullptr) {
        resp.command = msg.command | 0x80;
        resp.payload_length = snprintf(reinterpret_cast<char *>(resp.payload), 246, "Invalid command %d", msg.command);
        return;
    }

    const CommandEntry &entry = _command_tables[table_index]->commands[command_index];

    if (entry.payload_length != 255 && msg.payload_length != entry.payload_length) {
        resp.command = msg.command | 0x80;
        resp.payload_length =
            snprintf(reinterpret_cast<char *>(resp.payload), 246, "%s: Invalid payload length %d, expected %d",
                     entry.name, msg.payload_length, entry.payload_length);
        return;
    }

    if (entry.channel_validator != nullptr && !entry.channel_validator(msg.channel)) {
        resp.command = msg.command | 0x80;
        resp.payload_length =
            snprintf(reinterpret_cast<char *>(resp.payload), 246, "%s: Invalid channel %d", entry.name, msg.channel);
        return;
    }

    entry.handler(&msg, &resp);
}

/** \brief Process incoming data from the USB or serial connection, assemble
 * messages, and call the command handler when a complete message is received.
 *
 * This function is called for each incoming byte from the USB connection. It
 * appends the byte to the rx_buffer until it finds a null terminator, at which
 * point it attempts to decode the message using COBS, checks the CRC, and if
 * everything is valid, calls CMD_handle_message to process the command and
 * prepare a response. If any errors are encountered (framing error, CRC error,
 * invalid address), it sets msg_len to -1 to indicate that the current buffer
 * should be discarded.
 *
 * \param c The incoming byte to process
 */
void BusMessageProcessor::processIncomingData(char c) {
    if (c == 0) {
        // End of message
        if (_rx_buffer_pos < 8) {
            // Empty message, ignore (doesn't even fit the CRC and header)
            _msg_len = 0;
            return;
        }
        int res = COBS_decode((uint8_t *)rx_buffer, _rx_buffer_pos, (uint8_t *)_rx_message, sizeof(_rx_message));
        if (res < 0) {
            _msg_len = -1; // Framing error
            _rx_buffer_pos = 0;
            return;
        }
        if (_rx_message[0] != _device_address) {
            _msg_len = -1; // Not for us, ignore
            _rx_buffer_pos = 0;
            return;
        }
        _msg_len = res;
        uint32_t incoming_crc;
        memcpy(&incoming_crc, _rx_message + _msg_len - 4, sizeof(incoming_crc));
        uint32_t calc_crc = crc32(_rx_message, _msg_len - 4);
        if (calc_crc != incoming_crc) {
            _msg_len = -1; // CRC error
            _rx_buffer_pos = 0;
            return;
        }
        _msg_len = _msg_len - 4; // Exclude CRC
        _rx_buffer_pos = 0;      // Prepare to receive again
        return;
    }
    if (_rx_buffer_pos < sizeof(rx_buffer)) {
        rx_buffer[_rx_buffer_pos++] = c;
    } else {
        // Buffer full, treat as framing error
        _msg_len = -1;
        _rx_buffer_pos = 0;
        return;
    }
}


/** \brief Process queued messages, if any.
 *
 * This function should be called regularly in the main loop to check if a
 * complete message has been received and is ready to be processed. If _msg_len
 * is greater than 0, it means we have a complete message in _rx_message that
 * can be processed. This function will call handleMessage to process the
 * command and prepare a response, then COBS encode the response and send it
 * using the transmit function. Finally, it sets _msg_len to -1 to indicate
 * that the current message has been processed and the buffer can be reused.
 */
void BusMessageProcessor::processQueuedMessage() {
    // If we have a complete message, process it
    if (_msg_len > 0) {
        // Process message, prepare response in place in _tx_message
        auto &msg = *reinterpret_cast<BusMessage *>(_rx_message);
        auto &resp = *reinterpret_cast<BusMessage *>(_tx_message);
        handleMessage(msg, resp);
        // Calculate total response length
        int resp_len = 4 + resp.payload_length; // Header + payload
        // Append CRC
        uint32_t crc = crc32(_tx_message, resp_len);
        memcpy(_tx_message + resp_len, &crc, sizeof(crc));
        resp_len += sizeof(crc);
        // COBS encode response in place
        int enc_len = COBS_encode((uint8_t *)_tx_message, resp_len, (uint8_t *)_tx_buffer, sizeof(_tx_buffer));
        if (enc_len < 0) {
            // Encoding error, should not happen
            return;
        }
        _transmit_function(_tx_buffer, enc_len);
        _msg_len = -1; // Message, processed, drop it
    }
}