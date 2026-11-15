#!/usr/bin/env python3
"""
NieR Re[in]carnation offline patcher.

Does what lunar_tear_patcher.ipynb does on Google Colab (step 4 of the private
server guide), but on your own PC:

  * patches the APK so the game connects to your server
  * patches the master data (content tables) file

The actual patching is done by the lunar-scripts project (patch_apk.py and
patch_masterdata.py). This program downloads them plus the tools they need
(Java, Apktool, an APK signer) into the "runtime" folder once, then works
offline.

Run without arguments for the browser-based window, or see --help for the
command-line mode.
"""
import argparse
import glob
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
RUNTIME = os.path.join(ROOT, "runtime")
DOWNLOADS = os.path.join(RUNTIME, "downloads")
TOOLS = os.path.join(RUNTIME, "tools")
JRE_DIR = os.path.join(RUNTIME, "jre")
SCRIPTS_DIR = os.path.join(RUNTIME, "scripts")
FRAMEWORK_DIR = os.path.join(RUNTIME, "apktool-framework")
KEYSTORE = os.path.join(RUNTIME, "keystore", "debug.keystore")
WORK = os.path.join(RUNTIME, "work")
OUTPUT = os.path.join(ROOT, "output")

IS_WINDOWS = os.name == "nt"
MASTERDATA_NAME = "20240404193219.bin.e"

APKTOOL_JAR = "apktool_2.11.1.jar"
SIGNER_JAR = "uber-apk-signer-1.3.0.jar"
JRE_ZIP = "OpenJDK17U-jre_x64_windows_hotspot_17.0.15_6.zip"
SCRIPTS_ZIP = "lunar-scripts-main.zip"

URLS = {
    APKTOOL_JAR: "https://github.com/iBotPeaches/Apktool/releases/download/v2.11.1/apktool_2.11.1.jar",
    SIGNER_JAR: "https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar",
    JRE_ZIP: "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.15%2B6/" + JRE_ZIP,
    SCRIPTS_ZIP: "https://gitlab.com/walter-sparrow-group/lunar-scripts/-/archive/main/lunar-scripts-main.zip",
}

# Length limits come from patch_apk.py: replacement strings must fit in the
# space of the originals inside the game's metadata file.
MAX_GRPC_HOST = len("api.app.nierreincarnation.com")
MAX_WEB_URL = len("https://web.app.nierreincarnation.com")


class PatchError(Exception):
    pass


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def no_log(_line):
    pass


def find_java():
    """Path to java inside runtime/jre, or a system java on non-Windows."""
    exe = "java.exe" if IS_WINDOWS else "java"
    hits = sorted(glob.glob(os.path.join(JRE_DIR, "*", "bin", exe)))
    if hits:
        return hits[-1]
    if not IS_WINDOWS:
        return shutil.which("java")
    return None


def find_keytool():
    java = find_java()
    if not java:
        return None
    exe = "keytool.exe" if IS_WINDOWS else "keytool"
    cand = os.path.join(os.path.dirname(java), exe)
    if os.path.isfile(cand):
        return cand
    return shutil.which("keytool")


def scripts_root():
    """Folder that contains patch_masterdata.py and android/patch_apk.py."""
    for cand in [SCRIPTS_DIR] + sorted(glob.glob(os.path.join(SCRIPTS_DIR, "*"))):
        if os.path.isfile(os.path.join(cand, "android", "patch_apk.py")) and \
                os.path.isfile(os.path.join(cand, "patch_masterdata.py")):
            return cand
    return None


def python_libs_ok():
    try:
        import Crypto  # noqa: F401
        import lz4.block  # noqa: F401
        import msgpack  # noqa: F401
        return True
    except Exception:
        return False


