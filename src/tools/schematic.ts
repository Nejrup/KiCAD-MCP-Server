/**
 * Schematic tools for KiCAD MCP server
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerSchematicTools(server: McpServer, callKicadScript: Function) {
  // Create schematic tool
  server.tool(
    "create_schematic",
    "Create a new schematic",
    {
      name: z.string().describe("Schematic name"),
      path: z.string().optional().describe("Optional path"),
    },
    async (args: { name: string; path?: string }) => {
      const result = await callKicadScript("create_schematic", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Add component to schematic
  server.tool(
    "add_schematic_component",
    "Add a component to the schematic. Symbol format is 'Library:SymbolName' (e.g., 'Device:R', 'EDA-MCP:ESP32-C3')",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      symbol: z.string().describe("Symbol library:name reference (e.g., Device:R, EDA-MCP:ESP32-C3)"),
      reference: z.string().describe("Component reference (e.g., R1, U1)"),
      value: z.string().optional().describe("Component value"),
      position: z.object({
        x: z.number(),
        y: z.number()
      }).optional().describe("Position on schematic"),
    },
    async (args: { schematicPath: string; symbol: string; reference: string; value?: string; position?: { x: number; y: number } }) => {
      // Transform to what Python backend expects
      const [library, symbolName] = args.symbol.includes(':')
        ? args.symbol.split(':')
        : ['Device', args.symbol];

      const transformed = {
        schematicPath: args.schematicPath,
        component: {
          library,
          type: symbolName,
          reference: args.reference,
          value: args.value,
          // Python expects flat x, y not nested position
          x: args.position?.x ?? 0,
          y: args.position?.y ?? 0
        }
      };

      const result = await callKicadScript("add_schematic_component", transformed);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Successfully added ${args.reference} (${args.symbol}) to schematic`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to add component: ${result.message || JSON.stringify(result)}`
          }]
        };
      }
    }
  );

  // Connect components with wire
  server.tool(
    "add_wire",
    "Add a wire connection in the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      start: z.object({
        x: z.number(),
        y: z.number()
      }).describe("Start position"),
      end: z.object({
        x: z.number(),
        y: z.number()
      }).describe("End position"),
    },
    async (args: { schematicPath: string; start: { x: number; y: number }; end: { x: number; y: number } }) => {
      const transformed = {
        schematicPath: args.schematicPath,
        startPoint: [args.start.x, args.start.y],
        endPoint: [args.end.x, args.end.y],
      };
      const result = await callKicadScript("add_schematic_wire", transformed);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Add pin-to-pin connection
  server.tool(
    "add_schematic_connection",
    "Connect two component pins with a wire",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      sourceRef: z.string().describe("Source component reference (e.g., R1)"),
      sourcePin: z.string().describe("Source pin name/number (e.g., 1, 2, GND)"),
      targetRef: z.string().describe("Target component reference (e.g., C1)"),
      targetPin: z.string().describe("Target pin name/number (e.g., 1, 2, VCC)")
    },
    async (args: { schematicPath: string; sourceRef: string; sourcePin: string; targetRef: string; targetPin: string }) => {
      const result = await callKicadScript("add_schematic_connection", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Successfully connected ${args.sourceRef}/${args.sourcePin} to ${args.targetRef}/${args.targetPin}`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to add connection: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Add net label
  server.tool(
    "add_schematic_net_label",
    "Add a net label to the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Name of the net (e.g., VCC, GND, SIGNAL_1)"),
      position: z.array(z.number()).length(2).describe("Position [x, y] for the label")
    },
    async (args: { schematicPath: string; netName: string; position: number[] }) => {
      const result = await callKicadScript("add_schematic_net_label", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Successfully added net label '${args.netName}' at position [${args.position}]`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to add net label: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Connect pin to net
  server.tool(
    "connect_to_net",
    "Connect a component pin to a named net",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      componentRef: z.string().describe("Component reference (e.g., U1, R1)"),
      pinName: z.string().describe("Pin name/number to connect"),
      netName: z.string().describe("Name of the net to connect to")
    },
    async (args: { schematicPath: string; componentRef: string; pinName: string; netName: string }) => {
      const result = await callKicadScript("connect_to_net", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Successfully connected ${args.componentRef}/${args.pinName} to net '${args.netName}'`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to connect to net: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Get net connections
  server.tool(
    "get_net_connections",
    "Get all connections for a named net",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Name of the net to query")
    },
    async (args: { schematicPath: string; netName: string }) => {
      const result = await callKicadScript("get_net_connections", args);
      if (result.success && result.connections) {
        const connectionList = result.connections.map((conn: any) =>
          `  - ${conn.component}/${conn.pin}`
        ).join('\n');
        return {
          content: [{
            type: "text",
            text: `Net '${args.netName}' connections:\n${connectionList}`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to get net connections: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Generate netlist
  server.tool(
    "auto_layout_schematic",
    "Auto-layout schematic symbols to reduce overlaps and improve alignment",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      grid: z.number().optional().describe("Layout grid in mm (default 2.54)"),
      xOrigin: z.number().optional().describe("Layout origin X in mm"),
      yOrigin: z.number().optional().describe("Layout origin Y in mm"),
      rowSpacing: z.number().optional().describe("Row spacing in mm"),
      columnSpacing: z.number().optional().describe("Column spacing in mm"),
      preserveConnectivity: z.boolean().optional().describe("Preserve existing net memberships while laying out"),
      allowUnsafeLayout: z.boolean().optional().describe("Allow moving symbols without connectivity preservation")
    },
    async (args: {
      schematicPath: string;
      grid?: number;
      xOrigin?: number;
      yOrigin?: number;
      rowSpacing?: number;
      columnSpacing?: number;
      preserveConnectivity?: boolean;
      allowUnsafeLayout?: boolean;
    }) => {
      const result = await callKicadScript("auto_layout_schematic", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Auto-layout complete. Moved ${result.movedCount ?? 0} components.`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Auto-layout failed: ${result.message || JSON.stringify(result)}`
        }]
      };
    }
  );

  server.tool(
    "validate_schematic",
    "Validate schematic quality and basic circuit integrity checks",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      overlapDistanceMM: z.number().optional().describe("Distance threshold for overlap warnings")
    },
    async (args: { schematicPath: string; overlapDistanceMM?: number }) => {
      const result = await callKicadScript("validate_schematic", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  server.tool(
    "export_schematic_pdf",
    "Export schematic file to PDF",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      outputPath: z.string().describe("Output PDF file path")
    },
    async (args: { schematicPath: string; outputPath: string }) => {
      const result = await callKicadScript("export_schematic_pdf", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Schematic PDF exported to ${args.outputPath}`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to export schematic PDF: ${result.message || JSON.stringify(result)}`
        }]
      };
    }
  );

  server.tool(
    "generate_netlist",
    "Generate a netlist from the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      includeTemplates: z.boolean().optional().describe("Include internal template symbols in output")
    },
    async (args: { schematicPath: string; includeTemplates?: boolean }) => {
      const result = await callKicadScript("generate_netlist", args);
      if (result.success && result.netlist) {
        const netlist = result.netlist;
        const output = [
          `=== Netlist for ${args.schematicPath} ===`,
          `\nComponents (${netlist.components.length}):`,
          ...netlist.components.map((comp: any) =>
            `  ${comp.reference}: ${comp.value} (${comp.footprint || 'No footprint'})`
          ),
          `\nNets (${netlist.nets.length}):`,
          ...netlist.nets.map((net: any) => {
            const connections = net.connections.map((conn: any) =>
              `${conn.component}/${conn.pin}`
            ).join(', ');
            return `  ${net.name}: ${connections}`;
          })
        ].join('\n');

        return {
          content: [{
            type: "text",
            text: output
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to generate netlist: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );
}
