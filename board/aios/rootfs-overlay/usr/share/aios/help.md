# AIOS help

Open this help at any time with Super+F1, or type `aios-help` in a terminal. Super is the key with the Windows logo.

## The screen is locked or black

The screen locks after 5 minutes without use, when you press Super+Ctrl+L, and before the laptop sleeps (lid closed). After 10 minutes it also turns off.

- Black screen: press any key or move the mouse.
- Green ring: the screen is locked. Type your password (nothing is shown, the ring lights up with each key) and press Enter.
- Red ring: wrong password. Type it again; check Caps Lock and the keyboard layout.
- If the password is never accepted or the screen stays black: press Ctrl+Alt+F2, log in as `aios` with your password, type `pkill swaylock` and press Enter, then press Ctrl+Alt+F1 to go back.
- If nothing reacts at all, hold the power button for 5 seconds. Then run `aios-diag` so we can see what happened.

## The assistant

The AIOS terminal opens when the session starts. Type a message and press Enter, or hold Super+Space and speak.

| In the chat | What it does |
|---|---|
| `/voice` | speak instead of typing (same as holding Super+Space) |
| `/look [question]` | show the screen to the assistant |
| `/speak on`, `/speak off` | spoken answers on or off |
| `/history`, `/resume [n]` | earlier conversations, and continue one |
| `/clear` | start a new conversation |
| `/ai`, `/ai <name> [model]` | list the AI providers, switch to another one |
| `/pair` | add an AI provider by entering its key on your phone |
| `/help` | short help |
| `/exit` | close the chat (a normal terminal stays open) |

The assistant asks before changing anything. Ask it things like "connect to my wifi", "turn the volume down", "remind me at 6 to call Ana" or "how hot is the processor?".

## Notifications

Notices appear in the top right corner: reminders, low battery, updates, temperature. They go away after a few seconds or when you click them; reminders and urgent ones (battery almost empty) stay until you click. Missed one? `makoctl restore` shows the last one again.

## Updates

AIOS checks for updates once a day (and 15 minutes after starting) and tells you with a notice. It never installs anything by itself.

- Only versions signed by the AIOS team are offered, and never an older one.
- To install: open a terminal (Super+Enter) and run `sudo aios update code apply`. It shows what will change and asks first.
- Your own changes to settings files are kept; if one clashes, the new version is saved next to it as `.aios-new`.
- Something went wrong? `sudo aios update code rollback` puts back exactly what was there before.
- Check by hand: `sudo aios update code check`. Turn the daily check off: `AUTO_CHECK=no` in `/etc/aios/update.conf`.
- Some changes (new programs, the kernel) need a new image: the notice says so, and you download it from ccmai.org/aios.

## Keyboard shortcuts

| Keys | What it does |
|---|---|
| Super+F1 | this help |
| Super+C | open the AIOS assistant |
| Super+Enter | open a terminal |
| Super+D | run a program by name |
| Hold Super+Space | talk to the assistant |
| Hold Super+Ctrl+Space | dictate into the window you are using |
| Super+Ctrl+L | lock the screen |
| Print Screen | screenshot (saved in Pictures/Screenshots) |
| Super+Shift+Q | close the window |
| Super+F | full screen on or off |
| Super+Arrows (or H J K L) | move between windows |
| Super+Shift+Arrows (or H J K L) | move the window |
| Super+1 to Super+5 | go to workspace 1 to 5 |
| Super+Shift+1 to 5 | send the window to workspace 1 to 5 |
| Super+B, Super+V | next window beside, or below |
| Super+W, Super+S, Super+E | tabs, stacked, side by side |
| Super+Shift+Space | floating window on or off |
| Super+Shift+C | reload the desktop settings |
| Super+Shift+E | leave the desktop (type `exec aios-session` to start it again) |
| Brightness, volume and mute keys | work as usual, also on the lock screen |

## Useful commands

Type them in a terminal (Super+Enter). The ones with `sudo` ask for your password.

| Command | What it does |
|---|---|
| `aios net status` | network and Internet |
| `aios net wifi scan`, `aios net wifi connect <name>` | wifi networks |
| `aios audio status`, `aios audio test` | sound |
| `aios bt status`, `aios bt scan`, `aios bt connect <device>` | Bluetooth |
| `aios ui display list` | screens; also `extend`, `mirror`, `on`, `off` |
| `aios sys selftest` | test the hardware |
| `aios sys thermal`, `aios sys power` | temperature and battery |
| `aios remind list` | reminders |
| `sudo aios update code check` | look for AIOS updates (see Updates above) |
| `sudo aios-install` | install AIOS on the disk (erases the whole disk) |
| `aios-diag` | send a problem report: logs and hardware, never your conversations |
