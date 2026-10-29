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
| `aios-diag`: subir logs para soporte | Hecho. Recoge sistema, hardware, gráfica, logs de sway, journal (aios está en `systemd-journal`), llama y red (sin claves wifi) y sube un `.tar.gz` a `https://ccmai.org/aios-diag/upload`; `--local` solo lo guarda en `/tmp`. Token en `local/diag.token` (fuera de git) → `/etc/aios/diag.token`. Receptor: `scripts/diag-server.py` + `scripts/aios-diag-receiver.service` (127.0.0.1:8091, detrás de Apache), guarda en `~/aios-diag/` del VPS. Probado dentro de la imagen en QEMU. Receptor en marcha en el VPS (29 oct): servicio `aios-diag-receiver` y `ProxyPass /aios-diag/` en `ccmai.org-ssl.conf` (copia previa en `.bak-20261029`); probado por HTTPS |
| Aceleración por GPU | Hecho (29 oct), compila y arranca en QEMU; sin probar en hardware real. mesa 26.1.8 + LLVM 22: iris + crocus (Intel), radeonsi + r600 (AMD), nouveau, virgl, llvmpipe; firmware `xe` añadido. Compilación desde cero: 81 min. `aios-gpu-probe` abre el nodo de render de la GPU principal con GBM+EGL y lee el driver (`eglGetDisplayDriverName`): si es software (`kms_swrast`) o no inicializa, `aios-session` usa pixman; resultado en `~/.local/state/aios/gpu.log`. El reintento por log de sway queda como segunda red |
| Tildes en el teclado es | `/usr/share/X11/locale` con la tabla de Compose de libX11 1.8.13: sin ella xkbcommon no tenía teclas muertas y no se podía escribir «á» en foot |
| `aios-diag` mide la velocidad del modelo | `bench.txt`: una respuesta de 64 tokens con los `timings` de llama-server (tokens/s de prompt y de generación) |
| CLI `aios` (adelanto del hito 1) | Paquete Python en `/usr/lib/aios/aios`, contrato JSON (`--json` en cualquier posición; errores de uso e internos también en JSON). `aios net status`, `aios net wifi scan/connect/disconnect` (iwd por D-Bus con `busctl --json`; `iwctl` solo para entregar la contraseña) y `aios ui brightness [up/down/N]` (logind `SetBrightness`, mínimo 5 %) |
| Barra y teclas del portátil | `aios-status` en Python, un solo proceso: modelo, red (SSID o ETH), batería, RAM y hora. Teclas de brillo en sway |
| Chat: contexto y velocidad | `aios-chat` lee `n_ctx` de `/props`, olvida los turnos más antiguos por encima del 75 % (estimación calibrada con el `usage` del servidor) y, si llama-server aún rechaza por contexto, recorta y reintenta. tok/s de los `timings` del servidor. Probado contra el llama-server de la imagen en nativo con contexto 1024 |
| `aios update code` | `check / apply / rollback` desde git (`/etc/aios/update.conf`, por defecto el repo de GitHub, rama main). Solo el overlay; avisa de lo que necesita imagen nueva. Fusión a tres bandas por fichero (base = commit de `/etc/aios/build-info`): respeta cambios locales y deja `.aios-new` si chocan. Copia de todo en `/var/lib/aios/updates/` y `rollback` exacto. `apply` pide token (`--confirm`) o un sí en el terminal. Necesita root. Probado con un remoto y una raíz falsas: rollback idéntico byte a byte |
| `aios ai` y proveedores externos | `status / list / add / use / remove`. API compatible con OpenAI; clave en `Authorization: Bearer` o en otra cabecera (`--key-header X-API-Key`, como el servidor del VPS). Contexto: `/props` (llama.cpp), `/v1/models`, tabla de modelos o se pregunta (`--context`). `use` de un externo exige confirmación (los datos salen del equipo). `~/.config/aios/ai.json` en 0600. El chat usa el proveedor activo, vuelve al local si el remoto no responde y la barra muestra `AI REMOTE <nombre>` |
| `CTX=auto` en `llama.conf` | `aios-llama` calcula el contexto con los metadatos GGUF (`aios/gguf.py`: contexto de entrenamiento y caché KV por token; en Qwen3.5 solo 8 de 32 capas tienen KV, 32 KiB/token) y la RAM: RAM − 1,5 GiB − pesos − 0,5 GiB, con tope por velocidad de CPU (16K con < 12 GiB, 32K con más). 8 GB → 16K (igual que antes); 12 GB o más → 32K; poca RAM → menos. Si falla, 16384. Validado contra llama-server: KV 512 MiB a 16K y 2048 MiB a 64K (32 KiB/token exactos), búfer de cálculo fijo ~500 MiB, estado recurrente 50 MiB. Ojo: en CPU con AVX2 llama.cpp reordena pesos (`CPU_REPACK`, 1,3 GB anónimos) |
| SSH cerrado por defecto | `sshd` venía activado (preset de Buildroot) con el usuario `aios`/`aios` en wheel: cualquiera en la misma red entraba como administrador. Ahora `10-aios.preset` lo desactiva y `sshd_config` solo admite claves (sin contraseña ni root). Las claves de host se generan en el primer arranque. LLMNR y mDNS de systemd-resolved desactivados (puerto 5355 abierto a la red) |
| Arranque en el HP 15s | **Pendiente** |

