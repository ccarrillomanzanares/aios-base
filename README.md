# aios-base

**AIOS** is an operating system with its own AI assistant that runs on the laptop itself, even without Internet, on ordinary 8 GB machines. This repository is its base: a Buildroot `BR2_EXTERNAL` tree for x86_64 that builds a bootable image (USB, BIOS and UEFI) and a VirtualBox appliance.

It is also the common base of **newos**, a voice-first interface (Wayland kiosk + WPE WebKit).

Website and downloads: [ccmai.org/aios](https://ccmai.org/aios/) · Help and keyboard shortcuts: [ccmai.org/aios/help.html](https://ccmai.org/aios/help.html)

## What it does

- **Local AI**: Qwen3.5-4B (with vision) on the CPU through llama.cpp, which picks the fastest code for each processor. The context size adapts to the RAM.
- **The assistant** runs the system through the `aios` command line (JSON output): wifi, sound, screens, Bluetooth, brightness, temperature, power, reminders and updates. It asks before changing anything.
- **Voice**: hold Super+Space and speak (whisper.cpp); spoken answers with espeak; dictation into any window.
- **Screen and clipboard**: `/look` shows the screen to the model; it can summarise or translate what you copied.
- **Optional remote providers** (your own server, OpenAI, Anthropic, Gemini, Ollama Cloud, OpenRouter, any OpenAI-compatible API). Keys are entered on your phone through an encrypted pairing page, never typed on screen.
- **Desktop**: sway + foot with a WarGames look, PipeWire sound, Bluetooth, several screens, screen lock, notifications.
- **Install to disk**: `sudo aios-install` (erases the disk): system A and B for updates, `/home` encrypted with LUKS2.
- **Signed updates**: `aios update code` follows signed `v*` tags, checks daily, notifies once per version and never installs on its own; exact rollback.
- **Support**: `aios sys selftest` checks the hardware; `aios-diag` sends logs and the self-test (never your conversations).

## Status

Early test build, **v0.25.0**. It boots and passes `make test` in QEMU (BIOS and UEFI) and has been tested on two HP laptops (2019 and 2014). Roadmap and decisions: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md); work log: [docs/HITO-0.md](docs/HITO-0.md) (both in Spanish).

## Requirements

- To run it: a 64-bit PC with 8 GB of RAM (16 GB recommended) and a 16 GB USB stick, or VirtualBox. Without AVX2 the local model is very slow: use a server model.
- To build it: Linux, ~60 GB of disk, and patience (about 1 h 20 min from scratch with 16 cores; much less with ccache).

## Build and test

```bash
git clone https://github.com/ccarrillomanzanares/aios-base && cd aios-base
make model        # Qwen3.5-4B Q4_K_M + vision projector + whisper model into models/ (~3.4 GB)
make              # clones Buildroot 2026.08.1 into build/buildroot the first time
make qemu         # or 'make qemu-uefi'; QEMU_DISPLAY=vnc=:1 on a headless server
make test         # native (image binaries on the host), vm (QEMU) and install (disk installer)
```

The image is written to `build/output/images/aios.img`. Write it to a USB stick with `dd`, balenaEtcher or Rufus.

Publishing (maintainers): `scripts/publish.sh img` then `scripts/publish.sh vbox` (USB image, then VirtualBox appliance; both regenerate the website from `web/`), and `scripts/release.sh vX.Y.Z` to sign a release for `aios update code`.

## Layout

| Path | Contents |
|---|---|
| `configs/aios_x86_64_defconfig` | Buildroot configuration |
| `board/aios/` | kernel fragment, GRUB, image layout, post-build and post-image scripts |
| `board/aios/rootfs-overlay/` | everything AIOS adds: the `aios` CLI (`usr/lib/aios`), the chat and agent, session, services, themes, help |
| `package/` | extra packages (whisper.cpp, grim, swaylock, wl-clipboard...) |
| `tests/` | `make test` |
| `web/` | website templates for ccmai.org/aios |
| `scripts/` | publishing, signed releases, model download, diagnostics receiver |

## Related projects

- [aios-lfs](https://github.com/ccarrillomanzanares/aios-lfs) and [aios-agent](https://github.com/ccarrillomanzanares/aios-agent): the previous AIOS, built on Linux From Scratch.
- [newos](https://github.com/ccarrillomanzanares/newos)

## License

MIT
