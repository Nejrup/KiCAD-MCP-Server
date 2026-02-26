#!/usr/bin/env python3
"""
Diagnostic script to test pcbnew.LoadBoard() and identify why
the Duck Stand board fails to load properly via the MCP server.

Run this with KiCad's Python:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/*/bin/python3 diagnose_board_load.py
"""

import sys
import os

# Add KiCad Python paths
if sys.platform == 'darwin':
    for version in ['3.9', '3.10', '3.11', '3.12', '3.13']:
        path = f'/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/{version}/lib/python{version}/site-packages'
        if os.path.exists(path) and path not in sys.path:
            sys.path.insert(0, path)

print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"sys.path: {sys.path[:5]}...")
print()

try:
    import pcbnew
    print(f"pcbnew imported from: {pcbnew.__file__}")
    print(f"pcbnew version: {pcbnew.GetBuildVersion()}")
    print()
except ImportError as e:
    print(f"FAILED to import pcbnew: {e}")
    sys.exit(1)

# Test 1: Create a new board
print("=" * 60)
print("TEST 1: Create new board with pcbnew.BOARD()")
print("=" * 60)
try:
    board = pcbnew.BOARD()
    print(f"  board = {board}")
    print(f"  type(board) = {type(board)}")
    print(f"  board is None: {board is None}")
    print(f"  bool(board): {bool(board)}")
    print(f"  Result: PASS")
except Exception as e:
    print(f"  FAILED: {e}")

print()

# Test 2: Load the Duck Stand board
board_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'Duck_Stand_Charge_Board',
    'Duck_Stand_Charge_Board.kicad_pcb'
)
board_path = os.path.abspath(board_path)

print("=" * 60)
print(f"TEST 2: Load Duck Stand board")
print(f"  Path: {board_path}")
print(f"  Exists: {os.path.exists(board_path)}")
print("=" * 60)

if os.path.exists(board_path):
    try:
        board2 = pcbnew.LoadBoard(board_path)
        print(f"  board2 = {board2}")
        print(f"  type(board2) = {type(board2)}")
        print(f"  board2 is None: {board2 is None}")

        if board2 is not None:
            try:
                print(f"  bool(board2): {bool(board2)}")
            except Exception as e:
                print(f"  bool(board2) FAILED: {e}")

            try:
                print(f"  GetFileName(): {board2.GetFileName()}")
            except Exception as e:
                print(f"  GetFileName() FAILED: {e}")

            try:
                bbox = board2.GetBoardEdgesBoundingBox()
                print(f"  BBox width: {bbox.GetWidth() / 1e6} mm")
                print(f"  BBox height: {bbox.GetHeight() / 1e6} mm")
            except Exception as e:
                print(f"  GetBoardEdgesBoundingBox() FAILED: {e}")

            try:
                footprints = board2.GetFootprints()
                print(f"  Footprint count: {len(footprints)}")
            except Exception as e:
                print(f"  GetFootprints() FAILED: {e}")

            try:
                nets = board2.GetNetInfo()
                print(f"  Net count: {nets.GetNetCount()}")
            except Exception as e:
                print(f"  GetNetInfo() FAILED: {e}")

            # Check SWIG ownership
            try:
                print(f"  board2.thisown: {board2.thisown}")
            except AttributeError:
                print(f"  board2.thisown: (attribute not available)")

            print(f"  Result: PASS")
        else:
            print(f"  Result: FAIL - LoadBoard returned None")

    except Exception as e:
        print(f"  FAILED with exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"  SKIPPED - file not found")
    # Try alternative path
    alt_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'Duck_Stand_Charge_Board', 'Duck_Stand_Charge_Board.kicad_pcb'
    )
    print(f"  Try alternative: {alt_path}")
    print(f"  Alt exists: {os.path.exists(alt_path)}")

print()

# Test 3: Save and reload cycle
print("=" * 60)
print("TEST 3: Create board, save to /tmp, reload")
print("=" * 60)
try:
    board3 = pcbnew.BOARD()
    tmp_path = "/tmp/test_mcp_diag.kicad_pcb"
    board3.SetFileName(tmp_path)
    pcbnew.SaveBoard(tmp_path, board3)
    print(f"  Saved to: {tmp_path}")

    board3_reload = pcbnew.LoadBoard(tmp_path)
    print(f"  Reloaded board: {board3_reload}")
    print(f"  Is None: {board3_reload is None}")
    if board3_reload is not None:
        print(f"  bool: {bool(board3_reload)}")
        print(f"  GetFileName: {board3_reload.GetFileName()}")
        print(f"  Result: PASS")
    else:
        print(f"  Result: FAIL - reload returned None")

    os.remove(tmp_path)
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback
    traceback.print_exc()

print()
print("Diagnostics complete.")
