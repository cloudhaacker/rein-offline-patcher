# How it works

This document explains what the patcher does, why it is built the way it is,
and how it was developed. It is written for people who want to check the tool
before running it, or change it.

The whole tool is three files:

| File | Role |
|---|---|
| `Start Patcher.bat` | Gets a portable Python on first run, then starts the program |
| `app/patcher.py` | The program: setup, patching, checking, and a tiny local web server |
| `app/ui.html` | The window, shown in your web browser |

## What the original Colab notebook does

The lunar-tear guide's step 4 runs `lunar_tear_patcher.ipynb` on Google Colab.
The notebook contains no patch logic of its own. It is a launcher that:

1. Clones the lunar-scripts repository.
2. Installs `pycryptodome`, `msgpack` and `lz4`, plus Apktool, `zipalign`,
   `apksigner` and `keytool`.
3. For the APK: unpacks it with Apktool, runs `android/patch_apk.py` on the
   unpacked folder, rebuilds it, aligns it, generates a throwaway signing key
   and signs it.
4. For the master data: runs `patch_masterdata.py` on the `.bin.e` file.

This tool performs the same steps with the same scripts on your PC.

## What the upstream scripts change

This is a summary of the lunar-tear authors' work, from reading their scripts.
Their source is the authority; see the links in [CREDITS.md](../CREDITS.md).

### `patch_apk.py` (the APK)

- **`global-metadata.dat`**: the game's text constants live in this Unity
  IL2CPP file. The script rewrites the official server host name and three
  URLs to point at your server. A replacement must fit in the space of the
  original text, which is why very long addresses are refused.
- **`libil2cpp.so`**: the compiled game code. The script overwrites a small
  number of ARM64 instructions at fixed positions, valid only for game version
  3.7.1. These turn off certificate checking, pass network encryption through,
  make the asset list load unencrypted, bypass the in-app purchase checks, and
  set the server port.
- **`AndroidManifest.xml`** and **`network_security_config.xml`**: allow plain
  HTTP, since a home server has no certificate.
- **Facebook SDK code (smali)**: when you give a login address, the in-game
  login button is redirected from Facebook to your own auth server.

### `patch_masterdata.py` (the content tables)

`20240404193219.bin.e` is the game's master database: AES-encrypted, with a
MessagePack index followed by LZ4-compressed tables. The script decrypts it,
moves end dates that fall in 2020 to 2029 out to the end of 2030 so events,
shops and quests stay available, applies a few targeted table fixes, and
re-encrypts it. It does not depend on your server address.

## What this tool adds

### Setup: one folder, offline after the first run

`Start Patcher.bat` downloads the *embeddable* build of Python 3.12 from
python.org into `runtime\python` with `curl` and `tar`, both of which ship with
Windows 10 and 11. It then writes a three-line `python312._pth` file so that
this Python can import the bundled packages in `runtime\libs`. Nothing is
installed system-wide and no PATH or registry changes are made.

The program's *Setup* step then downloads, from fixed version-pinned addresses:

- Eclipse Temurin JRE 17 (Java, which also provides `keytool`)
- `apktool_2.11.1.jar`, the same version the notebook uses
- `uber-apk-signer-1.3.0.jar`
- the lunar-scripts repository as a zip

Each archive is kept in `runtime\downloads`. If a download fails, you can place
the file there by hand. Zip archives are checked before extraction so that no
entry can be written outside its target folder.

Downloads are **not** checksum-verified. They come over HTTPS from the
projects' official hosts, which is the same level of trust the Colab notebook
applies.

### Patching the APK

`patch_apk()` in `app/patcher.py` runs five steps, shown in the progress box:

1. Copy the APK into `runtime\work`.
2. `apktool d` to unpack it.
3. Run the upstream `patch_apk.py` with `--grpc-addr`, `--http-addr` and
   optionally `--auth-host`.
4. `apktool b` to rebuild it.
5. Align and sign it, then move it to `output\patched.apk`.

The work folder is deleted afterwards, whether or not the run succeeded.

Before starting, the addresses you typed are checked against the same length
limits the upstream script enforces, so a problem is reported immediately
rather than several minutes in. Afterwards the script's output is scanned: if
it could not find the game's server addresses, the run is reported as failed
instead of producing a broken APK.

### Differences from the Colab notebook

- **Align and sign.** The notebook uses `zipalign` and `apksigner` from the
  Android SDK. This tool uses uber-apk-signer, a single Java file that performs
  both steps, so the Android SDK is not needed. The output is checked to be
  aligned and signed with the v1, v2 and v3 schemes.
