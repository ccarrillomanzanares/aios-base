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
| Sonido para todas las aplicaciones | PipeWire + WirePlumber como servicios de usuario; ALSA (`pipewire-alsa`, dispositivo `default`), PulseAudio (`pipewire-pulse` y `libpulse` para las apps que la cargan; el demonio PulseAudio enmascarado). Firmware SOF (`package/sof-bin`) y perfiles UCM (`package/alsa-ucm-conf`) para el DSP y micrófonos digitales de Intel. `aios audio status/volume/mute [--mic]/test`, teclas multimedia y `VOL` en la barra. Sin JACK |
| Voz | Pulsar y mantener Super+Espacio (o `/voice` en el chat): `pw-record` 16 kHz → whisper.cpp (`package/whisper-cpp`, en `/opt/whisper` con su propio ggml 0.26 y variantes de CPU; el de llama.cpp es 0.9.x) con el modelo small q5_1 (~190 MB, `make model`) → el texto llega al chat (SIGUSR1). Respuesta hablada con espeak en el idioma detectado; `/speak on` para todas. `● REC` en la barra al grabar |
| Pantalla: capturas y `look` | Impr Pant → `aios-screenshot` (`grim`, paquete propio) en `~/Pictures/Screenshots`; `aios-diag` sube las 3 últimas (`--no-screenshots` para no). `/look [pregunta]`, `aios ai look` y la herramienta `look` del agente: captura reducida a 1024 px y pregunta al modelo local con su proyector de visión |
| Agente v0 en el chat | Herramientas `aios` (la CLI, JSON) y `look`. Las consultas se ejecutan solas; lo que cambia algo pide confirmación (y el token del contrato cuando la orden lo exige). Turnos recortados enteros. Si el proveedor no admite herramientas, sigue sin ellas |
| Historial del chat | `~/.local/share/aios/chats/*.json`; `/history` y `/resume [n]` |
| Primer arranque | `aios-firstboot` antes del chat: contraseña propia (vía `chpasswd`, nunca en la línea de órdenes) y bloqueo de root; wifi si no hay red. Marca en `~/.local/state/aios/firstboot-done` |
| Actualizaciones firmadas | `aios update code` por defecto en el canal `release`: solo etiquetas `v*` firmadas con SSH (clave en `/etc/aios/update-signers`; la privada en el VPS, `~/.ssh/aios-release`), nunca baja de versión. `CHANNEL=main` para desarrollo, sin firma. `scripts/release.sh vX.Y.Z` firma una versión |
| `make test` | `tests/run.py`: fase native (binarios de la imagen en el VPS: agente con herramientas, `look`, voz, proveedor externo) y vm (QEMU snapshot: `tests/vm-checks.sh` por consola serie con wifi virtual, sonido grabado por QEMU, capturas, diag, actualización, primer arranque). Resultados en `build/test-results/` |
| Pantallas | `aios ui display list/on/off/mode/scale/extend/mirror`: swaymsg; cada elección se guarda por monitor (marca, modelo, serie) en `~/.config/sway/config.d/50-aios-displays.conf`; nunca apaga la última pantalla; duplicar con `wl-mirror` (paquete propio) |
| Bloqueo e inactividad | `swaylock` + `swayidle` (paquetes propios): bloqueo a los 5 min, pantalla apagada a los 10, bloqueo antes de suspender (tapa). Super+Ctrl+L. Tema en `/etc/swaylock/config` |
| Notificaciones | `mako` (paquete propio), tema en `/etc/xdg/mako/config`; `aios/notify.py` por D-Bus estándar. Batería baja al 10 % y 5 %: notificación y aviso hablado, una vez por umbral |
| Bluetooth | BlueZ (cliente, audio, HID, HOG) + firmware Intel, Realtek, MediaTek y Qualcomm. `aios bt status/on/off/scan/connect/disconnect/remove` por D-Bus; emparejar en modo Just Works (teclados con PIN, pendiente). Los auriculares salen solos en PipeWire |
| Primer arranque completo | Idioma (`/etc/locale.conf`), teclado (sway al momento + consola), zona horaria, contraseña y red. Locales generados: es, en, ca, fr, de, it, pt |
| Autoprueba de hardware | `aios sys selftest` (y dentro de `aios-diag`): CPU, GPU, pantallas, brillo, batería con desgaste, wifi, Bluetooth, sonido (tono de 1 kHz por el altavoz buscado en lo que graba el micrófono, Goertzel), modelo y voz (espeak → whisper, con tiempo) |
| Arranque en el HP 15s | **Hecho** (29 oct, USB, UEFI): autoprueba 10/10 sin fallos (iris, 2 pantallas, wifi, Bluetooth, batería, modelo, voz); dos `aios-diag` en `~/aios-diag/` del VPS. Lo que salió y su arreglo, en «Primer arranque en el HP» |

