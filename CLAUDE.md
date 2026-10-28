# aios-base — contexto para Claude Code

Base común de AIOS y newos: árbol `BR2_EXTERNAL` de Buildroot (x86_64) con un agente de IA local que corre en la CPU de portátiles de 8 GB.

- Arquitectura y decisiones: `docs/ARQUITECTURA.md`.
- Trabajo en curso y estado pieza a pieza: `docs/HITO-0.md`. Actualízalo al terminar cada pieza.
- Idioma del proyecto: español en docs y comentarios; mensajes de la interfaz y de la web, en inglés.
- Repos de partida para consultar (no modificar desde aquí): aios-lfs, aios-agent y newos en github.com/ccarrillomanzanares. newos ya resolvió arranque BIOS/UEFI, kernel sin initramfs y Wayland en Buildroot.
- Antes de publicar una imagen: arrancarla en QEMU. No terminar comandos con `| tail -1` sin comprobar el código de salida (oculta errores; pasó con xorriso y con git push).