def components():
    """Status of everything the patcher needs."""
    return [
        {"id": "python", "name": "Python packages", "ok": python_libs_ok(),
         "file": None, "note": "bundled with the patcher"},
        {"id": "scripts", "name": "Patch scripts (lunar-scripts)", "ok": scripts_root() is not None,
         "file": SCRIPTS_ZIP, "url": URLS[SCRIPTS_ZIP]},
        {"id": "java", "name": "Java", "ok": find_java() is not None and find_keytool() is not None,
         "file": JRE_ZIP if IS_WINDOWS else None,
         "url": URLS[JRE_ZIP] if IS_WINDOWS else None,
         "note": None if IS_WINDOWS else "install Java 17+ with your package manager"},
        {"id": "apktool", "name": "Apktool", "ok": os.path.isfile(os.path.join(TOOLS, APKTOOL_JAR)),
         "file": APKTOOL_JAR, "url": URLS[APKTOOL_JAR]},
        {"id": "signer", "name": "APK signer", "ok": os.path.isfile(os.path.join(TOOLS, SIGNER_JAR)),
         "file": SIGNER_JAR, "url": URLS[SIGNER_JAR]},
    ]


def missing(ids):
    return [c["name"] for c in components() if c["id"] in ids and not c["ok"]]


def download(name, log, force=False):
    """Fetch URLS[name] into runtime/downloads (or reuse a copy already there)."""
    os.makedirs(DOWNLOADS, exist_ok=True)
    dest = os.path.join(DOWNLOADS, name)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0 and not force:
        log(f"  using {name} from runtime/downloads")
        return dest
    url = URLS[name]
    log(f"  downloading {name} ...")
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "nier-offline-patcher"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            got, last = 0, time.time()
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if time.time() - last > 2:
                    last = time.time()
                    pct = f" ({got * 100 // total}%)" if total else ""
                    log(f"    {got / 1048576:.1f} MB{pct}")
        if total and got != total:
            raise PatchError("download was cut off")
    except Exception as exc:
        if os.path.exists(part):
            os.remove(part)
        raise PatchError(
            f"Could not download {name}: {exc}\n"
            f"  Download it yourself from:\n    {url}\n"
            f"  put it in the runtime/downloads folder (keep the name {name}) and try again."
        )
    os.replace(part, dest)
    log(f"    done ({os.path.getsize(dest) / 1048576:.1f} MB)")
    return dest


def safe_extract(zip_path, dest):
    """Extract a zip, refusing entries that would land outside dest."""
    dest_abs = os.path.abspath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = os.path.abspath(os.path.join(dest_abs, member))
            if target != dest_abs and not target.startswith(dest_abs + os.sep):
                raise PatchError(f"Unsafe path in {os.path.basename(zip_path)}: {member}")
        zf.extractall(dest_abs)


def rmtree(path):
    def onerror(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except Exception:
            pass
    if os.path.isdir(path):
        shutil.rmtree(path, onerror=onerror)


def run(cmd, log, cwd=None):
    """Run a tool, streaming its output to log. Returns the output lines."""
    flags = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            creationflags=flags,
        )
    except OSError as exc:
        raise PatchError(f"Could not start {os.path.basename(cmd[0])}: {exc}")
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        lines.append(line)
        log("  " + line)
    if proc.wait() != 0:
        raise PatchError(f"{os.path.basename(cmd[0])} failed (exit code {proc.returncode}). See the log above.")
    return lines


def python_cmd(script):
    # -X utf8: the scripts print non-ASCII characters, which would crash on a
    # Windows pipe otherwise.
    return [sys.executable, "-X", "utf8", script]


# --------------------------------------------------------------------------
# setup (first run, or "update scripts")
# --------------------------------------------------------------------------

def install_scripts(log, force=False):
    zip_path = download(SCRIPTS_ZIP, log, force=force)
    tmp = SCRIPTS_DIR + ".new"
    rmtree(tmp)
    safe_extract(zip_path, tmp)
    rmtree(SCRIPTS_DIR)
    os.replace(tmp, SCRIPTS_DIR)
    if not scripts_root():
        raise PatchError(f"{SCRIPTS_ZIP} does not contain the expected patch scripts.")


