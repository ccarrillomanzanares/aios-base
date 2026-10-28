# Hito 0 — La base arranca

**Puerta:** la imagen arranca en QEMU y en el HP 15s, entra sola en una sesión sway con el tema WarGames, y `llama-server` sirve Qwen3.5-4B en `127.0.0.1:8083`.

Arquitectura completa: [ARQUITECTURA.md](ARQUITECTURA.md).

## Estado

| Pieza | Estado |
| --- | --- |
| `external.desc`, `external.mk`, `Config.in` | Hecho. `external.mk` activa todas las variantes de CPU de llama.cpp |
| `configs/aios_x86_64_defconfig` | Hecho, sin compilar todavía (Buildroot 2026.08.1) |
| Kernel 6.18.10: base de newos + `board/aios/kernel/aios.fragment` | Hecho |
| GRUB BIOS + UEFI, `genimage.cfg`, `post-build.sh`, `post-image.sh` | Hecho (adaptado de newos) |
| Usuario `aios` y autologin en tty1 | Hecho |
| Sesión: `.bash_profile` → `aios-session` → sway + foot | **Pendiente** |
| Tema WarGames de sway y foot | **Pendiente** |
| `aios-llama.service` + `/etc/aios/llama.conf` + `aios-llama` | **Pendiente** |
| `aios-chat` (chat mínimo contra llama-server, saludo WarGames) | **Pendiente** |
| Red: `systemd-networkd` (cable) + `iwd` (wifi) | **Pendiente** (`/etc/systemd/network/*.network`) |
| `/etc/sudoers.d/wheel`, `/etc/locale.conf`, `/etc/vconsole.conf` (es) | **Pendiente** |
| `Makefile` (`make`, `make model`, `make qemu`) y `scripts/download-model.sh` | **Pendiente** |

## Decisiones ya tomadas

- Buildroot **2026.08.1**, toolchain glibc, CPU **x86-64 base** (corre en cualquier PC de 64 bits).
- llama.cpp del propio Buildroot (**b8117**) con `GGML_BACKEND_DL` + `GGML_CPU_ALL_VARIANTS`; `post-build.sh` mueve las variantes a `/usr/lib/ggml`. **Comprobar que b8117 carga Qwen3.5**; si no, subir la versión.
- Modelo del hito 0: `unsloth/Qwen3.5-4B-GGUF`, cuantización **Q4_K_M (2,74 GB)** + proyector de visión (`mmproj`). Se deja en `models/` (fuera de git) y `post-build.sh` lo copia a `/usr/share/aios/models/`. Raíz ext4 de 7 GB para que quepa.
- Sesión gráfica: sway (lee configuración de i3) + foot; wlroots con renderizador por software si no hay GPU 3D. libseat usa logind (systemd), sin daemon seatd.
- Contexto local de 16K; puerto 8083 como en aios-lfs.

## Lecciones heredadas de newos (no repetir)

- Sin initramfs: los controladores de disco y USB deben ir `=y` en el kernel o la raíz no aparece (pantalla negra).
- GRUB en UEFI lee `/EFI/BOOT/grub.cfg`: el de Buildroot apunta a la partición FAT y da pantalla negra.
- Scripts editados en Windows: normalizar CRLF y dar `chmod +x` **después**.
- El `grub.cfg` genérico de Buildroot en la raíz confunde la búsqueda de GRUB: se borra.

## Compilar (en el VPS)

```bash
git clone https://github.com/ccarrillomanzanares/aios-base && cd aios-base
git clone --depth 1 -b 2026.08.1 https://gitlab.com/buildroot.org/buildroot.git build/buildroot
make -C build/buildroot O=$PWD/build/output BR2_EXTERNAL=$PWD aios_x86_64_defconfig
make -C build/buildroot O=$PWD/build/output -j$(nproc)
```

La imagen queda en `build/output/images/aios.img`.
