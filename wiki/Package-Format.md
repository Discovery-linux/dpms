# Package format

DPMS packages are `.tar.xz` archives with a `.dp` extension.

## Naming

```
name-version-arch.dp.tar.xz
name-version-arch.dp-rcN.tar.xz     (release candidate)
```

Examples: `ripgrep-13.0.0-x86_64.dp.tar.xz`, `myapp-2.5-aarch64.dp-rc1.tar.xz`

## Structure

Packages are extracted directly to the install root. Each package can contain:
- Binaries (`usr/bin/`)
- Libraries (`usr/lib/`)
- Configuration (`etc/`)
- Any other files

## Tracking

DPMS records every installed file:

```
/var/lib/dp/installed/<pkgname>   ← list of installed file paths
```

On uninstall, DPMS reads this list, removes each file, and cleans up empty directories.

## Supported platforms

| Platform | Arch |
|----------|------|
| Linux x86_64 | `x86_64` |
| Linux ARM64 | `aarch64` |
| macOS Intel | `x86_64` |
| macOS Apple Silicon | `aarch64` |