def setup(log=no_log, update_scripts=False):
    log("Setting up (one time) ...")
    for d in (DOWNLOADS, TOOLS, OUTPUT):
        os.makedirs(d, exist_ok=True)

    if not python_libs_ok():
        raise PatchError(
            "The Python packages are missing. Use the complete patcher folder "
            "(runtime/libs), or run: pip install pycryptodome msgpack lz4"
        )

    if update_scripts or not scripts_root():
        log("Patch scripts:")
        install_scripts(log, force=update_scripts)

    for jar in (APKTOOL_JAR, SIGNER_JAR):
        if not os.path.isfile(os.path.join(TOOLS, jar)):
            log(f"{jar}:")
            shutil.copyfile(download(jar, log), os.path.join(TOOLS, jar))

    if not (find_java() and find_keytool()):
        if not IS_WINDOWS:
            raise PatchError("Java was not found. Install Java 17 or newer (it must include keytool).")
        log("Java:")
        zip_path = download(JRE_ZIP, log)
        log("  unpacking ...")
        rmtree(JRE_DIR)
        safe_extract(zip_path, JRE_DIR)
        if not (find_java() and find_keytool()):
            raise PatchError("Java was unpacked but java.exe / keytool.exe were not found.")

    left = missing({"python", "scripts", "java", "apktool", "signer"})
    if left:
        raise PatchError("Still missing: " + ", ".join(left))
    log("Setup complete. The patcher now works offline.")


# --------------------------------------------------------------------------
# input checks
# --------------------------------------------------------------------------

HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$")


def check_host(host):
    host = (host or "").strip()
    if not host:
        raise PatchError("Enter your server's IP address.")
    if "://" in host or "/" in host or ":" in host or not HOST_RE.match(host):
        raise PatchError(
            f"'{host}' is not a valid address. Enter just the IP (for example 192.168.1.50), "
            "without http:// and without a port."
        )
    return host


def check_port(value, label):
    try:
        port = int(str(value).strip())
    except ValueError:
        raise PatchError(f"{label} port must be a number.")
    if not 1 <= port <= 65535:
        raise PatchError(f"{label} port must be between 1 and 65535.")
    return port


def build_addresses(host, grpc_port, http_port, auth_port):
    """Validate and return (grpc_addr, http_addr, auth_host or None)."""
    host = check_host(host)
    gp = check_port(grpc_port, "Game (gRPC)")
    hp = check_port(http_port, "Assets (HTTP)")
    if len(host) > MAX_GRPC_HOST:
        raise PatchError(f"The address is too long (max {MAX_GRPC_HOST} characters).")
    web_url = f"http://{host}:{hp}"
    if len(web_url) > MAX_WEB_URL:
        raise PatchError(f"The address is too long: {web_url} must be at most {MAX_WEB_URL} characters.")
    auth = None
    if auth_port not in (None, "", 0, "0"):
        auth = f"{host}:{check_port(auth_port, 'Login (auth)')}"
    return f"{host}:{gp}", f"{host}:{hp}", auth


# --------------------------------------------------------------------------
# patching
# --------------------------------------------------------------------------

def ensure_keystore(log):
    if os.path.isfile(KEYSTORE):
        return
    log("Creating a signing key (kept in runtime/keystore) ...")
    os.makedirs(os.path.dirname(KEYSTORE), exist_ok=True)
    run([find_keytool(), "-genkeypair", "-keystore", KEYSTORE, "-alias", "key",
         "-storepass", "android", "-keypass", "android", "-keyalg", "RSA",
         "-keysize", "2048", "-validity", "10000", "-dname", "CN=Debug"], log)


