# aios-base

Base común de **AIOS** y **newos**: un árbol `BR2_EXTERNAL` de Buildroot para x86_64 con un agente de IA pequeño que corre en la CPU de portátiles antiguos de 8 GB.

- **AIOS**: interfaz de terminal con estética WarGames (sway + foot).
- **newos**: interfaz pensada para la voz (kiosco Wayland + WPE WebKit).

Los dos comparten base inmutable con actualización A/B, extensiones `systemd-sysext`, la CLI `aios` con salida JSON, el agente y los modelos Qwen (Qwen3.5-4B en local, Qwen3.6-35B-A3B en servidor).

## Estado

Fase de diseño. Primer entregable: el hito 0, una imagen que arranca en QEMU con `llama-server` sirviendo Qwen3.5-4B.

## Documentación

- [Arquitectura](docs/ARQUITECTURA.md)

## Proyectos de partida

- [aios-lfs](https://github.com/ccarrillomanzanares/aios-lfs) y [aios-agent](https://github.com/ccarrillomanzanares/aios-agent)
- [newos](https://github.com/ccarrillomanzanares/newos)

Web: [ccmai.org/aios](https://ccmai.org/aios/)

## Licencia

MIT