## Traspaso (29 oct, noche) — leer primero

Sesión de la noche: primeros arranques en el HP 15s (2019) y en el HP 15-ba (antiguo), arreglos y proveedores de IA. Detalle en las secciones «Primer arranque en el HP 15s», «Portátil antiguo» y «Cortafuegos y proveedores de IA».

- **Imagen publicada** (30 oct, 08:01): commit `dbd89d6` (`DIRTY=no`), `make test` 92/92. Lleva todas las mejoras de la noche del 29 al 30 y, al 3 % de batería sin cargador, aviso en pantalla y voz y suspensión al minuto (se cancela al enchufar). `https://ccmai.org/aios/releases/aios.img.xz`, sha256 `6d39e335d12eac0afea65a6e2124dcf63b2f78297ce2a703a2286cb441056097`. Las anteriores quedan en `build/aios-d89c73c.img.xz` y `build/aios-17h55.img.xz`.
- **Push pendiente**: este VPS no tiene credenciales de GitHub; el push lo hace el usuario (GitHub sigue en `148c7e6`).
- **Pendiente de confirmar en el HP 15s con la imagen nueva**: beep y micrófono (si fallan, el diag trae ahora `audio-codec.txt` y `audio-alsa.txt`), velocidad entre mensajes (plantilla estable), wifi desde el agente (contraseña sin eco), bloqueo de pantalla, `/pair` con el servidor de ccmai.org (primera prueba con una clave real). En el HP 15-ba: que sway arranque (espera a udev en `aios-session`).
- **VPS**: el receptor (`aios-diag-receiver`) sirve también el emparejamiento (`/aios-diag/pair`); se reinicia con `sudo systemctl restart aios-diag-receiver` tras tocar `diag-server.py` o `pair.html`. El llama-server de Docker con Caddy (`llama-qwen`, `llama-proxy`, `webuillama.ccmai.org:8443`) es del proyecto **llama-hardened**: no tocarlo ni usar sus claves.
- **Siguiente: instalador a disco** (decidido con el usuario): borra el disco entero, se probará en el HP 15-ba (tiene una versión antigua de AIOS que se puede perder). Diseño propuesto:
  - `aios-install` (o `aios sys install`) desde el USB: elige disco (nunca el del propio USB), confirmación escribiendo el nombre del disco, resumen de lo que se borra.
  - GPT con partición BIOS boot (GRUB i386-pc) + ESP FAT (GRUB EFI, kernel, `grub.cfg`), para BIOS y UEFI como el USB.
  - Raíz A y raíz B (ext4, mismo tamaño que la del USB o más): se copia la A; la B queda vacía para RAUC (hito 4). `grub.cfg` con slot por defecto en una variable de entorno de GRUB, para que A/B encaje después.
  - `/home` en LUKS2 (cryptsetup), desbloqueo al arrancar con systemd-cryptsetup (pide la frase en tty1 antes de la sesión). La raíz no se cifra: no hay initramfs (lección de newos).
  - Paquetes a revisar: `cryptsetup`, `BR2_PACKAGE_SYSTEMD_CRYPTSETUP` (o equivalente en 2026.08), `dosfstools`, `e2fsprogs`, `gptfdisk`/`sfdisk`, kernel con `DM_CRYPT` y AES/XTS `=y`.
  - Probar primero en QEMU con un disco virtual extra (BIOS y UEFI), añadirlo a `make test`, y solo después al portátil.
- **Sin push** a GitHub (sigue en `148c7e6`); no hacer push sin que lo pida el usuario.

## Noche del 29 al 30 oct: mejoras en la rama `mejoras-termica-bateria-updates`

Hechas mientras el usuario dormía, a petición suya, **fuera de la imagen publicada** esa noche (la de `d89c73c`). Cada una con pruebas por partes y comprobaciones nuevas en `make test`; la imagen con todo se compila y prueba después de publicar la otra.

