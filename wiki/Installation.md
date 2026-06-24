# Installation

## From source

```bash
git clone https://github.com/Discovery-linux/Dpms--pkg.git
cd dpms
pip install .
```

## Dependencies

- Python 3.8+
- `rich` (CLI formatting)
- `textual` (TUI)
- `PyQt5` (GUI, optional)

## Dev mode

```bash
export DPMS_ROOT=~/system_root
python3 -m dpms.dpms --help
```

Set `DPMS_ROOT` to any user-writable directory to skip sudo during development.
