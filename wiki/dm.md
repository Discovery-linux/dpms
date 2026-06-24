# dm — DPMS Version Manager

`dm` manages versions of the `dpms` package itself using pip.

## Commands

| Command | Description |
|---------|-------------|
| `dm list dpms` | Show all versions on PyPI |
| `dm current [dpms]` | Show installed version |
| `dm use dpms VERSION` | Switch to a specific version |
| `dm compare V1 V2` | Compare two version strings |
| `dm diff dpms V1 V2` | Compare files between versions |
| `dm pin dpms` | Lock current version |
| `dm unpin dpms` | Unlock version |
| `dm list-pinned` | Show pinned versions |
| `dm rollback dpms` | Go back to previous version |

## Examples

```bash
dm list dpms
dm current
dm use dpms 2.0.0
dm rollback dpms
dm pin dpms
```

## How it works

`dm` delegates everything to pip:
- **version listing** — `pip index versions dpms`
- **switching** — `pip install dpms==<version>`
- **installed version** — `importlib.metadata.version('dpms')`