| Mejora | Qué hace |
|---|---|
| Temperatura (6) | `aios sys thermal` (coretemp/k10temp/zonas, contadores de estrangulamiento de Intel, frecuencia); autoprueba; barra `CPU 71°C` / `HOT` / `THROTTLED`, aviso a 95 °C; consulta del agente |
| Perfil de batería (7) | `aios-power.service` + regla udev: con batería, EPP `balance_power`, brillo ≤ 60 % (vuelve al enchufar si no se tocó) y modelo con la mitad de hilos (reinicia llama-server solo si está ocioso; si no, reintenta al minuto). `/etc/aios/power.conf`, `aios sys power` |
| Aviso de actualizaciones (8) | `aios update code notify` + `aios-update-check.timer` diario: avisa una vez por versión, nunca instala; `AUTO_CHECK=no` |
| Recordatorios (4) | `aios remind add/list/cancel`, temporizadores de usuario con hora absoluta, aviso en pantalla y voz, `restore` al entrar en sway (avisa de los perdidos); el agente los crea sin confirmación |
| Portapapeles (5) y dictado (3) | Paquetes propios `wl-clipboard` 2.3.0 y `wtype` 0.5. Herramienta `clipboard` del agente (con proveedor remoto pregunta antes de enviar); dictado con Super+Ctrl+Espacio (`aios-voice dictate`) |
| Swap en RAM | `aios-zram.service`: zram de la mitad de la RAM (≤ 8 GiB), swappiness 150 |
| Prompt fijo procesado de antemano | `aios-chat` procesa sistema + herramientas en segundo plano al abrirse, mientras el usuario escribe: el primer mensaje procesa ~15 tokens en vez de ~900 (en el HP 15s, ~50 s menos de espera). Guardarlo en disco para que dure entre reinicios (restaurar: 10 ms) **no funciona con el proyector de visión cargado**: llama.cpp b8117 responde 501 «not supported by multimodal», y en AIOS siempre lo está. Queda intentado (`--slot-save-path`); funcionará si una versión nueva de llama.cpp lo admite o si se separa la visión |
| Batería y memoria | Tiempo restante en la barra; suspensión al 3 % sin cargador; `OOMScoreAdjust=500` en el modelo |
| Diag y pruebas | Diag con swap/zram, temperatura, energía y recordatorios. QEMU: emparejamiento de punta a punta y wifi del agente con contraseña sin eco; native: llama-server como `aios-llama` y caché del prompt |

**Estado (30 oct, 02:00)**: rama fusionada en `main` (fast-forward, sin push). Imagen de `e1ca6cd` compilada y `make test` **92/92** (native + QEMU). **No publicada**: la publicada sigue siendo la de `d89c73c`. Encontrado y corregido por el camino: `aios-zram.service` creaba un ciclo de arranque con `tmp.mount` (systemd descartaba el montaje de `/tmp` y luego bluetooth.service lo montaba encima de lo que hubiera); nueva prueba `boot-no-cycles`. Las comprobaciones de la VM se ejecutan ahora desde un fichero con la entrada en `/dev/null`.

Pendiente de probar en hardware: todo lo anterior. Decidido con el usuario (30 oct): suspensión al 3 % con aviso previo; el dictado se queda en Super+Ctrl+Espacio.

## Traspaso anterior (29 oct, fin de la sesión larga)

Para retomar en una sesión nueva: leer esta sección, la tabla de estado y `git log`.

