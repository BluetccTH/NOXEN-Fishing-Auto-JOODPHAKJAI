# [ NOXEN ] - Fishing Auto JOODPHAKJAI

**Windows fishing automation prototype · V5.3 Recovery · Dark UI**

[ภาษาไทย](README_TH.txt) · [Changelog](CHANGELOG_TH.txt)

NOXEN is a Python desktop application that reads selected Roblox UI regions and automates the fishing loop. The interface uses a Deep Navy / Teal dark theme.

<img width="1529" height="860" alt="Fishing Auto JOODPHAKJAI" src="https://github.com/user-attachments/assets/9b5b01d5-0da1-4c47-84a1-25a04f2d9841" />

## Features

- Detects the Roblox window automatically.
- Calibrates four screen regions (cast point, charge meter, reel minigame, progress bar).
- Reads the vertical charge meter and releases the cast at a configurable threshold.
- Uses a Fisch-style reel controller: hold to move the control bar right, release to let it move left, and track the fish marker.
- Repeats fishing rounds after a completed minigame.
- Smart recovery for temporary detection failures, including safe mouse release and retry delays.
- Waits for Roblox to return to the foreground before sending further input.
- Debug snapshots (PNG + JSON), logs, and import/export of configuration.

## Requirements

- Windows 10 or Windows 11
- Python 3.10+
- Internet access on first launch so the launcher can install Python dependencies

## Run

1. Download this repository using **Code → Download ZIP** and extract it.
2. Open Roblox and keep its window visible.
3. Run `Run.bat`.
4. In **ตั้งค่าพื้นที่** (Region Setup), calibrate:
   - **A** — cast point on the water
   - **B** — the full vertical charge meter
   - **C** — the full reel rail, including the control bar and fish marker
   - **D** — the full progress bar
5. Use the vision test while each corresponding UI is visible.
6. Press **F6** once to start the automatic loop.

## Hotkeys

| Key | Action |
|---|---|
| F6 | Start automatic fishing |
| F7 | Emergency stop and release mouse |
| F8 | Show the control panel and stop the bot |

The loop continues until **F7** is pressed or the application is closed.

## Safety and limitations

- Roblox must remain visible and in the foreground. This build does not provide background game control.
- When Roblox loses focus or is minimized, the bot releases the mouse and waits. It does not send clicks to another application.
- Vision is heuristic-based. Correct A/B/C/D calibration and the game's current UI layout are important.
- The project was tested with its included unit tests (11/11 passed) and supplied screenshots. Real-time mouse control still needs to be validated on the target PC and game session.
- Use this tool responsibly and follow the applicable game and platform rules.

## Project layout

```text
app.py                 Desktop UI and calibration
core/engine.py         Fishing state machine and recovery loop
core/vision.py         Charge, reel, fish-marker, and progress detection
core/win32.py          Roblox window detection and coordinate mapping
core/input_win.py      Windows mouse input
core/debug.py          Vision tests and debug snapshots
ui/overlay.py          Region-selection overlay
tests/                 Unit tests
Run.bat                Setup dependencies and launch
Setup.bat              Install dependencies only
```

## Tests

Run the local tests with:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Version

Current source: **V5.3 Recovery — NOXEN Dark UI Edition**  
See [VERSION.txt](VERSION.txt) and [CHANGELOG_TH.txt](CHANGELOG_TH.txt).

No license file is included at this time. All rights remain with the project author unless a license is added.

[👉 Tutorial video.](https://vt.tiktok.com/ZSsNFh6jn/)
