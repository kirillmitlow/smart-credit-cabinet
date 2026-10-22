# JSON reader for smoke.sh: Bash 3.2+, no jq/Python. Paths use dot-separated keys/indices.
# Leaves the selected value as JSON_RAW (JSON) and JSON_TEXT (unquoted ASCII scalar).
# Containers and strings stay intact: braces/commas inside strings are never delimiters.

_json_space() {
    while [[ ${_j_data:_j_pos:1} == [$' \t\r\n'] && $_j_pos -lt ${#_j_data} ]]; do
        _j_pos=$((_j_pos + 1))
    done
}

_json_string() {
    local c escape hex
    [[ ${_j_data:_j_pos:1} == '"' ]] || return 1
    _j_pos=$((_j_pos + 1))
    while (( _j_pos < ${#_j_data} )); do
        c=${_j_data:_j_pos:1}
        _j_pos=$((_j_pos + 1))
        case "$c" in
            '"') return 0 ;;
            '\')
                escape=${_j_data:_j_pos:1}
                _j_pos=$((_j_pos + 1))
                case "$escape" in
                    '"'|'\'|'/'|b|f|n|r|t) ;;
                    u)
                        hex=${_j_data:_j_pos:4}
                        [[ $hex =~ ^[0-9a-fA-F]{4}$ ]] || return 1
                        _j_pos=$((_j_pos + 4))
                        ;;
                    *) return 1 ;;
                esac
                ;;
            $'\n'|$'\r'|$'\t') return 1 ;;
        esac
    done
    return 1
}

_json_value() {
    local path=$1 depth=$2 start key_start key index=0 c token child
    (( depth < 64 )) || return 1
    _json_space
    start=$_j_pos
    c=${_j_data:_j_pos:1}
    case "$c" in
        '{'|'[')
            _j_pos=$((_j_pos + 1))
            _json_space
            if [[ $c == '{' && ${_j_data:_j_pos:1} == '}' ]] ||
               [[ $c == '[' && ${_j_data:_j_pos:1} == ']' ]]; then
                _j_pos=$((_j_pos + 1))
            else
                while :; do
                    if [[ $c == '{' ]]; then
                        _json_space
                        key_start=$_j_pos
                        _json_string || return 1
                        key=${_j_data:key_start+1:_j_pos-key_start-2}
                        _json_space
                        [[ ${_j_data:_j_pos:1} == ':' ]] || return 1
                        _j_pos=$((_j_pos + 1))
                    else
                        key=$index
                        index=$((index + 1))
                    fi
                    child=${path:+$path.}$key
                    _json_value "$child" "$((depth + 1))" || return 1
                    _json_space
                    if [[ $c == '{' && ${_j_data:_j_pos:1} == '}' ]] ||
                       [[ $c == '[' && ${_j_data:_j_pos:1} == ']' ]]; then
                        _j_pos=$((_j_pos + 1))
                        break
                    fi
                    [[ ${_j_data:_j_pos:1} == ',' ]] || return 1
                    _j_pos=$((_j_pos + 1))
                done
            fi
            ;;
        '"') _json_string || return 1 ;;
        *)
            while (( _j_pos < ${#_j_data} )); do
                case "${_j_data:_j_pos:1}" in
                    ','|']'|'}'|$' '|$'\t'|$'\r'|$'\n') break ;;
                esac
                _j_pos=$((_j_pos + 1))
            done
            token=${_j_data:start:_j_pos-start}
            [[ $token == true || $token == false || $token == null ||
               $token =~ ^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$ ]] || return 1
            ;;
    esac
    if [[ $path == "$_j_want" ]]; then
        _j_found=$((_j_found + 1))
        JSON_RAW=${_j_data:start:_j_pos-start}
    fi
}

json_read() {
    local _j_data=$1 _j_want=$2 _j_pos=0 _j_found=0
    JSON_RAW= JSON_TEXT=
    _json_value '' 0 || return 1
    _json_space
    [[ $_j_pos -eq ${#_j_data} && $_j_found -eq 1 ]] || return 1
    JSON_TEXT=$JSON_RAW
    if [[ $JSON_RAW == \"* ]]; then
        JSON_TEXT=${JSON_RAW:1:${#JSON_RAW}-2}
        # All fields consumed by smoke are ASCII identifiers, enum values and demo codes.
        # Do not silently use a JSON escape as a different identifier.
        [[ $JSON_TEXT != *'\'* ]] || return 1
    fi
}
