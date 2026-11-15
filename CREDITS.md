# Credits

## The patching itself

**lunar-tear** and **lunar-scripts**, by Walter-Sparrow (Ilya Groshev) and
contributors.

- Server: <https://github.com/Walter-Sparrow/lunar-tear> (MIT License)
- Patch scripts: <https://gitlab.com/walter-sparrow-group/lunar-scripts>

Every change made to the APK and to the master data is made by their scripts,
`android/patch_apk.py` and `patch_masterdata.py`. Finding which bytes to
change in the game, and how, is their work. This tool only automates running
those scripts on a Windows PC.

The lunar-scripts repository had no license file when this tool was written
(November 2026). For that reason this repository does **not** contain a copy of
those scripts. The patcher downloads them from their official home on first
run, the same way the original Colab notebook does, and runs them unmodified.

If the lunar-tear authors would like this handled differently, please open an
issue here.

## Tools downloaded on first run

These are fetched from their official sources into the `runtime` folder. They
are not redistributed in this repository.

| Tool | Version | Authors | License | Source |
|---|---|---|---|---|
| Apktool | 2.11.1 | Connor Tumbleson (iBotPeaches), Ryszard Wiśniewski and contributors | Apache License 2.0 | <https://github.com/iBotPeaches/Apktool> |
| uber-apk-signer | 1.3.0 | Patrick Favre (patrickfav) | Apache License 2.0 | <https://github.com/patrickfav/uber-apk-signer> |
| Eclipse Temurin JRE | 17.0.15+6 | Eclipse Adoptium project | GPLv2 with Classpath Exception | <https://adoptium.net> |
| Python (embeddable build) | 3.12.10 | Python Software Foundation | PSF License | <https://www.python.org> |

## Python packages included in this repository

`runtime/libs` holds the unpacked, unmodified Windows wheels of three packages.
Their license files are inside each package's `*.dist-info` folder, and
`runtime/README.md` lists the exact wheels and their checksums.

| Package | Version | License |
|---|---|---|
| pycryptodome | 4.4.0 | BSD 2-Clause, public domain (Unlicense) and MIT parts |
| msgpack | 1.2.4 | Apache License 2.0 |
| lz4 (python-lz4) | 4.4.5 | BSD License |

## Documentation

The community setup guide for lunar-tear, whose step 4 (the Google Colab
notebook) this tool replaces.

## This tool

- Idea, requirements and testing: [cloudhaacker](https://github.com/cloudhaacker)
- Code, research, documentation and screenshots: Claude, an AI model made by
  Anthropic (Claude Fable 5.2), working from the owner's direction

## The game

NieR Re[in]carnation was developed by Applibot and published by Square Enix.
This project is not affiliated with either company and distributes none of
their files.
