
# uv environment - only source when uv is actually installed,
# otherwise fish prints an error on every new shell.
test -f "$HOME/.local/bin/env.fish" && source "$HOME/.local/bin/env.fish"
