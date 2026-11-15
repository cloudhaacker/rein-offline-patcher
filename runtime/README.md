# runtime

Everything the patcher needs at run time lives here. Only `libs/` is part of
the repository; the rest is created on your PC the first time you run the
patcher and is ignored by git.

## libs (committed)

The unpacked contents of three unmodified wheels from PyPI, for 64-bit Windows
and CPython 3.12. The patch scripts import them.

| Package | Version | Wheel | SHA-256 of the wheel |
|---|---|---|---|
| pycryptodome | 4.4.0 | `pycryptodome-4.4.0-cp39-abi3-win_amd64.whl` | `c5571df4f386ff4cdc0d5d0d040af9c0bdfc59ad587bf224063d873e07acbe61` |
| msgpack | 1.2.4 | `msgpack-1.2.4-cp312-cp312-win_amd64.whl` | `6e38b123681df22373d545520f54bbeddc4706d9235a1161061f12bd6648497d` |
| lz4 | 4.4.5 | `lz4-4.4.5-cp312-cp312-win_amd64.whl` | `713a777de88a73425cf08eb11f742cd2c98628e79a8673d6a52e3c5f0c116f33` |

To rebuild this folder yourself instead of trusting the committed copy:

```
pip download --no-deps --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp -d wheels pycryptodome==4.4.0 msgpack==1.2.4 lz4==4.4.5
```

then unzip each `.whl` into `runtime/libs`. Each package's license is in its
`*.dist-info` folder.

## Created on first run (not committed)

| Folder | What | From |
|---|---|---|
| `python/` | Portable Python 3.12.10 (embeddable build) | python.org |
| `jre/` | Eclipse Temurin JRE 17.0.15+6 | github.com/adoptium/temurin17-binaries |
| `tools/` | `apktool_2.11.1.jar`, `uber-apk-signer-1.3.0.jar` | their GitHub releases |
| `scripts/` | The lunar-scripts project | gitlab.com/walter-sparrow-group/lunar-scripts |
| `downloads/` | The downloaded archives, kept as a backup | |
| `keystore/` | Your APK signing key, generated locally | |
| `apktool-framework/`, `work/`, `inbox/` | Scratch space, emptied after use | |