def patch_apk(apk_path, grpc_addr, http_addr, auth_host, log=no_log, output=None):
    left = missing({"scripts", "java", "apktool", "signer"})
    if left:
        raise PatchError("Run setup first. Missing: " + ", ".join(left))
    apk_path = os.path.abspath(apk_path or "")
    if not os.path.isfile(apk_path):
        raise PatchError("Choose the original game APK first (file not found).")
    output = os.path.abspath(output or os.path.join(OUTPUT, "patched.apk"))
    if output == apk_path:
        raise PatchError("The output file must be different from the original APK.")

    java = find_java()
    apktool = [java, "-jar", os.path.join(TOOLS, APKTOOL_JAR)]
    script = os.path.join(scripts_root(), "android", "patch_apk.py")
    decoded = os.path.join(WORK, "p")
    unaligned = os.path.join(WORK, "u.apk")
    signed_dir = os.path.join(WORK, "s")

    try:
        rmtree(WORK)
        os.makedirs(WORK)
        os.makedirs(FRAMEWORK_DIR, exist_ok=True)

        log("[1/5] Copying the APK ...")
        original = os.path.join(WORK, "o.apk")
        shutil.copyfile(apk_path, original)
        log(f"  {os.path.getsize(original) / 1048576:.1f} MB")

        log("[2/5] Unpacking (this can take a few minutes) ...")
        run(apktool + ["d", original, "-o", decoded, "-f", "-p", FRAMEWORK_DIR], log)

        log("[3/5] Patching ...")
        cmd = python_cmd(script) + [decoded, "--grpc-addr", grpc_addr, "--http-addr", http_addr]
        if auth_host:
            cmd += ["--auth-host", auth_host]
        # The script ends with manual "rebuild with ..." hints that do not
        # apply here (the next steps do that), so stop echoing after "Done".
        seen_done = []

        def patch_echo(line):
            if not seen_done:
                log(line)
            if "[+] Done" in line:
                seen_done.append(True)

        patch_log = run(cmd, patch_echo)
        if not any("[+] Done" in line for line in patch_log):
            raise PatchError("The patch script did not finish. Is this the right APK (version 3.7.1)?")
        warnings = [l.strip() for l in patch_log if "[!]" in l]
        # Normal with an IP address: only the short-name metadata slot is
        # skipped, the login redirect itself is still patched.
        serious = [w for w in warnings if "skipping metadata patch" not in w]
        if any("NOT FOUND" in w or "Bad magic" in w or "No table entry" in w for w in serious):
            raise PatchError(
                "The patch script could not find the game's server addresses in this APK. "
                "Use the ORIGINAL, unpatched 3.7.1 APK."
            )

        log("[4/5] Rebuilding (this is the slow part) ...")
        run(apktool + ["b", decoded, "-o", unaligned, "-p", FRAMEWORK_DIR], log)

        log("[5/5] Aligning and signing ...")
        ensure_keystore(log)
        run([java, "-jar", os.path.join(TOOLS, SIGNER_JAR), "--apks", unaligned,
             "--ks", KEYSTORE, "--ksAlias", "key", "--ksPass", "android",
             "--ksKeyPass", "android", "--out", signed_dir, "--allowResign"], log)
        signed = glob.glob(os.path.join(signed_dir, "*.apk"))
        if len(signed) != 1:
            raise PatchError("Signing did not produce an APK. See the log above.")

        os.makedirs(os.path.dirname(output), exist_ok=True)
        if os.path.exists(output):
            os.remove(output)
        shutil.move(signed[0], output)
    finally:
        rmtree(WORK)

    log("")
    if serious:
        log("Finished with warnings from the patch script:")
        for w in serious:
            log("  " + w)
    log(f"Done! Patched APK: {output} ({os.path.getsize(output) / 1048576:.1f} MB)")
    log("Install it on your phone or emulator (uninstall an older copy first if it refuses).")
    return output


def patch_masterdata(input_path, log=no_log, output=None):
    left = missing({"python", "scripts"})
    if left:
        raise PatchError("Run setup first. Missing: " + ", ".join(left))
    input_path = os.path.abspath(input_path or "")
    if not os.path.isfile(input_path):
        raise PatchError(f"Choose the original {MASTERDATA_NAME} first (file not found).")
    output = os.path.abspath(output or os.path.join(OUTPUT, MASTERDATA_NAME))
    if output == input_path:
        raise PatchError("The output file must be different from the original file.")
    os.makedirs(os.path.dirname(output), exist_ok=True)

    tmp = output + ".tmp"
    script = os.path.join(scripts_root(), "patch_masterdata.py")
    log("Patching master data ...")
    try:
        run(python_cmd(script) + ["--input", input_path, "--output", tmp], log)
        if not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            raise PatchError("The patch script did not write an output file.")
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    log("")
    log(f"Done! Patched master data: {output} ({os.path.getsize(output) / 1024:.1f} KB)")
    log("Copy it into rein/assets/release (replace the file there).")
    return output


# --------------------------------------------------------------------------
# APK check / compare (diagnostics)
# --------------------------------------------------------------------------

META_PATH = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
LIB_PATH = "lib/arm64-v8a/libil2cpp.so"
ORIGINAL_HOSTS = [b"api.app.nierreincarnation.com", b"https://web.app.nierreincarnation.com",
                  b"https://resources-api.app.nierreincarnation.com/"]
SIG_BLOCK_IDS = {0x7109871A: "v2", 0xF05368C0: "v3", 0x1B93AD61: "v3.1"}


