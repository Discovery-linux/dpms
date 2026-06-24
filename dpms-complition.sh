# dpms bash completion script
# ported from zypper bash completion by Marek Stopka, Josef Reidinger, et al.

_dpms_installed_packages() {
	! [[ $cur =~ / ]] || return
	local db="${DP_DB_DIR:-/var/lib/dp/installed}"
	if [ -d "$db" ]; then
		ls "$db" 2>/dev/null | grep "^$cur"
	fi
}

_dpms_available_packages() {
	! [[ $cur =~ / ]] || return
	[[ $cur ]] || return
	local cachedir="${XDG_CACHE_HOME:-$HOME/.cache}/dpms/repos"
	if [ -d "$cachedir" ]; then
		for repo in "$cachedir"/*/; do
			[ -d "$repo" ] || continue
			ls "$repo" 2>/dev/null | grep -o "^${cur}[^0-9-]*" | sort -u
		done
	fi
}

_dpms_repos() {
	python3 -c "
import json, sys, os
paths = [
    '/usr/local/lib/python3.13/dist-packages/dpms/repo_list.json',
    os.path.expanduser('~/.config/dpms/repo_list.json'),
    '/etc/dpms/repo_list.json',
]
for p in paths:
    if os.path.exists(p):
        with open(p) as f:
            data = json.load(f)
            for name in data:
                print(name)
        break
" 2>/dev/null
}

_dpms() {
	local noglob=$(shopt -po noglob)
	local comp cur prev command
	local -a opts=()
	local -a cmds=()
	local IFS=$'\n'

	set -o noglob

	if [ ${#_DPMS_CMDS[@]} -eq 0 ]; then
		_DPMS_CMDS=($(
			dpms --help 2>/dev/null | sed -n '/^  --[a-z]/s/^  \(--[^ ,[]*\).*/\1/p'
		))
	fi

	prev=${COMP_WORDS[COMP_CWORD-1]}
	cur=${COMP_WORDS[COMP_CWORD]}

	local comp_iter=$COMP_CWORD
	while [ $((comp_iter--)) -ge 0 ]; do
		comp="${COMP_WORDS[comp_iter]}"
		if [[ " ${_DPMS_CMDS[*]} " =~ " ${comp} " ]]; then
			command=$comp
			break
		fi
		if [[ "$comp" =~ "dpms" ]]; then
			command="dpms"
			break
		fi
	done

	case "$prev" in
		"--add-repo")
			# expects NAME URL [ARCH]
			return 0
		;;
		"--remove-repo" | "--toggle-repo" | "--repo-list" | "--list-repo" | "--repo-priority")
			opts=($( _dpms_repos ))
			COMPREPLY=($(compgen -W "${opts[*]}" -- "$cur"))
			_strip
			eval "$noglob"
			return 0
		;;
		"--lock" | "--unlock" | "--install" | "-i" | "--uninstall" | "-r" | "--info" | "-I" | "--files" | "-f" | "--verify" | "-V" | "--depends" | "--rdepends" | "--download" | "--reinstall" | "--downgrade" | "--oldpackage")
			opts=($( _dpms_available_packages ))
			COMPREPLY=($(compgen -W "${opts[*]}" -- "$cur"))
			_strip
			eval "$noglob"
			return 0
		;;
		"--search" | "-s")
			# optional arg, no completion needed
			return 0
		;;
		"--maketar")
			# expects FOLDER [NAME VERSION [ARCH]]
			return 0
		;;
		"--tar")
			# expects FOLDER
			COMPREPLY=($(compgen -d -- "$cur"))
			_strip
			eval "$noglob"
			return 0
		;;
	esac

	if [[ "$command" == "dpms" ]]; then
		opts=("${_DPMS_CMDS[@]}")
		COMPREPLY=($(compgen -W "${opts[*]}" -- "$cur"))
		_strip
		eval "$noglob"
		return 0
	fi

	if [ -n "$command" ]; then
		if ! [[ $cur =~ ^[^-] ]]; then
			opts=$(_dpms_command_opts "$command")
		fi

		if ! [[ $cur =~ ^- ]]; then
			case "$command" in
				"--help" | "-h")
					opts=("${_DPMS_CMDS[@]}")
				;;
				"--remove-repo" | "--toggle-repo" | "--list-repo" | "--repo-priority")
					opts=($( _dpms_repos ))
				;;
				"--uninstall" | "-r" | "--info" | "-I" | "--files" | "-f" | "--verify" | "-V" | "--depends" | "--rdepends" | "--reinstall")
					opts=($( _dpms_installed_packages ))
				;;
				"--install" | "-i" | "--download" | "--downgrade" | "--lock" | "--unlock")
					opts=($( _dpms_available_packages ))
				;;
			esac
		fi

		IFS=$'\n'
		COMPREPLY=($(compgen -W "${opts[*]}" -- "$cur"))
		_strip
	fi

	eval "$noglob"
}

_dpms_command_opts() {
	dpms --help 2>/dev/null | sed -n '/^  --[a-z]/s/^  \([^-][^ ,[]*\).*/\1/p'
}

_strip() {
	local s c o
	if [ ${#COMPREPLY[@]} -gt 0 ]; then
		s="${COMP_WORDBREAKS// }"
		s="${s//	}"
		s="${s//[\{\}()\[\]]}"
		s="${s} 	(){}[]"
		o=${#s}
		while [ $((o--)) -gt 0 ]; do
			c="${s:${o}:1}"
			COMPREPLY=(${COMPREPLY[*]//${c}/\\${c}})
		done
	fi
}

complete -F _dpms -o default dpms
