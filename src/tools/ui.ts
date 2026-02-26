/**
 * UI/Process management tools for KiCAD MCP server
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

export function registerUITools(server: McpServer, callKicadScript: Function) {
  // Check if KiCAD UI is running
  server.tool(
    "check_kicad_ui",
    "Check if KiCAD UI is currently running",
    {},
    async () => {
      logger.info('Checking KiCAD UI status');
      const result = await callKicadScript("check_kicad_ui", {});
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Launch KiCAD UI
  server.tool(
    "launch_kicad_ui",
    "Launch KiCAD UI, optionally with a project file",
    {
      projectPath: z.string().optional().describe("Optional path to .kicad_pro/.kicad_pcb/.kicad_sch file to open"),
      autoLaunch: z.boolean().optional().describe("Whether to launch KiCAD if not running (default: true)")
    },
    async (args: { projectPath?: string; autoLaunch?: boolean }) => {
      logger.info(`Launching KiCAD UI${args.projectPath ? ' with project: ' + args.projectPath : ''}`);
      const result = await callKicadScript("launch_kicad_ui", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  server.tool(
    "open_schematic_editor",
    "Open schematic in KiCAD Schematic Editor (.kicad_sch preferred)",
    {
      schematicPath: z.string().optional().describe("Optional path to .kicad_sch file"),
      projectPath: z.string().optional().describe("Optional project/board path; .kicad_sch is derived if possible"),
      autoLaunch: z.boolean().optional().describe("Whether to launch KiCAD if not running (default: true)")
    },
    async (args: { schematicPath?: string; projectPath?: string; autoLaunch?: boolean }) => {
      logger.info(`Opening Schematic Editor${args.schematicPath ? ' with schematic: ' + args.schematicPath : ''}`);
      const result = await callKicadScript("open_schematic_editor", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  logger.info('UI management tools registered');
}