def load_il2cpp_patches():
    """The byte patches the current patch_apk.py applies, or [] if unavailable."""
    root = scripts_root()
    if not root:
        return []
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lunar_patch_apk", os.path.join(root, "android", "patch_apk.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return [(p["name"], p["rva"], bytes(p["bytes"])) for p in mod.IL2CPP_PATCHES]
    except Exception:
        return []


def signature_schemes(path, zf):
    schemes = []
    if any(n.startswith("META-INF/") and n.upper().endswith((".RSA", ".DSA", ".EC")) for n in zf.namelist()):
        schemes.append("v1")
    try:
        cd = zf.start_dir
        with open(path, "rb") as fh:
            fh.seek(cd - 24)
            tail = fh.read(24)
            if tail[8:] == b"APK Sig Block 42":
                size = int.from_bytes(tail[:8], "little")
                fh.seek(cd - size - 8)
                block = fh.read(size + 8)[8:-24]
                pos = 0
                while pos + 12 <= len(block):
                    n = int.from_bytes(block[pos:pos + 8], "little")
                    ident = int.from_bytes(block[pos + 8:pos + 12], "little")
                    if ident in SIG_BLOCK_IDS:
                        schemes.append(SIG_BLOCK_IDS[ident])
                    pos += 8 + n
    except Exception:
        pass
    return schemes


def data_offset(path_fh, info):
    path_fh.seek(info.header_offset)
    hdr = path_fh.read(30)
    return info.header_offset + 30 + int.from_bytes(hdr[26:28], "little") + int.from_bytes(hdr[28:30], "little")


def diff_regions(a, b, limit=60):
    """Byte ranges where a and b differ (same-length data), merged when close."""
    regions, chunk, n = [], 1 << 16, min(len(a), len(b))
    for base in range(0, n, chunk):
        ca, cb = a[base:base + chunk], b[base:base + chunk]
        if ca == cb:
            continue
        i = 0
        while i < len(ca):
            if ca[i] != cb[i]:
                j = i + 1
                gap = 0
                k = j
                while k < len(ca) and gap < 8:
                    if ca[k] != cb[k]:
                        j, gap = k + 1, 0
                    else:
                        gap += 1
                    k += 1
                if regions and base + i - regions[-1][1] < 8:
                    regions[-1] = (regions[-1][0], base + j)
                else:
                    regions.append((base + i, base + j))
                if len(regions) > limit:
                    return regions
                i = j
            else:
                i += 1
    return regions


def show_bytes(data):
    data = data[:48]
    text = data.rstrip(b"\x00")
    if text and all(32 <= c < 127 for c in text):
        return '"' + text.decode("ascii") + '"'
    return data.hex()


