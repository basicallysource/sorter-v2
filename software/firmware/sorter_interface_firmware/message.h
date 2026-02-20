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

#ifndef MESSAGE_H
#define MESSAGE_H

#include "cobs.h"
#include <array>
#include <stdbool.h>
#include <stdint.h>

const int MAX_PAYLOAD_SIZE = COBS_MAX_MESSAGE_SIZE - 4 - 4; // 254 - 4 bytes of header - 4 bytes of CRC

struct BusMessage {
    uint8_t dev_address;    // Device address, ignored on USB connections
    uint8_t command;        // Command code (from 0 to 127, high bit is used to signal exceptions)
    uint8_t channel;        // Channel or motor number
    uint8_t payload_length; // Length of payload in bytes
    uint8_t payload[];      // Payload data
};

typedef void (*CommandHandler)(const BusMessage *msg, BusMessage *resp);
typedef bool (*ChannelValidator)(uint8_t channel);

struct CommandEntry {
    const char *name;                   // For debugging and self-documentation purposes.
    const char *arg_type;               // In python stuct format, e.g. "B" for uint8_t, "i" for int32_t, etc.
    const char *ret_type;               // In python stuct format, e.g. "B" for uint8_t, "i" for int32_t, etc.
    uint8_t payload_length;             // Expected payload length for this command 255 if variable, 0 if no payload
    ChannelValidator channel_validator; // Optional function to validate the channel field of the message, can be NULL
                                        // if no validation needed
    CommandHandler handler;
};

struct CommandTable {
    const char *prefix;
    std::array<CommandEntry, 16> commands;
};

typedef const std::array<const CommandTable *, 8> MasterCommandTable;
typedef void (*TXFunction)(const char *data, int length);

class BusMessageProcessor {
  public:
    BusMessageProcessor(uint8_t device_address, MasterCommandTable &command_tables, TXFunction send_response);
    void processIncomingData(char c);
    void processQueuedMessage();
    void handleMessage(const BusMessage &msg, BusMessage &resp);

  private:
    uint8_t _device_address;
    // Buffers for incoming and outgoing messages
    char rx_buffer[255];
    char _tx_buffer[255];
    char _rx_message[254];
    char _tx_message[254];
    // State variables for message processing
    int _rx_buffer_pos = 0;
    int _msg_len = -1;

    // Reference to the master command table for dispatching commands
    MasterCommandTable &_command_tables;
    // Reference to sending function, to be set by the main firmware code to allow sending responses
    TXFunction _transmit_function;
};

#endif // MESSAGE_H