# Hito 0 — La base arranca

**Puerta:** ~~QEMU~~ hecho; falta el HP 15s. La imagen arranca en QEMU y en el HP 15s, entra sola en una sesión sway con el tema WarGames, y `llama-server` sirve Qwen3.5-4B en `127.0.0.1:8083`.

Arquitectura completa: [ARQUITECTURA.md](ARQUITECTURA.md).

## Estado

| Pieza | Estado |
| --- | --- |
| `external.desc`, `external.mk`, `Config.in` | Hecho. `external.mk` activa todas las variantes de CPU de llama.cpp |
| `configs/aios_x86_64_defconfig` | Hecho, sin compilar todavía (Buildroot 2026.08.1); añadido `SYSTEMD_VCONSOLE` |
| Kernel 6.18.10: base de newos + `board/aios/kernel/aios.fragment` | Hecho |
| GRUB BIOS + UEFI, `genimage.cfg`, `post-build.sh`, `post-image.sh` | Hecho (adaptado de newos) |
| Usuario `aios` y autologin en tty1 | Hecho |
| Sesión: `.bash_profile` → `aios-session` → sway + foot | Hecho. Sin nodo `renderD*` usa `WLR_RENDERER=pixman`; si hay nodo pero mesa no tiene driver (Intel sin iris) y sway no crea el renderizador, reintenta con pixman (log de EGL en `sway-egl.log`); si sway falla deja una shell en tty1 y el log en `~/.local/state/aios/sway.log` |
| Tema WarGames de sway y foot | Hecho: `/etc/sway/config` (atajos de aios-lfs), `/etc/aios/theme/sway.conf`, `/etc/xdg/foot/foot.ini` (`[colors-dark]`, foot 1.26), barra `aios-status` |
| `aios-llama.service` + `/etc/aios/llama.conf` + `aios-llama` | Hecho. `DynamicUser`, hilos = núcleos físicos, `-np 1 --jinja --mmproj`; autodetecta el modelo si falta el configurado |
| `aios-chat` (chat mínimo contra llama-server, saludo WarGames) | Hecho, solo biblioteca estándar; streaming SSE, sin razonamiento (`enable_thinking: false`). Probado contra un servidor simulado |
| Red: `systemd-networkd` (cable) + `iwd` (wifi) | Hecho: `20-wired.network`, `25-wireless.network`; iwd solo asocia (`EnableNetworkConfiguration=false`) |
| `/etc/sudoers.d/wheel`, `/etc/locale.conf`, `/etc/vconsole.conf` (es) | Hecho |
| `Makefile` (`make`, `make model`, `make qemu`, `make qemu-uefi`) y `scripts/download-model.sh` | Hecho. El `mmproj` se guarda como `Qwen3.5-4B-mmproj-F16.gguf` |
| Primera compilación y arranque en QEMU | **Hecho (28 oct).** Compilación desde cero: ~1 h 20 min la primera vez en el VPS (16 vCPU), 27 min con ccache. En QEMU, BIOS y UEFI: GRUB → kernel → systemd → autologin → sway + foot con tema WarGames → `aios-chat` responde en español en streaming. `llama-server` carga Qwen3.5-4B + mmproj en ~30 s; ggml elige la variante de CPU solo; ~3,1 GB de RAM usados con el modelo cargado |
| Arreglos que salieron al arrancar | PAM (`linux-pam`, `login` de util-linux, `/etc/pam.d/login` con `pam_systemd`): sin él no había sesión de logind y sway no tenía asiento. uid/gid de `aios` fijos en 1000 (en mkusers `-1` es uid de sistema → sesión `user-light` sin `systemd --user`). `LANG` de la sesión desde `locale.conf` con `pam_env` |
| Arranque en el HP 15s | **Pendiente** |

## Decisiones ya tomadas

- Buildroot **2026.08.1**, toolchain glibc, CPU **x86-64 base** (corre en cualquier PC de 64 bits).
- llama.cpp del propio Buildroot (**b8117**) con `GGML_BACKEND_DL` + `GGML_CPU_ALL_VARIANTS`; `post-build.sh` mueve las variantes a `/usr/lib/ggml`. Comprobado en el código de b8117: ya trae la arquitectura `qwen35` y el proyector `qwen3vl_merger`, no hace falta subir versión.
- Modelo del hito 0: `unsloth/Qwen3.5-4B-GGUF`, cuantización **Q4_K_M (2,74 GB)** + proyector de visión (`mmproj`). Se deja en `models/` (fuera de git) y `post-build.sh` lo copia a `/usr/share/aios/models/`. Raíz ext4 de 7 GB para que quepa.
- Sesión gráfica: sway (lee configuración de i3) + foot; wlroots con renderizador por software si no hay GPU 3D. libseat usa logind (systemd), sin daemon seatd.
- Contexto local de 16K; puerto 8083 como en aios-lfs.
- **mesa sin LLVM** en el hito 0: solo r600, virgl y softpipe. En mesa 26, iris, crocus e i915 (Intel) exigen LLVM, y Buildroot descarta iris sin avisar si falta. En Intel (incluido el HP 15s), sway dibuja con pixman. **Pendiente:** decidir si se activa `BR2_PACKAGE_MESA3D_LLVM` + iris (más tiempo de compilación, y lo pedirá el navegador).

## Lecciones de este hito

- Kconfig descarta en silencio las opciones cuyas dependencias faltan (pasó con `MESA3D_GALLIUM_DRIVER_IRIS` sin LLVM). Tras tocar el defconfig, comprobar que cada `BR2_...=y` sigue en `build/output/.config`.
- Con `BR2_PER_PACKAGE_DIRECTORIES`, cambiar la configuración de un paquete base (systemd, PAM) exige compilar desde cero (`make clean all`); con ccache son ~30 min.
- En `users.txt` de Buildroot 2026.08, uid `-1` = sistema y `-2` = usuario normal. Mejor fijarlo.
- QEMU en el VPS va sin KVM: la velocidad del modelo ahí (~0,4 tok/s) no dice nada; medir en hardware real.

## Lecciones heredadas de newos (no repetir)

- Sin initramfs: los controladores de disco y USB deben ir `=y` en el kernel o la raíz no aparece (pantalla negra).
- GRUB en UEFI lee `/EFI/BOOT/grub.cfg`: el de Buildroot apunta a la partición FAT y da pantalla negra.
- Scripts editados en Windows: normalizar CRLF y dar `chmod +x` **después**.
- El `grub.cfg` genérico de Buildroot en la raíz confunde la búsqueda de GRUB: se borra.

## Compilar (en el VPS)

```bash
git clone https://github.com/ccarrillomanzanares/aios-base && cd aios-base
make model   # Qwen3.5-4B Q4_K_M + mmproj a models/ (~3,4 GB)
make         # clona Buildroot 2026.08.1 en build/buildroot la primera vez
make qemu    # o 'make qemu-uefi'; QEMU_DISPLAY=vnc=:1 en un servidor sin pantalla
```

La imagen queda en `build/output/images/aios.img`.