- **Hecho y probado** (tabla de arriba). Pruebas: `make test` (fase native: binarios de la imagen en el VPS; fase vm: QEMU). Última pasada antes de la compilación final: native 8/8, vm 40/43, y los 3 fallos (faltaba `chpasswd` en BusyBox; comprobaciones de root) corregidos en el commit siguiente.
- **29 oct, tarde**: compilación final hecha (53 min). `make test`: native 8/8, vm 53/53 tras corregir `aios-firstboot` (`sudo -k -S`: con la contraseña en la caché de sudo, la línea de la contraseña le llegaba a `chpasswd` y el cambio fallaba si antes se elegía idioma o zona), `aios bt` (sin `/sys/class/bluetooth` es `BT_NO_ADAPTER`, no servicio caído) y tres pruebas (swayidle apaga la pantalla de la VM antes de la captura; la imagen no trae `locale`; Bluetooth sin adaptador).
- **Imagen para el HP publicada** (29 oct, 17:55): `/var/www/ccmai.org/aios/releases/aios.img.xz` (+ `.sha256`), sacada del commit de estas correcciones. El usuario la prueba antes de seguir con las mejoras.
- **Sin publicar**: commits locales sin push (`git log origin/main..main`; GitHub va en `148c7e6`); el `aios.img.xz` publicado es del 29 oct (arriba). No hacer push ni regenerar/publicar el `.xz` sin que lo pida el usuario. `aios update code` en el HP no verá nada hasta que haya push y una versión firmada (`scripts/release.sh vX.Y.Z`, clave `~/.ssh/aios-release` en el VPS).
- **VPS**: receptor de `aios-diag` activo (`aios-diag-receiver`, Apache `/aios-diag/` en ccmai.org; paquetes en `~/aios-diag/`). En el VPS corre además otro llama-server con Qwen3.6-35B (Docker, `llama-qwen`, tras Caddy en :8443 con `X-API-Key`): no usar su clave sin permiso.
- **Siguiente paso del hito 0**: arrancar en el HP 15s, ejecutar `aios-diag` (sube autoprueba, capturas y logs) y revisar aquí lo que llegue.
- **Pendiente de decidir con el usuario**: las «Mejoras propuestas» de abajo (las pidió para revisarlas).

## Primer arranque en el HP 15s (29 oct, noche)

HP Laptop 15s-fq1xxx, i5-1035G1 (Ice Lake, AVX-512), 7,5 GiB, ALC236 por HDA clásico (el micrófono interno es el pin 0x12 del códec, no hace falta SOF). Modelo: 13,8-24 tok/s de prompt y 3,5-4,1 tok/s de generación con 4 hilos.

| Hallazgo | Causa | Arreglo (pendiente de probar en el HP) |
|---|---|---|
| Sin micrófono (`WARN sound`; PipeWire sin ninguna fuente, ni perfil de entrada) | Buildroot hace `systemctl preset-all` y habilitaba también los servicios **de sistema** de PipeWire, pipewire-pulse y WirePlumber (usuario `pipewire`, sin HOME): un segundo WirePlumber abría la tarjeta antes que el de aios | `disable` en `10-aios.preset` |
| Cada mensaje nuevo tardaba 1-2 min antes de responder: llama-server volvía a procesar 1.600-2.200 tokens | La plantilla de Qwen3.5 solo pinta `<think></think>` en las respuestas posteriores a la última pregunta; al llegar otra, el historial cambia y en un modelo híbrido la caché vuelve a un checkpoint antiguo o a cero | `aios-llama` genera al arrancar una plantilla con el bloque en todas las respuestas (`gguf.py template`). Medido en el VPS con los binarios de la imagen: de ~590 tokens reprocesados por mensaje a ~21 |
| agetty en ttyS0 fallando y reiniciándose cada 10 s (360 líneas de error en el journal) | `console=ttyS0` (para QEMU y pruebas) hace que systemd ponga un getty en un puerto serie que el portátil no tiene | `ExecCondition` en `serial-getty@.service.d/aios-uart.conf`: solo si `/sys/class/tty/ttyS0/type` no es 0 |
| Bluetooth sin audio (WirePlumber: «BlueZ SPA plugin is missing») | `pipewire.mk` solo activa bluez5 con `BR2_PACKAGE_SBC` | `BR2_PACKAGE_SBC=y` |
| El agente no conseguía conectar la wifi: pedía confirmación y luego la contraseña no valía; además se veía al escribirla | La contraseña iba en la orden que escribe el modelo (`--password <p>`): el usuario la tecleaba en el chat a la vista (y quedaba en la conversación guardada) y el modelo de 4B tenía que copiarla, y el nombre de la red, al carácter | `aios-chat` intercepta `net wifi connect`: busca la red con un escaneo, pide la contraseña sin eco (pedirla ya es la confirmación; Enter cancela; hasta 3 intentos) y el modelo no la ve nunca. `net.py` acepta el nombre aproximado si solo coincide una red («livebox 6s f406») |
| El modelo solo usa 4 de los 8 hilos | `THREADS=auto` = núcleos físicos | `-tb` (prompt) con todos los hilos menos uno (`THREADS_BATCH` en `llama.conf`); al generar siguen 4, porque generar lo limita la memoria. El benchmark de `aios-diag` usa ahora un prompt de ~260 tokens para medir también la lectura |
| Reloj 1 h adelantado hasta que sincroniza NTP (a los 13 min, con el wifi) | El portátil tiene Windows: el RTC va en hora local | Sin tocar: es el arranque dual de siempre. Si molesta, `timedatectl set-local-rtc 1` o ajustar Windows a UTC |

