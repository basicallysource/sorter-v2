/*
 * Sorter Interface Firmware
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

#include <stdio.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/timer.h"

#include "Stepper.h"
#include "TMC_UART.h"
#include "TMC2209.h"

TMC_UART_Bus tmc_bus(uart0);
TMC2209 tmc_drivers[4] = {
    TMC2209(&tmc_bus, 0),
    TMC2209(&tmc_bus, 1),
    TMC2209(&tmc_bus, 2),
    TMC2209(&tmc_bus, 3)
};
Stepper steppers[4] = {
    Stepper(2, 3), // 28, 27 in final board
    Stepper(4, 5), // 26, 25 in final board
    Stepper(21, 20),
    Stepper(19, 18)
};

const int TMC_UART_TX_PIN = 0; // 16 on final board
const int TMC_UART_RX_PIN = 1; // 17 on final board
const int TMC_UART_BAUDRATE = 200000;

const int STEPPER_nEN_PIN = 6; // TBD on final board

const uint32_t STEP_TICK_PERIOD_US = 1000000 / STEP_TICK_RATE_HZ;
const uint32_t MOTION_UPDATE_PERIOD_US = 1000000 / STEP_MOTION_UPDATE_RATE_HZ;

void core1_stepgen_isr(uint alarm_num ) {
    // Core 1 step generator interrupt service routine, called at STEP_TICK_RATE_HZ
    hardware_alarm_set_target(alarm_num, time_us_64() + STEP_TICK_PERIOD_US);
    
    steppers[0].stepgen_tick();
    steppers[1].stepgen_tick();
    steppers[2].stepgen_tick();
    steppers[3].stepgen_tick();
}

void core1_motion_update_isr(uint alarm_num ) {
    // Core 1 motion update interrupt service routine, called at STEP_MOTION_UPDATE_RATE_HZ
    hardware_alarm_set_target(alarm_num, time_us_64() + MOTION_UPDATE_PERIOD_US);
    
    steppers[0].motion_update_tick();
    steppers[1].motion_update_tick();
    steppers[2].motion_update_tick();
    steppers[3].motion_update_tick();
}

void core1_entry() {
    // Core 1 main loop, this deals with high speed real-time tasks like stepper control.
    // Setup step generator timer interrupt
    hardware_alarm_claim(0);
    hardware_alarm_set_target(0, time_us_64() + STEP_TICK_PERIOD_US);
    hardware_alarm_set_callback(0, core1_stepgen_isr);
    // Setup motion update timer interrupt
    hardware_alarm_claim(1);
    hardware_alarm_set_target(1, time_us_64() + MOTION_UPDATE_PERIOD_US);
    hardware_alarm_set_callback(1, core1_motion_update_isr);

    while (true) {
        // Core 1 main loop does nothing, all work is done in interrupts
        tight_loop_contents();
    }
}


int main()
{
    stdio_init_all();
    // Initialize TMC UART bus
    tmc_bus.setupComm(TMC_UART_BAUDRATE, TMC_UART_TX_PIN, TMC_UART_RX_PIN);
    // Initialize TMC2209 drivers and steppers
    for (int i = 0; i < 4; i++) {
        //tmc_drivers[i].enableDriver(true);
        steppers[i].initialize();
        steppers[i].setAcceleration(20000);
        steppers[i].setSpeedLimits(16, 2000);
        tmc_drivers[i].initialize();
        tmc_drivers[i].enableDriver(true);
        tmc_drivers[i].setCurrent(31, 16, 10);
        tmc_drivers[i].setMicrosteps(MICROSTEP_8);
        tmc_drivers[i].enableStealthChop(true); 
    }
    gpio_init(STEPPER_nEN_PIN);
    gpio_set_dir(STEPPER_nEN_PIN, GPIO_OUT);
    gpio_put(STEPPER_nEN_PIN, 0); // Enable stepper drivers
    // Initialize Core 1
    multicore_launch_core1(core1_entry);

    int stepper_moves[4] = {5000, -3000, 1500, -2500};

    while (true) {
        // Main loop, this deals with communications and high level command processing
        // for now, try moving the steppers in a test pattern
        for (int i = 0; i < 1; i++) {
            if (steppers[i].moveSteps(stepper_moves[i])) {
                printf("Stepper %d moving %d steps\n", i, stepper_moves[i]);
                stepper_moves[i] = -stepper_moves[i]; // Reverse direction for next move
                if (stepper_moves[i] > 0) {
                    tmc_drivers[i].setMicrosteps(MICROSTEP_16);
                } else {
                    tmc_drivers[i].setMicrosteps(MICROSTEP_4);
                }
                // read the chopconf register to verify microstep setting
                TMC2209ChopperConfig chopconf;
                int res = tmc_bus.readRegister(i, TMC2209_Register::CHOPCONF, &chopconf.value);
                printf("Stepper %d CHOPCONF: 0x%08X, MRES: %d\n", i, chopconf.value, chopconf.mres);
            }
            
        }
    }
}
