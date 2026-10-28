# AIOS: al entrar en tty1 (autologin) se abre la sesión gráfica.
# En otras consolas, por SSH o dentro de foot, es una shell normal.
[ -f ~/.bashrc ] && . ~/.bashrc
if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
    exec /usr/bin/aios-session
fi