def describe_apk(label, path, log, patches, name=None):
    """Print facts about one APK; returns dict of things reused by compare."""
    info = {"path": path}
    log(f"--- {label}: {name or os.path.basename(path)} ({os.path.getsize(path) / 1048576:.1f} MB)")
    with zipfile.ZipFile(path) as zf, open(path, "rb") as fh:
        names = set(zf.namelist())
        info["entries"] = {i.filename: i for i in zf.infolist()}
        log(f"  files inside: {len(names)}")
        schemes = signature_schemes(path, zf)
        log("  signature: " + (", ".join(schemes) if schemes else "NONE - this APK will not install"))

        bad_align = []
        for i in zf.infolist():
            if i.compress_type == 0 and i.file_size:
                off = data_offset(fh, i)
                if off % 4:
                    bad_align.append(i.filename)
        log("  alignment: " + ("OK" if not bad_align else f"NOT aligned ({len(bad_align)} files, e.g. {bad_align[0]})"))
        arsc = info["entries"].get("resources.arsc")
        if arsc:
            log("  resources.arsc: " + ("stored (OK)" if arsc.compress_type == 0 else "COMPRESSED (Android 11+ refuses this)"))
        libs = sorted(n for n in names if n.startswith("lib/") and n.endswith(".so"))
        abis = sorted({n.split("/")[1] for n in libs})
        stored = sum(1 for n in libs if info["entries"][n].compress_type == 0)
        log(f"  native libraries: {len(libs)} ({', '.join(abis) or 'none'}), {stored} stored / {len(libs) - stored} compressed")
        dex = sorted(n for n in names if re.fullmatch(r"classes\d*\.dex", n))
        log(f"  dex files: {len(dex)}")
        log("  network_security_config.xml: " + ("present" if "res/xml/network_security_config.xml" in names else "MISSING"))

        if META_PATH in names:
            meta = zf.read(META_PATH)
            info["meta"] = meta
            left = [h.decode() for h in ORIGINAL_HOSTS if h in meta]
            m = re.search(rb"(http://[^\x00/]{1,40})/assets/release/\{0\}/database\.bin", meta)
            log("  server address in game data: " + (m.group(1).decode("ascii", "replace") if m else "not found"))
            log("  original (official) addresses still present: " + (", ".join(left) if left else "none (good)"))
        else:
            log(f"  {META_PATH}: MISSING")

        if LIB_PATH in names:
            lib = zf.read(LIB_PATH)
            info["lib"] = lib
            log(f"  libil2cpp.so: {len(lib) / 1048576:.1f} MB")
            if patches:
                applied = [n for n, rva, b in patches if lib[rva:rva + len(b)] == b]
                missing_p = [n for n, rva, b in patches if lib[rva:rva + len(b)] != b]
                log(f"  code patches from the current scripts: {len(applied)} of {len(patches)} present")
                for n in missing_p:
                    log(f"      not present: {n}")
            port_at = 0x361D548
            word = int.from_bytes(lib[port_at:port_at + 4], "little")
            if word & 0xFFE0001F == 0x52800000 and lib[port_at + 4:port_at + 8] == bytes.fromhex("c0035fd6"):
                log(f"  game port baked in: {(word >> 5) & 0xFFFF}")
            else:
                log("  game port baked in: none (uses 443)")
        else:
            log(f"  {LIB_PATH}: MISSING")
    return info


def check_apk(apk, compare=None, log=no_log, names=(None, None)):
    apk = os.path.abspath(apk or "")
    if not os.path.isfile(apk):
        raise PatchError("Choose the APK to check first (file not found).")
    if compare:
        compare = os.path.abspath(compare)
        if not os.path.isfile(compare):
            raise PatchError("The APK to compare with was not found.")
    patches = load_il2cpp_patches()
    log("APK CHECK REPORT")
    try:
        a = describe_apk("APK A (to check)", apk, log, patches, names[0])
        if not compare:
            log("")
            log("Tip: choose a known-good APK in 'Compare with' to see exactly what differs.")
            return
        log("")
        b = describe_apk("APK B (compare with)", compare, log, patches, names[1])
    except zipfile.BadZipFile:
        raise PatchError("That file is not a valid APK (it is not a zip archive).")

    log("")
    log("--- Differences between A and B")
    ea, eb = a["entries"], b["entries"]
    only_a = sorted(n for n in ea if n not in eb and not n.startswith("META-INF/"))
    only_b = sorted(n for n in eb if n not in ea and not n.startswith("META-INF/"))
    changed = sorted(n for n in ea if n in eb and not n.startswith("META-INF/")
                     and (ea[n].CRC != eb[n].CRC or ea[n].file_size != eb[n].file_size))
    method = sorted(n for n in ea if n in eb and ea[n].compress_type != eb[n].compress_type)
    log(f"  files only in A: {len(only_a)}")
    for n in only_a[:25]:
        log(f"      {n}")
    log(f"  files only in B: {len(only_b)}")
    for n in only_b[:25]:
        log(f"      {n}")
    log(f"  files with different content: {len(changed)}")
    for n in changed[:60]:
        log(f"      {n}  (A {ea[n].file_size} bytes, B {eb[n].file_size} bytes)")
    if len(changed) > 60:
        log(f"      ... and {len(changed) - 60} more")
    log(f"  files stored differently (compressed vs not): {len(method)}")
    for n in method[:15]:
        log(f"      {n}  (A {'stored' if ea[n].compress_type == 0 else 'compressed'}, "
            f"B {'stored' if eb[n].compress_type == 0 else 'compressed'})")

    names = {rva: n for n, rva, _b in patches}
    for key, title in (("meta", "global-metadata.dat"), ("lib", "libil2cpp.so")):
        if key not in a or key not in b:
            continue
        da, db = a[key], b[key]
        log("")
        if da == db:
            log(f"  {title}: identical")
            continue
        if len(da) != len(db):
            log(f"  {title}: different sizes (A {len(da)}, B {len(db)}) - not the same base game version?")
            continue
        regions = diff_regions(da, db)
        log(f"  {title}: {len(regions)}{'+' if len(regions) > 60 else ''} differing spots")
        for start, end in regions[:60]:
            tag = ""
            for rva, n in names.items():
                if rva <= start < rva + 8:
                    tag = f"  [{n}]"
            log(f"      0x{start:X}: A {show_bytes(da[start:end])} | B {show_bytes(db[start:end])}{tag}")
    log("")
    log("End of report.")


