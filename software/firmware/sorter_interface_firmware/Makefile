NPROC := $(shell sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PICO_SDK_VERSION := 2.2.0
PICO_DEPS_DIR := $(shell pwd)/.pico-deps
PICO_SDK_PATH := $(PICO_DEPS_DIR)/pico-sdk
PICOTOOL_CACHE := $(PICO_DEPS_DIR)/picotool
CMAKE_FLAGS := -DPICO_SDK_PATH=$(PICO_SDK_PATH) -DPICOTOOL_FETCH_FROM_GIT_PATH=$(PICOTOOL_CACHE)
HOST_CC := $(shell which clang 2>/dev/null || echo cc)
HOST_CXX := $(shell which clang++ 2>/dev/null || echo c++)
HOMEBREW_LLVM := /opt/homebrew/opt/llvm/bin
ifneq ($(wildcard $(HOMEBREW_LLVM)/clang),)
	HOST_CC := $(HOMEBREW_LLVM)/clang
	HOST_CXX := $(HOMEBREW_LLVM)/clang++
endif

.PHONY: setup build-feeder build-distribution flash-feeder flash-distribution build \
        build-feeder-v1 build-distribution-v1 flash-feeder-v1 flash-distribution-v1

setup: $(PICO_SDK_PATH)/pico_sdk_init.cmake

$(PICO_SDK_PATH)/pico_sdk_init.cmake:
	@mkdir -p $(PICO_DEPS_DIR)
	git clone --depth 1 --branch $(PICO_SDK_VERSION) https://github.com/raspberrypi/pico-sdk $(PICO_SDK_PATH)
	cd $(PICO_SDK_PATH) && git submodule update --init --depth 1

build: build-feeder build-distribution

build-feeder: setup
	@mkdir -p build-feeder
	@cd build-feeder && CC=$(HOST_CC) CXX=$(HOST_CXX) cmake -DFIRMWARE_ROLE=feeder $(CMAKE_FLAGS) .. && CC=$(HOST_CC) CXX=$(HOST_CXX) make -j$(NPROC)
	@echo "Feeder firmware built: build-feeder/sorter_interface_firmware.uf2"

build-distribution: setup
	@mkdir -p build-distribution
	@cd build-distribution && CC=$(HOST_CC) CXX=$(HOST_CXX) cmake -DFIRMWARE_ROLE=distribution $(CMAKE_FLAGS) .. && CC=$(HOST_CC) CXX=$(HOST_CXX) make -j$(NPROC)
	@echo "Distribution firmware built: build-distribution/sorter_interface_firmware.uf2"

flash-feeder: build-feeder
	cp build-feeder/sorter_interface_firmware.uf2 /Volumes/RPI-RP2/
	@echo "Feeder firmware flashed."

flash-distribution: build-distribution
	cp build-distribution/sorter_interface_firmware.uf2 /Volumes/RPI-RP2/
	@echo "Distribution firmware flashed."