Seguimiento (misma noche): en el HP 15s **tampoco se oía el beep** (la autoprueba daba «output OK» igualmente). En el diag PipeWire marcaba los auriculares como conectados y el altavoz como no disponible; el kernel aplica el ajuste genérico de HP (`ALC269_FIXUP_HP_MUTE_LED`, el 86C9 no tiene uno propio). Sin confirmar si es por el PipeWire doble. `aios-diag` recoge ahora `audio-codec.txt` (pines y detección de conectores), `audio-alsa.txt` (`amixer contents`, procesos de audio con su uid, unidades de sistema de PipeWire).

Bloqueo de pantalla (swaylock) imposible de quitar: rechazaba cualquier contraseña. PAM comprueba la contraseña con `unix_chkpwd`, que debe ser setuid root para leer `/etc/shadow`, y en la imagen estaba a 0755 (post-build no puede poner setuid). Arreglo: `board/aios/permissions.txt` en `BR2_ROOTFS_DEVICE_TABLE` (4755). Prueba nueva en QEMU: contraseña buena aceptada y mala rechazada por `unix_chkpwd`, como hace swaylock. Mientras tanto: Ctrl+Alt+F2 y `pkill swaylock`.

## Portátil antiguo: HP 15-ba (29 oct, noche)

HP Notebook, placa 82F6, AMD A8-7410 (Mullins, Radeon R5, `radeon`), 6,7 GiB, BIOS (no UEFI), wifi RTL8723BE. Sonido con micrófono bien; voz: 56 s para 1,3 s de habla (el modelo aún cargaba).

| Hallazgo | Causa | Arreglo (pendiente de probar) |
|---|---|---|
| sway no arranca: «Could not take device: No such device», «Found 0 GPUs» | Carrera: el autologin lanza sway a los 10,8 s y radeon acaba a los 12,8 s; udev seguía con la cola ocupada (cargó `amdgpu` a los 27 s, CPU lenta y USB) y `/dev/dri/card0` aún era `root:root 0600`, sin puesto. La prueba de GPU tampoco podía abrir el nodo de render y forzaba pixman | `aios-session` espera a `udevadm settle` (hasta 45 s, con aviso en pantalla) y, si sway sale con «Found 0 GPUs», espera otra vez y reintenta desde el principio con la prueba de GPU |

## Cortafuegos y proveedores de IA (29 oct, noche)

- **Cortafuegos** (`aios-firewall.service`, `/etc/nftables.conf`): tabla propia `inet aios`; sale todo, entra solo lo establecido/relacionado, loopback, ICMP/ICMPv6 y DHCP. Arranca antes de la red. Reglas locales en `/etc/nftables.d/*.nft` (p. ej. SSH). Pruebas: política `drop` cargada y recarga sin duplicar.
- **Elegir modelo**: `aios ai models [proveedor]` y `aios ai use <proveedor> --model <id>` (recalcula el contexto). En el chat: `/ai`, `/ai <nombre> [modelo]`, y el chat cambia de proveedor solo si cambia el activo (también si lo cambia el agente).
- **Emparejamiento** (`aios ai pair`, `/pair` en el chat): el portátil genera una clave RSA-3072 en `XDG_RUNTIME_DIR`, pide un código al VPS y enseña URL y QR (`qrencode`). En `https://ccmai.org/aios-diag/pair` (móvil o PC) se elige proveedor y se pega la clave; el navegador la cifra con WebCrypto (RSA-OAEP SHA-256) y el VPS solo guarda texto cifrado, en memoria, 10 min, y lo borra al entregarlo. El portátil descifra con `openssl`, enseña lo recibido, pide nombre y modelo y confirma antes de usarlo. Servidor: `scripts/diag-server.py` + `scripts/pair.html` (límites por IP con la IP real, la última de `X-Forwarded-For`). Probado de punta a punta contra el servidor real con un proveedor simulado.
- Proveedores en la página: servidor de ccmai.org (llama-hardened, `https://webuillama.ccmai.org:8443/v1`, `X-API-Key`; es otro proyecto: AIOS solo lo usa, no lo toca), OpenAI, Anthropic, Gemini, Ollama Cloud (`https://ollama.com/v1`; su `/v1/models` no da el contexto: `detect_context` lo saca de `/api/show`, que vale también para un Ollama local), OpenRouter y uno compatible cualquiera. Solo están probados la ruta y el formato; con claves reales, ninguno todavía.
- **Cloudflare devolvía 403 a `Python-urllib`**: el modelo del VPS y el emparejamiento no habrían funcionado desde AIOS. Todas las peticiones llevan ahora `User-Agent: AIOS/1.0` (`ai.headers()`). El servidor simulado de las pruebas rechaza ese agente como Cloudflare.
- Instalador a disco: en la imagen siguiente, borrando el disco entero (se probará en el HP 15-ba, que tiene una versión antigua de AIOS).