# --------------------------------------------------------------------------
# window (a local web page) helpers
# --------------------------------------------------------------------------

def detect_ips():
    """IPv4 addresses of this PC's network adapters (no data is sent)."""
    found = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        found.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ip.startswith("127.") and ip != "0.0.0.0"]


# Files chosen in the page are copied here (fixed names, so nothing the page
# sends can choose where a file is written).
INBOX = os.path.join(RUNTIME, "inbox")
SLOTS = ("apk", "md", "chkA", "chkB")
CHOSEN = {}  # slot -> original file name


def slot_path(slot):
    return os.path.join(INBOX, slot + ".bin")


def chosen_file(slot, what):
    if slot not in CHOSEN or not os.path.isfile(slot_path(slot)):
        raise PatchError(f"Choose {what} first.")
    return slot_path(slot)


class Job:
    """One background task at a time, with a log the page can poll."""

    def __init__(self):
        self.lock = threading.Lock()
        self.lines = []
        self.running = False
        self.name = ""
        self.result = ""  # "", "ok" or "error"

    def log(self, line):
        with self.lock:
            self.lines.append(line)

    def start(self, name, func):
        with self.lock:
            if self.running:
                raise PatchError("Something is already running. Wait for it to finish.")
            self.running, self.name, self.result, self.lines = True, name, "", []

        def worker():
            result = "ok"
            try:
                func()
            except PatchError as exc:
                self.log("")
                self.log(f"ERROR: {exc}")
                result = "error"
            except Exception as exc:  # unexpected
                self.log("")
                self.log(f"ERROR: {type(exc).__name__}: {exc}")
                result = "error"
            with self.lock:
                self.running, self.result = False, result

        threading.Thread(target=worker, daemon=True).start()

    def snapshot(self, since):
        with self.lock:
            return {"running": self.running, "name": self.name, "result": self.result,
                    "lines": self.lines[since:], "total": len(self.lines)}


JOB = Job()
TOKEN = secrets.token_urlsafe(16)
SERVER = [None]


