# Generated Cmake Pico project file

cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Initialise pico_sdk from installed location
# (note this can come from environment, CMake cache etc)

# == DO NOT EDIT THE FOLLOWING LINES for the Raspberry Pi Pico VS Code Extension to work ==
if(WIN32)
    set(USERHOME $ENV{USERPROFILE})
else()
    set(USERHOME $ENV{HOME})
endif()
set(sdkVersion 2.2.0)
set(toolchainVersion 14_2_Rel1)
set(picotoolVersion 2.2.0-a4)
set(picoVscode ${USERHOME}/.pico-sdk/cmake/pico-vscode.cmake)
if (EXISTS ${picoVscode})
    include(${picoVscode})
endif()
# ====================================================================================
set(PICO_BOARD pico CACHE STRING "Board type")

# Pull in Raspberry Pi Pico SDK (must be before project)
include(pico_sdk_import.cmake)

project(sorter_interface_firmware C CXX ASM)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

option(HW_SKR_PICO "Compile for SKR Pico hardware" OFF)
set(INIT_DEVICE_NAME "FEEDER MB" CACHE STRING "Device Name for the firmware to use on startup")
set(INIT_DEVICE_ADDRESS "0x00" CACHE STRING "Device Address in the bus")

# Add executable. Default name is the project name, version 0.1

add_executable(sorter_interface_firmware 
    sorter_interface_firmware.cpp 
    TMC2209.cpp 
    TMC_UART.cpp
    Stepper.cpp 
    cobs.c 
    crc.c 
    message.cpp 
    PCA9685.cpp
    Servo.cpp
)

pico_set_program_name(sorter_interface_firmware "sorter_interface_firmware")
pico_set_program_version(sorter_interface_firmware "0.1")

# Modify the below lines to enable/disable output over UART/USB
pico_enable_stdio_uart(sorter_interface_firmware 0)
pico_enable_stdio_usb(sorter_interface_firmware 1)

# Add the standard library to the build
target_link_libraries(sorter_interface_firmware
        pico_stdlib)

# Add the standard include files to the build
target_include_directories(sorter_interface_firmware PRIVATE
        ${CMAKE_CURRENT_LIST_DIR}
)

# Pass INIT_DEVICE_NAME and INIT_DEVICE_ADDRESS as preprocessor definitions
target_compile_definitions(sorter_interface_firmware PRIVATE INIT_DEVICE_NAME="${INIT_DEVICE_NAME}" INIT_DEVICE_ADDRESS=${INIT_DEVICE_ADDRESS})
if (HW_SKR_PICO)
    target_compile_definitions(sorter_interface_firmware PRIVATE HW_SKR_PICO)
endif()

# Add any user requested libraries
target_link_libraries(sorter_interface_firmware
        pico_multicore
        pico_stdlib
        pico_time
        hardware_i2c
        hardware_timer
        )

pico_add_extra_outputs(sorter_interface_firmware)

