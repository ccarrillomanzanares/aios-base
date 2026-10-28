# AIOS — atajos de compilación sobre Buildroot.
#   make            configura (la primera vez) y compila la imagen
#   make model      descarga Qwen3.5-4B a models/ (antes de 'make')
#   make qemu       arranca la imagen en QEMU (BIOS); 'make qemu-uefi' con OVMF
#   make menuconfig / savedefconfig / linux-menuconfig
#   make clean      borra build/output (no la descarga de Buildroot)

BR_VERSION  := 2026.08.1
BR_DIR      := $(CURDIR)/build/buildroot
OUT_DIR     := $(CURDIR)/build/output
DEFCONFIG   := aios_x86_64_defconfig
IMAGE       := $(OUT_DIR)/images/aios.img
# Todos los núcleos: con BR2_PER_PACKAGE_DIRECTORIES Buildroot compila varios
# paquetes a la vez y reparte el servidor de trabajos (-j) entre ellos.
JOBS        ?= $(shell nproc)
BR          := $(MAKE) -C $(BR_DIR) O=$(OUT_DIR) BR2_EXTERNAL=$(CURDIR)

# QEMU: memoria del perfil mínimo; QEMU_DISPLAY=vnc=:1 para un servidor sin pantalla
QEMU_MEM    ?= 8G
QEMU_SMP    ?= 4
QEMU_DISPLAY ?= gtk
OVMF_CODE   ?= $(firstword $(wildcard /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd))
OVMF_VARS   ?= $(firstword $(wildcard /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd /usr/share/edk2/x64/OVMF_VARS.4m.fd))
KVM         := $(if $(wildcard /dev/kvm),-enable-kvm -cpu host,-cpu max)
QEMU        := qemu-system-x86_64 $(KVM) -m $(QEMU_MEM) -smp $(QEMU_SMP) \
	-drive file=$(IMAGE),format=raw,if=virtio \
	-device virtio-vga -display $(QEMU_DISPLAY) \
	-nic user,model=virtio-net-pci,hostfwd=tcp::2222-:22 \
	-serial mon:stdio

.PHONY: all model qemu qemu-uefi menuconfig savedefconfig linux-menuconfig clean

all: $(OUT_DIR)/.config
	$(BR) -j$(JOBS)

$(BR_DIR)/Makefile:
	git clone --depth 1 -b $(BR_VERSION) https://gitlab.com/buildroot.org/buildroot.git $(BR_DIR)

$(OUT_DIR)/.config: $(BR_DIR)/Makefile
	$(BR) $(DEFCONFIG)

model:
	scripts/download-model.sh

qemu:
	@test -f $(IMAGE) || { echo "No image: run 'make' first"; exit 1; }
	$(QEMU)

qemu-uefi:
	@test -f $(IMAGE) || { echo "No image: run 'make' first"; exit 1; }
	@test -n "$(OVMF_CODE)" || { echo "OVMF not found (apt install ovmf)"; exit 1; }
	cp -n $(OVMF_VARS) $(OUT_DIR)/images/OVMF_VARS.fd
	$(QEMU) -drive if=pflash,format=raw,readonly=on,file=$(OVMF_CODE) \
		-drive if=pflash,format=raw,file=$(OUT_DIR)/images/OVMF_VARS.fd

menuconfig savedefconfig linux-menuconfig: $(OUT_DIR)/.config
	$(BR) $@

clean:
	rm -rf $(OUT_DIR)
