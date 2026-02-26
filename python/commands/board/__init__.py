"""
Board-related command implementations for KiCAD interface
"""

import pcbnew
import logging
from typing import Dict, Any, Optional

# Import specialized modules
from .size import BoardSizeCommands
from .layers import BoardLayerCommands
from .outline import BoardOutlineCommands
from .view import BoardViewCommands

logger = logging.getLogger('kicad_interface')

class BoardCommands:
    """Handles board-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self._board = board

        # Initialize specialized command classes
        self.size_commands = BoardSizeCommands(board)
        self.layer_commands = BoardLayerCommands(board)
        self.outline_commands = BoardOutlineCommands(board)
        self.view_commands = BoardViewCommands(board)

    @property
    def board(self):
        """Get current board reference"""
        return self._board

    @board.setter
    def board(self, value):
        """Set board reference and propagate to all nested command handlers"""
        self._board = value
        # Automatically propagate to all nested command objects
        self.size_commands.board = value
        self.layer_commands.board = value
        self.outline_commands.board = value
        self.view_commands.board = value
        logger.debug(f"BoardCommands: board reference updated and propagated to all sub-commands. board is None: {value is None}")

    # Delegate board size commands
    def set_board_size(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the size of the PCB board"""
        return self.size_commands.set_board_size(params)

    # Delegate layer commands
    def add_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new layer to the PCB"""
        return self.layer_commands.add_layer(params)

    def set_active_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the active layer for PCB operations"""
        return self.layer_commands.set_active_layer(params)

    def get_layer_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all layers in the PCB"""
        return self.layer_commands.get_layer_list(params)

    # Delegate board outline commands
    def add_board_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a board outline to the PCB"""
        return self.outline_commands.add_board_outline(params)

    def add_mounting_hole(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a mounting hole to the PCB"""
        return self.outline_commands.add_mounting_hole(params)

    def add_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add text annotation to the PCB"""
        return self.outline_commands.add_text(params)

    # Delegate view commands
    def get_board_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current board"""
        logger.info(f"BoardCommands.get_board_info() called. self.board is None: {self.board is None}")
        return self.view_commands.get_board_info(params)

    def get_board_2d_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a 2D image of the PCB"""
        return self.view_commands.get_board_2d_view(params)

    def get_board_extents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get the bounding box extents of the board"""
        return self.view_commands.get_board_extents(params)