## Decisiones ya tomadas

- Buildroot **2026.08.1**, toolchain glibc, CPU **x86-64 base** (corre en cualquier PC de 64 bits).
- llama.cpp del propio Buildroot (**b8117**) con `GGML_BACKEND_DL` + `GGML_CPU_ALL_VARIANTS`; `post-build.sh` mueve las variantes a `/usr/lib/ggml`. Comprobado en el código de b8117: ya trae la arquitectura `qwen35` y el proyector `qwen3vl_merger`, no hace falta subir versión.
- Modelo del hito 0: `unsloth/Qwen3.5-4B-GGUF`, cuantización **Q4_K_M (2,74 GB)** + proyector de visión (`mmproj`). Se deja en `models/` (fuera de git) y `post-build.sh` lo copia a `/usr/share/aios/models/`. Raíz ext4 de 7 GB para que quepa.
- Sesión gráfica: sway (lee configuración de i3) + foot; wlroots con renderizador por software si no hay GPU 3D. libseat usa logind (systemd), sin daemon seatd.
- Contexto local de 16K; puerto 8083 como en aios-lfs.
- **mesa con LLVM** (29 oct): iris y crocus (Intel), radeonsi (AMD) y llvmpipe lo exigen en mesa 26; iris además necesita el compilador precompilado (host-mesa3d + libclc). Buildroot descarta iris sin avisar si falta LLVM. Antes (28 oct) iba sin LLVM y en Intel y AMD moderna sway dibujaba con pixman.
- **Cada imagen para hardware real agrupa todos los cambios verificados**: el ciclo compilar → descargar → grabar USB → probar es largo. Verificar en el VPS todo lo posible antes (Kconfig, compilación, QEMU, scripts ejecutados dentro de la imagen).

## Ideas apuntadas (sin hacer)


- Velocidad del modelo (pospuesto): guardar en disco la caché del prompt fijo (sistema + herramientas) y probar decodificación especulativa con un modelo de borrador pequeño. Medir en el HP.
- Instalador a disco con `/home` en partición propia (hito 4): el USB es solo para pruebas.

## Mejoras propuestas (pendientes de que el usuario las revise)

1. Instalador a disco (hito 4): cifrado LUKS, `/home` en partición propia, A/B con RAUC. Es el destino real; el USB es solo para pruebas.
2. Cortafuegos `nftables` por defecto que bloquee las conexiones entrantes (refuerzo de lo hecho con SSH y LLMNR).
3. Dictado en cualquier aplicación: atajo que transcribe y escribe el texto en la ventana activa (necesita `wtype`).
4. Recordatorios y alarmas por chat o voz: herramienta del agente con temporizadores de systemd, notificación y aviso hablado.
5. Portapapeles (`wl-clipboard`) como herramienta del agente: «resume/traduce lo que he copiado».
6. Temperatura y estrangulamiento térmico en la barra y en la autoprueba (el modelo calienta el portátil).
7. Perfil de batería automático al desenchufar: gobernador de CPU, menos hilos del modelo, brillo.
8. Comprobación periódica de actualizaciones (temporizador) con notificación.
9. Cámara para la visión (`/look camera`).
10. Más herramientas del agente (hito 1): leer ficheros, shell con política de seguridad, documentación (`aios doc`, RAG).
11. Aplicaciones básicas: navegador (extensión, hito 4), visor de imágenes y PDF, gestor de ficheros.
12. Palabra de activación manos libres («Oye AIOS»), opcional: coste de CPU a medir.

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
