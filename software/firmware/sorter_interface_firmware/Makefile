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

.PHONY: setup build \
        build-feeder-v1-1 build-distribution-v1-1 flash-feeder-v1-1 flash-distribution-v1-1 \
        build-feeder-v1-2 build-distribution-v1-2 flash-feeder-v1-2 flash-distribution-v1-2 \
        build-distribution-skr

setup: $(PICO_SDK_PATH)/pico_sdk_init.cmake

$(PICO_SDK_PATH)/pico_sdk_init.cmake:
	@mkdir -p $(PICO_DEPS_DIR)
	git clone --depth 1 --branch $(PICO_SDK_VERSION) https://github.com/raspberrypi/pico-sdk $(PICO_SDK_PATH)
	cd $(PICO_SDK_PATH) && git submodule update --init --depth 1

build: build-feeder-v1-1 build-distribution-v1-1

build-feeder-v1-1: setup
	@mkdir -p build-feeder-v1-1
	@cd build-feeder-v1-1 && CC=$(HOST_CC) CXX=$(HOST_CXX) cmake -DFIRMWARE_ROLE=feeder -DHW_BASICALLY_V1_1=ON $(CMAKE_FLAGS) .. && CC=$(HOST_CC) CXX=$(HOST_CXX) make -j$(NPROC)
	@echo "Feeder v1-1 firmware built: build-feeder-v1-1/sorter_interface_firmware.uf2"

build-distribution-v1-1: setup
	@mkdir -p build-distribution-v1-1
	@cd build-distribution-v1-1 && CC=$(HOST_CC) CXX=$(HOST_CXX) cmake -DFIRMWARE_ROLE=distribution -DHW_BASICALLY_V1_1=ON $(CMAKE_FLAGS) .. && CC=$(HOST_CC) CXX=$(HOST_CXX) make -j$(NPROC)
	@echo "Distribution v1-1 firmware built: build-distribution-v1-1/sorter_interface_firmware.uf2"

flash-feeder-v1-1: build-feeder-v1-1
	python3 flash.py --board feeder --uf2 build-feeder-v1-1/sorter_interface_firmware.uf2

flash-distribution-v1-1: build-distribution-v1-1
	python3 flash.py --board distribution --uf2 build-distribution-v1-1/sorter_interface_firmware.uf2

build-feeder-v1-2: setup
	@mkdir -p build-feeder-v1-2
	@cd build-feeder-v1-2 && CC=$(HOST_CC) CXX=$(HOST_CXX) cmake -DFIRMWARE_ROLE=feeder -DHW_BASICALLY_V1_2=ON $(CMAKE_FLAGS) .. && CC=$(HOST_CC) CXX=$(HOST_CXX) make -j$(NPROC)
	@echo "Feeder v1-2 firmware built: build-feeder-v1-2/sorter_interface_firmware.uf2"

build-distribution-v1-2: setup
	@mkdir -p build-distribution-v1-2
	@cd build-distribution-v1-2 && CC=$(HOST_CC) CXX=$(HOST_CXX) cmake -DFIRMWARE_ROLE=distribution -DHW_BASICALLY_V1_2=ON $(CMAKE_FLAGS) .. && CC=$(HOST_CC) CXX=$(HOST_CXX) make -j$(NPROC)
	@echo "Distribution v1-2 firmware built: build-distribution-v1-2/sorter_interface_firmware.uf2"

flash-feeder-v1-2: build-feeder-v1-2
	python3 flash.py --board feeder --uf2 build-feeder-v1-2/sorter_interface_firmware.uf2

flash-distribution-v1-2: build-distribution-v1-2
	python3 flash.py --board distribution --uf2 build-distribution-v1-2/sorter_interface_firmware.uf2

build-distribution-skr: setup
	@mkdir -p build-distribution-skr
	@cd build-distribution-skr && CC=$(HOST_CC) CXX=$(HOST_CXX) cmake -DFIRMWARE_ROLE=distribution -DHW_SKR_PICO=ON $(CMAKE_FLAGS) .. && CC=$(HOST_CC) CXX=$(HOST_CXX) make -j$(NPROC)
	@echo "Distribution SKR Pico firmware built: build-distribution-skr/sorter_interface_firmware.uf2"
