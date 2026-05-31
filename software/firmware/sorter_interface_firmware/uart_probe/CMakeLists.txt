cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

include(${CMAKE_CURRENT_LIST_DIR}/../pico_sdk_import.cmake)

project(uart_probe C CXX ASM)

pico_sdk_init()

add_executable(uart_probe uart_probe.cpp)

pico_set_program_name(uart_probe "uart_probe")

# Diagnostics go over USB CDC; physical UART pins stay free for the buses.
pico_enable_stdio_uart(uart_probe 0)
pico_enable_stdio_usb(uart_probe 1)

# Per the doc's SDK guidance: keep the SDK's "default UART" definitions from
# silently grabbing pins we drive ourselves. stdio_uart is already disabled
# above, so nothing routes stdout to a physical UART; pin these defaults to our
# UART0 pair explicitly to document intent and avoid any default-pin conflict.
target_compile_definitions(uart_probe PRIVATE
    PICO_DEFAULT_UART=0
    PICO_DEFAULT_UART_TX_PIN=16
    PICO_DEFAULT_UART_RX_PIN=17
)

target_link_libraries(uart_probe
    pico_stdlib
    hardware_uart
    hardware_gpio
)

pico_add_extra_outputs(uart_probe)