def api(action, data):
    if action == "state":
        snap = JOB.snapshot(int(data.get("since", 0)))
        snap["components"] = components()
        snap["windows"] = IS_WINDOWS
        return snap
    if action == "setup":
        update = bool(data.get("update_scripts"))
        JOB.start("setup", lambda: setup(JOB.log, update_scripts=update))
        return {}
    if action == "detect_ip":
        return {"ips": detect_ips()}
    if action == "patch_apk":
        auth_port = data.get("auth_port") if data.get("use_auth") else None
        grpc, http_addr, auth = build_addresses(
            data.get("host"), data.get("grpc_port"), data.get("http_port"), auth_port)
        apk = chosen_file("apk", "the original game APK")
        JOB.start("apk", lambda: patch_apk(apk, grpc, http_addr, auth, JOB.log))
        return {}
    if action == "patch_md":
        src = chosen_file("md", "the original " + MASTERDATA_NAME)
        JOB.start("masterdata", lambda: patch_masterdata(src, JOB.log))
        return {}
    if action == "check":
        apk = chosen_file("chkA", "the APK to check")
        ref = slot_path("chkB") if "chkB" in CHOSEN and os.path.isfile(slot_path("chkB")) else None
        names = (CHOSEN.get("chkA"), CHOSEN.get("chkB"))
        JOB.start("check", lambda: check_apk(apk, ref, JOB.log, names))
        return {}
    if action == "open_output":
        os.makedirs(OUTPUT, exist_ok=True)
        if IS_WINDOWS:
            os.startfile(OUTPUT)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", OUTPUT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {}
    if action == "quit":
        threading.Thread(target=SERVER[0].shutdown, daemon=True).start()
        return {}
    raise PatchError("Unknown action.")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "NierPatcher"

    def log_message(self, *_args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _upload(self, query, length):
        """Receive a file chosen in the page into runtime/inbox/<slot>.bin."""
        slot = query.get("slot", [""])[0]
        name = os.path.basename(query.get("name", ["file"])[0].replace("\\", "/"))[:200]
        if slot not in SLOTS:
            self.close_connection = True
            raise PatchError("Unknown file slot.")
        if JOB.running:
            self.close_connection = True
            raise PatchError("Wait for the current task to finish before choosing another file.")
        os.makedirs(INBOX, exist_ok=True)
        CHOSEN.pop(slot, None)
        part = slot_path(slot) + ".part"
        left = length
        try:
            with open(part, "wb") as out:
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        raise PatchError("The file transfer was interrupted.")
                    out.write(chunk)
                    left -= len(chunk)
            os.replace(part, slot_path(slot))
        except OSError as exc:
            self.close_connection = True
            raise PatchError(f"Could not save the file ({exc}). Is the disk full?")
        finally:
            if os.path.exists(part):
                os.remove(part)
        CHOSEN[slot] = name
        return {"name": name, "size": length}

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        token = urllib.parse.parse_qs(url.query).get("t", [""])[0]
        if url.path != "/" or not self._host_ok() or not secrets.compare_digest(token, TOKEN):
            return self._send(404, b"Not found", "text/plain")
        with open(os.path.join(APP_DIR, "ui.html"), "rb") as fh:
            page = fh.read().replace(b"__TOKEN__", TOKEN.encode())
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self):
        token = self.headers.get("X-Token") or ""
        if not self._host_ok() or not secrets.compare_digest(token, TOKEN) \
                or not self.path.startswith("/api/"):
            return self._send(403, b"{}", "application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            url = urllib.parse.urlparse(self.path)
            if url.path == "/api/upload":
                result = self._upload(urllib.parse.parse_qs(url.query), length)
            else:
                data = json.loads(self.rfile.read(length) or b"{}")
                result = api(url.path[len("/api/"):], data)
            result["ok"] = True
        except PatchError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._send(200, json.dumps(result).encode(), "application/json")


def gui(open_browser=True):
    rmtree(INBOX)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    SERVER[0] = server
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={TOKEN}"
    print("NieR Re[in]carnation offline patcher is running.")
    print("A page should open in your web browser. If it does not, open this address:")
    print("  " + url)
    print("Keep this window open while you use the patcher. Close it to quit.")
    sys.stdout.flush()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    rmtree(INBOX)
    print("Patcher closed.")


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="NieR Re[in]carnation offline patcher")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gui", help="open the patcher window (default)")
    g.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    s = sub.add_parser("setup", help="download the tools into the runtime folder")
    s.add_argument("--update-scripts", action="store_true", help="re-download the patch scripts")
    a = sub.add_parser("apk", help="patch the APK")
    a.add_argument("--apk", required=True)
    a.add_argument("--ip", required=True, help="server IP or host name")
    a.add_argument("--grpc-port", default="8003")
    a.add_argument("--http-port", default="8080")
    a.add_argument("--auth-port", default="3000", help="0 to skip the login patch")
    a.add_argument("--output")
    m = sub.add_parser("masterdata", help="patch the master data file")
    m.add_argument("--input", required=True)
    m.add_argument("--output")
    c = sub.add_parser("check", help="inspect an APK, optionally compare with another")
    c.add_argument("--apk", required=True)
    c.add_argument("--compare")
    args = ap.parse_args()

    try:
        if args.cmd in (None, "gui"):
            gui(open_browser=not getattr(args, "no_browser", False))
        elif args.cmd == "setup":
            setup(print, update_scripts=args.update_scripts)
        elif args.cmd == "apk":
            grpc, http_addr, auth = build_addresses(args.ip, args.grpc_port, args.http_port, args.auth_port)
            patch_apk(args.apk, grpc, http_addr, auth, print, args.output)
        elif args.cmd == "check":
            check_apk(args.apk, args.compare, print)
        elif args.cmd == "masterdata":
            patch_masterdata(args.input, print, args.output)
    except PatchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
