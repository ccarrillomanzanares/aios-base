# AIOS: shell interactiva del usuario
[[ $- != *i* ]] && return
PS1='\[\e[32m\]\u@\h:\w\$\[\e[0m\] '
alias ls='ls --color=auto'
alias chat='aios-chat'