## Decisiones ya tomadas

- Buildroot **2026.08.1**, toolchain glibc, CPU **x86-64 base** (corre en cualquier PC de 64 bits).
- llama.cpp del propio Buildroot (**b8117**) con `GGML_BACKEND_DL` + `GGML_CPU_ALL_VARIANTS`; `post-build.sh` mueve las variantes a `/usr/lib/ggml`. Comprobado en el código de b8117: ya trae la arquitectura `qwen35` y el proyector `qwen3vl_merger`, no hace falta subir versión.
- Modelo del hito 0: `unsloth/Qwen3.5-4B-GGUF`, cuantización **Q4_K_M (2,74 GB)** + proyector de visión (`mmproj`). Se deja en `models/` (fuera de git) y `post-build.sh` lo copia a `/usr/share/aios/models/`. Raíz ext4 de 7 GB para que quepa.
- Sesión gráfica: sway (lee configuración de i3) + foot; wlroots con renderizador por software si no hay GPU 3D. libseat usa logind (systemd), sin daemon seatd.
- Contexto local de 16K; puerto 8083 como en aios-lfs.
- **mesa con LLVM** (29 oct): iris y crocus (Intel), radeonsi (AMD) y llvmpipe lo exigen en mesa 26; iris además necesita el compilador precompilado (host-mesa3d + libclc). Buildroot descarta iris sin avisar si falta LLVM. Antes (28 oct) iba sin LLVM y en Intel y AMD moderna sway dibujaba con pixman.
- **Cada imagen para hardware real agrupa todos los cambios verificados**: el ciclo compilar → descargar → grabar USB → probar es largo. Verificar en el VPS todo lo posible antes (Kconfig, compilación, QEMU, scripts ejecutados dentro de la imagen).

## Ideas apuntadas (sin hacer)


## Lecciones de este hito

- Kconfig descarta en silencio las opciones cuyas dependencias faltan (pasó con `MESA3D_GALLIUM_DRIVER_IRIS` sin LLVM). Tras tocar el defconfig, comprobar que cada `BR2_...=y` sigue en `build/output/.config`.
- Con `BR2_PER_PACKAGE_DIRECTORIES`, cambiar la configuración de un paquete base (systemd, PAM) exige compilar desde cero (`make clean all`); con ccache son ~30 min.
- En `users.txt` de Buildroot 2026.08, uid `-1` = sistema y `-2` = usuario normal. Mejor fijarlo.
- **wlroots sí acepta llvmpipe** en máquinas virtuales: con `virtio_gpu` sin virgl, mesa cae a `kms_swrast` sobre el dispositivo de hardware, wlroots no lo detecta como software y sway dibuja con 4 hilos de llvmpipe. Por eso se pregunta a mesa el driver antes de arrancar sway, en vez de fiarse de wlroots. Comprobar el renderizador real por los hilos (`/proc/$(pgrep -x sway)/task/*/comm`).
- El userland de la imagen es BusyBox en parte (`tar` sin `-z`): un script que funciona en el VPS puede fallar en AIOS. Probarlo dentro de la imagen (consola serie de QEMU en un socket).
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
