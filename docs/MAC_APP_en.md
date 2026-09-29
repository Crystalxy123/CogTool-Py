# CogTool for Mac — English Edition

This desktop edition packages CogTool-Py 0.2.1rc1 in a native macOS application. The English interface lets you open a model, select a task, run a prediction, and inspect the results. The Python calculation engine is included; you do not need to install Python, Java, or Lisp, or connect to the internet to use the app.

## Install and use

Requires an **Apple Silicon Mac (M series) running macOS 15.0 or later**. The build and verification environment is macOS 15.6 arm64. Other macOS versions and Intel Macs have not been verified.

1. Open `CogTool-0.2.1rc1-macOS-arm64-English.dmg` and drag `CogTool.app` to the `Applications` shortcut. Alternatively, extract the English ZIP and move the app to Applications.
2. Double-click `CogTool.app`. Start with a bundled example or open a JSON model in this project's format.
3. Select a task and run its prediction. Review the predicted time, generated steps, and model information. Open the output folder to inspect `result.json`, `events.csv`, `steps.csv`, and the saved `input.json`. Some integrated engine results also include motor and vision event CSV files.
4. Each prediction uses a new output folder to preserve earlier results. An unsupported or incomplete calculation is reported as such; a missing total time is not a completed prediction.

The app has a local **ad-hoc signature**, without an Apple Developer ID signature or notarization. Another Mac may display a security prompt after downloading it. If you trust the delivered file and macOS blocks it because the developer cannot be verified, use **System Settings → Privacy & Security → Open Anyway**. Do not disable system security protections.

## Models and scope

The desktop app uses the existing calculation engine and the configuration saved in each input. It does not automatically switch engines or change parameters. Its four bundled examples have English display names. Their numeric parameters, geometry, actions, identifiers, and other calculation settings are preserved. Example click and key durations remain explicitly stated modeling assumptions.

The app reads this project's schema 1/2 JSON models and saves schema 2. It does not provide the original CogTool visual model editor or a general `.cgt` importer. Full ACT-R, general visual search, and arbitrary interactive design editing are outside the supported scope. To change a model, edit its JSON and reopen it. Official materials and benchmarks marked `LOCAL_ONLY` are excluded from the installer. See `docs/SUPPORTED_FEATURES.md` and `docs/LIMITATIONS.md` in the source archive for the detailed scope.

The interface and desktop examples are English. Existing source comments, historical documentation, and license notices retain their original language. User-provided model names are displayed as supplied.

## Delivered files and source

The English build writes to `dist/macos-en/` and preserves the earlier Chinese delivery in `dist/macos/`:

- `CogTool.app`: the complete application.
- `CogTool-0.2.1rc1-macOS-arm64-English.dmg`: installer image with an Applications shortcut.
- `CogTool-0.2.1rc1-macOS-arm64-English.zip`: ZIP copy of the application.
- `CogTool-0.2.1rc1-source-English.tar.gz`: calculation engine, desktop interface, English examples, documentation, licenses, and build scripts.
- `CogTool-0.2.1rc1-build-report-English.json`: build environment, file hashes, and verification results.

In Finder, right-click the app and choose **Show Package Contents**. `Contents/Resources/` contains `Examples`, `Licenses`, `Source`, `English User Guide.md`, and a build manifest. The `engine/cogtool-engine` executable and its `_internal` directory contain the bundled Python runtime and calculation engine. Running the app does not require the development checkout or Homebrew.

The project remains licensed under LGPL-2.1-or-later. The original `LICENSE`, `NOTICE.md`, and ACT-R license notice are included. Python, the PyInstaller bootloader, and bundled native dependencies retain their respective licenses. Corresponding project source and build scripts accompany the application. Official projects, papers, and historical Java/Lisp runtimes are not included. This local delivery does not publish the software to a public service.

## Rebuild from source

Building requires an Apple Silicon Mac with macOS 15 or later, Apple Command Line Tools including Swift and the macOS SDK, and Python 3.11 or later with virtual environment support. The verified build setup uses Python 3.11.15, Swift 6.2.3, and macOS SDK 26.2. The script explicitly sets the deployment target to macOS 15.0; this is not a claim that every 15.x version has been tested.

From the extracted source directory or project root:

```sh
python3.11 -m venv .desktop-build-venv
.desktop-build-venv/bin/python -m pip install -r desktop/macos/requirements-build.txt
.desktop-build-venv/bin/python scripts/build_macos_app.py
```

Only dependency installation needs access to a package index. The build script itself does not use the network. Build dependency versions are pinned. The script packages the Python engine, compiles the SwiftUI interface, creates the CT icon, signs the app locally, and generates the English DMG and ZIP. macOS icon and disk-image tools require access to system services; a restricted build environment may need permission to run those tools.

The script checks every task in all four English examples against the source engine. It compares complete results, excluding only measured program runtime, including predicted times, events, steps, and source fingerprints. Frozen checks run from an independent directory with no external Python in `PATH`. The script also checks the package's built-in example, verifies the application signature, and verifies the DMG. These automated checks supplement opening the actual app and exercising its interface.

Existing English delivery files cause the script to stop. To replace this version's English delivery after a successful new build:

```sh
.desktop-build-venv/bin/python scripts/build_macos_app.py --replace
```

`--replace` affects only the named English artifacts in `dist/macos-en/`. It preserves `dist/macos/` and the original `CogTool.dmg` in the project root. Intermediate runs are retained in `build/macos/runs/`; compilation caches are in `build/macos/cache/`. Source archives use stable ordering and metadata for identical inputs. Application signatures, timestamps, and system-tool outputs are not promised to be byte-for-byte reproducible.
