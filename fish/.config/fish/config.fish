test -f /usr/share/cachyos-fish-config/cachyos-config.fish && source /usr/share/cachyos-fish-config/cachyos-config.fish

# Add user local bin to path
fish_add_path -g $HOME/.local/bin

# Initialize Starship prompt if installed
if type -q starship
    starship init fish | source
end