- **Signing key.** The notebook generates a new key in every session. This tool
  generates one key the first time (`runtime\keystore`, subject `CN=Debug`,
  no personal details) and reuses it, so later re-patches install as updates.
- **Paths.** Apktool's framework files are kept inside `runtime` instead of
  your user profile.

Everything else is the same commands with the same arguments.

### Patching the content tables

`patch_masterdata()` runs the upstream script and writes
`output\20240404193219.bin.e`. The input file is never modified.

### Checking an APK

`check_apk()` opens an APK as a zip archive and reports:

- which signature schemes are present, by reading the APK Signing Block
- whether uncompressed files are 4-byte aligned and `resources.arsc` is stored
- which native libraries and how many `dex` files it contains
- the server address found in `global-metadata.dat`, and whether any official
  address is still present
- whether each instruction patch listed in the current `patch_apk.py` is
  present in `libil2cpp.so`, and the port that was written

Given a second APK, it also lists files that exist in only one, files whose
contents differ, and the exact differing bytes in the two patched game files.
It reads only; it never writes to an APK.

### The window

There is no GUI toolkit in embeddable Python, so the window is a web page.
`patcher.py` starts a small HTTP server bound to `127.0.0.1` on a random free
port and opens your browser at it.

- The server is reachable only from your own PC.
- The address contains a random token generated at each start. Every request
  must carry it, and the `Host` header must be local. This stops other web
  pages you have open from driving the patcher.
- Files you choose are copied by the browser to `runtime\inbox` under fixed
  names, so nothing the page sends can choose where a file is written. The
  folder is emptied when the patcher starts and when it quits.
- One task runs at a time, in a background thread. The page polls for new log
  lines once or twice a second.

The page uses no external scripts, fonts or images and sends nothing anywhere.

### Privacy

- No settings are saved. Your IP address is typed in each time and is passed
  only to the patch script.
- No log files are written. The progress text exists only in memory.
- *Show this PC's addresses* reads the addresses of your network adapters
  locally. It sends no data.
- Your patched APK contains your server address, and `runtime\keystore`
  contains your signing key. Do not share a folder you have used.

## Command line and other systems

`patcher.py` can be run without the window:

```
python app/patcher.py setup
python app/patcher.py apk --apk game.apk --ip 192.168.1.50
python app/patcher.py masterdata --input 20240404193219.bin.e
python app/patcher.py check --apk output/patched.apk --compare other.apk
```

On Linux or macOS, install Python 3.10 or newer, Java 17 or newer, and
`pip install pycryptodome msgpack lz4`. The bundled `runtime/libs` are Windows
binaries and are not used there. The development tests below ran on Linux, but
nobody has used the tool for real on those systems.

## How it was developed

An honest account, including the wrong turns.

1. **Reading.** The setup guide pointed to a Colab notebook hosted on GitLab.
   The notebook turned out to be a launcher for two scripts.
2. **Content tables, first attempt.** Before the scripts were available, the
   patch was reverse-engineered from an original and a Colab-patched copy of
   the file: both were decrypted, compared table by table, and the differences
   stored as a list of byte edits. That reproduced the Colab output exactly.
3. **Switching to the real scripts.** Once the lunar-scripts code was at hand,
   the reverse-engineered patch was dropped in favour of running the authors'
   own script, which gives the same bytes and stays correct if they update it.
4. **APK pipeline.** Built to mirror the notebook, with the substitutions
   listed above. It was first exercised on a stand-in APK containing fake game
   files, then by the owner on the real APK.
5. **A black screen.** The first real APK showed a black screen. The check
   feature was written to compare it with a working Colab-patched APK. The two
   were identical apart from the server address: the PC had two network
   addresses and the wrong one had been used. The *Use this PC's IP* button,
   which had silently picked one, was replaced by a list to choose from.
6. **File pickers.** The first version opened a Windows file dialog through
   PowerShell. It appeared behind the browser, so file choosing was moved into
   the page.
7. **A bug shipped.** That change accidentally deleted the code behind the
   *Check APK* and *Copy report* buttons, and the owner found it. From then on
   every button is exercised in a real (headless) browser before a release.

### Tests that were run

- Content tables: output byte-identical to the Colab output for the real file.
- APK steps: unpack, patch, rebuild, align and sign on a stand-in APK; the
  result verified as aligned and signed.
- The page: every button clicked through in headless Chrome on Linux.
- Real APK on Windows: done by the owner; patched APK matched a Colab-patched
  one apart from the address, and ran in MuMu Player.

There is no automated test suite in this repository.
