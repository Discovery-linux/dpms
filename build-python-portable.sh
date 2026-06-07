#!/bin/bash
set -e

PYTHON_VERSION="${1:-3.13.12}"
PREFIX="/tmp/dpms-python-standalone"
BUILD_DIR="/tmp/dpms-python-build"
DEPS_DIR="$BUILD_DIR/deps"
PKG_NAME="dpms-python-standalone"
OUTPUT_FILE="${PKG_NAME}-${PYTHON_VERSION}.dp.tar.xz"
JOBS=$(nproc)

rm -rf "$BUILD_DIR" "$PREFIX"
mkdir -p "$PREFIX" "$DEPS_DIR" "$DEPS_DIR/src"

# dependency versions
OPENSSL_VER="3.4.1"
ZLIB_VER="1.3.1"
BZIP2_VER="1.0.8"
NCURSES_VER="6.5"
READLINE_VER="8.2"
SQLITE_VER="3480000"
LIBFFI_VER="3.4.6"
XZ_VER="5.6.4"

export CC="gcc"
export CFLAGS="-Os -fdata-sections -ffunction-sections -fPIC"
export LDFLAGS="-Wl,--gc-sections -Wl,-s"
export LD_LIBRARY_PATH="$PREFIX/lib:$LD_LIBRARY_PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export CPPFLAGS="-I$PREFIX/include"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"

build_lib() {
    local name="$1" url="$2" dir="$3"
    local archive="$DEPS_DIR/src/$(basename "$url")"
    if [ ! -f "$archive" ]; then
        wget -q -O "$archive" "$url"
    fi
    local srcdir="$DEPS_DIR/$dir"
    rm -rf "$srcdir"
    mkdir -p "$srcdir"
    tar xf "$archive" -C "$srcdir" --strip-components=1
    cd "$srcdir"
    shift 3
    ./configure --prefix="$PREFIX" --enable-shared --disable-static "$@"
    make -j"$JOBS"
    make install
    cd /
}

build_lib_cmake() {
    local name="$1" url="$2" dir="$3"
    local archive="$DEPS_DIR/src/$(basename "$url")"
    if [ ! -f "$archive" ]; then
        wget -q -O "$archive" "$url"
    fi
    local srcdir="$DEPS_DIR/$dir"
    rm -rf "$srcdir"
    mkdir -p "$srcdir"
    tar xf "$archive" -C "$srcdir" --strip-components=1
    local builddir="$DEPS_DIR/${dir}_build"
    rm -rf "$builddir"
    mkdir -p "$builddir"
    cd "$builddir"
    shift 3
    cmake "$srcdir" -DCMAKE_INSTALL_PREFIX="$PREFIX" -DBUILD_SHARED_LIBS=ON "$@"
    make -j"$JOBS"
    make install
    cd /
}

echo "=== Building dependencies ==="

build_lib "zlib" "https://www.zlib.net/fossils/zlib-${ZLIB_VER}.tar.gz" "zlib"
build_lib "bzip2" "https://sourceware.org/pub/bzip2/bzip2-${BZIP2_VER}.tar.gz" "bzip2" --enable-shared --disable-static
build_lib "xz" "https://github.com/tukaani-project/xz/releases/download/v${XZ_VER}/xz-${XZ_VER}.tar.gz" "xz" --enable-shared --disable-static --disable-doc
build_lib "libffi" "https://github.com/libffi/libffi/releases/download/v${LIBFFI_VER}/libffi-${LIBFFI_VER}.tar.gz" "libffi" --enable-shared --disable-static
build_lib "ncurses" "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VER}.tar.gz" "ncurses" --enable-shared --disable-static --without-normal --without-debug --without-ada --without-tests --with-terminfo-dirs=/etc/terminfo:/lib/terminfo:/usr/share/terminfo
build_lib "readline" "https://ftp.gnu.org/gnu/readline/readline-${READLINE_VER}.tar.gz" "readline" --enable-shared --disable-static
build_lib "openssl" "https://github.com/openssl/openssl/releases/download/openssl-${OPENSSL_VER}/openssl-${OPENSSL_VER}.tar.gz" "openssl" --shared --disable-static --disable-docs

echo "=== Building SQLite ==="
build_lib_cmake "sqlite" "https://www.sqlite.org/2025/sqlite-autoconf-${SQLITE_VER}.tar.gz" "sqlite"

echo "=== Building Python ==="
PYTHON_SRC="$DEPS_DIR/Python-$PYTHON_VERSION"
if [ ! -d "$PYTHON_SRC" ]; then
    wget -q -O "$DEPS_DIR/src/Python-$PYTHON_VERSION.tar.xz" "https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tar.xz"
    mkdir -p "$PYTHON_SRC"
    tar xf "$DEPS_DIR/src/Python-$PYTHON_VERSION.tar.xz" -C "$PYTHON_SRC" --strip-components=1
fi
cd "$PYTHON_SRC"

./configure \
    --prefix="$PREFIX" \
    --enable-optimizations \
    --with-lto \
    --without-ensurepip \
    --disable-test-modules \
    --disable-idle3 \
    --disable-pydoc \
    --disable-lib2to3 \
    --disable-tk \
    --disable-nis \
    --disable-dbm \
    --without-gdbm \
    --without-dbm \
    --enable-shared \
    --with-openssl="$PREFIX" \
    --with-system-libffi \
    --with-system-expat \
    CFLAGS="$CFLAGS" \
    LDFLAGS="$LDFLAGS -L$PREFIX/lib" \
    CPPFLAGS="-I$PREFIX/include"

make -j"$JOBS"
make install

cd /
rm -rf "$BUILD_DIR"

echo "=== Collecting runtime shared libs ==="
for lib in $(LD_LIBRARY_PATH="$PREFIX/lib" ldd "$PREFIX/bin/python3" 2>/dev/null | grep '=> /' | awk '{print $3}' | sort -u); do
    base=$(basename "$lib")
    if [ ! -f "$PREFIX/lib/$base" ]; then
        cp -n "$lib" "$PREFIX/lib/" 2>/dev/null || true
    fi
done

for lib in $(LD_LIBRARY_PATH="$PREFIX/lib" ldd "$PREFIX/lib/libpython3*.so" 2>/dev/null | grep '=> /' | awk '{print $3}' | sort -u); do
    base=$(basename "$lib")
    if [ ! -f "$PREFIX/lib/$base" ]; then
        cp -n "$lib" "$PREFIX/lib/" 2>/dev/null || true
    fi
done

echo "=== Stripping large files ==="
find "$PREFIX" -type f -size +1M 2>/dev/null | while read -r f; do
    if file "$f" | grep -q ELF; then
        strip --strip-unneeded "$f" 2>/dev/null || strip -s "$f" 2>/dev/null || true
    fi
done

strip "$PREFIX/bin/python3" 2>/dev/null || true

echo "=== Packaging with dpms maketar ==="
cd /tmp
python3 -m dpms.dpms --maketar "$PREFIX" "$PKG_NAME" "$PYTHON_VERSION"

echo "Done."
echo "Output: $(ls -1 /tmp/${PKG_NAME}-${PYTHON_VERSION}-*.dp.tar.xz 2>/dev/null | head -1)"
echo "Size: $(du -h /tmp/${PKG_NAME}-${PYTHON_VERSION}-*.dp.tar.xz 2>/dev/null | cut -f1)"
