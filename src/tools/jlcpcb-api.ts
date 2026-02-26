/**
 * JLCPCB API tools for KiCAD MCP server
 * Provides access to JLCPCB's complete parts catalog via their API
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerJLCPCBApiTools(server: McpServer, callKicadScript: Function) {
  const fmtRange = (r: any) => `${r?.min?.toLocaleString?.() ?? r?.min} - ${r?.max?.toLocaleString?.() ?? r?.max}`;
  const fmtTimeRange = (t: any) => {
    const min = t?.min;
    const max = t?.max;
    if (typeof min === 'number' && typeof max === 'number') {
      return `${min} - ${max} min`;
    }
    return 'unknown';
  };

  const elicitChoice = async (message: string, enumValues: string[], enumNames: string[]) => {
    return await server.server.elicitInput({
      message,
      requestedSchema: {
        type: 'object',
        properties: {
          choice: {
            type: 'string',
            enum: enumValues,
            enumNames,
            title: 'Choice',
            description: 'Select one option',
          },
        },
        required: ['choice'],
      },
    });
  };

  // Download JLCPCB parts database
  server.tool(
    "download_jlcpcb_database",
    `Download the complete JLCPCB parts catalog to local database.

This is a one-time setup that downloads JLCPCB parts into a local SQLite database.
Use source='official' for signed full-catalog download (requires JLCPCB_APP_ID, JLCPCB_API_KEY, JLCPCB_API_SECRET).
Use source='public' for high-coverage public snapshot hosted by yaqwsx/jlcparts artifacts.

The download takes 5-10 minutes and creates a local SQLite database
for fast offline searching.`,
    {
      force: z.boolean().optional().default(false)
        .describe("Force re-download even if database exists"),
      source: z.enum(["auto", "official", "public"]).optional().default("auto")
        .describe("Download source: auto (show choices), signed official API, or public snapshot (hosted by yaqwsx)"),
      confirm: z.boolean().optional().default(false)
        .describe("Required for public snapshot source after estimate is shown")
    },
    async (args: { force?: boolean; source?: "auto" | "official" | "public"; confirm?: boolean }) => {
      let startResult = await callKicadScript("download_jlcpcb_database", {
        ...args,
        background: true,
      });

      if (!startResult.success) {
        if (startResult.requiresReplaceConfirmation && startResult.stats) {
          const stats = startResult.stats;
          const official = startResult.options?.official;
          const publicSnapshot = startResult.options?.public;

          const sourceInfo = official && publicSnapshot
            ? `\n\nAvailable sources after replacement:\n` +
              `1) official - available=${official.available ? 'yes' : 'no'}, est parts=${fmtRange(official.estimatedPartCount)}, est in-stock~${(official.estimatedInStockParts ?? '?').toLocaleString?.() ?? official.estimatedInStockParts ?? '?'}, est basic~${(official.estimatedBasicParts ?? '?').toLocaleString?.() ?? official.estimatedBasicParts ?? '?'}, est download=${official.estimatedDownloadSizeMB ?? '?'} MB, est DB=${official.estimatedDatabaseSizeMB} MB, est time=${fmtTimeRange(official.estimatedDownloadTimeMinutes)}\n` +
              `   Note: ${official.recommendedUseCase || 'Signed official API dataset.'}\n` +
              `2) public (hosted by yaqwsx) - est parts=${fmtRange(publicSnapshot.estimatedPartCount)}, est in-stock~${(publicSnapshot.estimatedInStockParts ?? '?').toLocaleString?.() ?? publicSnapshot.estimatedInStockParts ?? '?'}, est basic~${(publicSnapshot.estimatedBasicParts ?? '?').toLocaleString?.() ?? publicSnapshot.estimatedBasicParts ?? '?'}, est changed download=${publicSnapshot.estimatedUpdateDownloadMB ?? publicSnapshot.downloadSizeMB} MB, est DB=${publicSnapshot.estimatedDatabaseSizeMB} MB, est time=${fmtTimeRange(publicSnapshot.estimatedUpdateTimeMinutes || publicSnapshot.estimatedDownloadTimeMinutes)}\n` +
              `   Archive reuse: changed=${publicSnapshot.changedArchiveParts ?? '?'} reused=${publicSnapshot.reusedArchiveParts ?? '?'}\n` +
              `   Note: ${publicSnapshot.recommendedUseCase || 'Large public snapshot.'}`
            : '';

          try {
            const response = await elicitChoice(
              `Existing JLC database found:\n` +
                `Total parts: ${stats.total_parts}\n` +
                `Basic: ${stats.basic_parts}, Extended: ${stats.extended_parts}\n` +
                `In stock: ${stats.in_stock}\n` +
                `Path: ${stats.db_path}` +
                sourceInfo,
              ['keep_existing', 'replace_official', 'replace_public'],
              ['Keep existing database', 'Replace with Official API', 'Replace with Public Snapshot'],
            );

            const choice = response?.content?.choice;
            if (response?.action !== 'accept' || !choice || choice === 'keep_existing') {
              return {
                content: [{
                  type: 'text',
                  text: 'Keeping existing JLC database. No download started.',
                }],
              };
            }

            const nextArgs = choice === 'replace_official'
              ? { force: true, source: 'official' }
              : { force: true, source: 'public', confirm: true };

            startResult = await callKicadScript('download_jlcpcb_database', {
              ...nextArgs,
              background: true,
            });
            if (!startResult.success) {
              return {
                content: [{
                  type: 'text',
                  text: `✗ Failed to start JLCPCB download: ${startResult.message || 'Unknown error'}`,
                }],
              };
            }
          } catch {
            return {
              content: [{
                type: 'text',
                text: `⚠ Existing JLC database found:\n` +
                  `Total parts: ${stats.total_parts}\n` +
                  `Basic: ${stats.basic_parts}, Extended: ${stats.extended_parts}\n` +
                  `In stock: ${stats.in_stock}\n` +
                  `Path: ${stats.db_path}\n\n` +
                  `Choose:\n` +
                  `- Keep existing DB: do nothing\n` +
                  `- Replace DB: re-run with force=true source=official OR force=true source=public` +
                  sourceInfo,
              }],
            };
          }
        }

        if (startResult.requiresDownloadConfirmation && startResult.estimate) {
          const est = startResult.estimate;
          const partRange = est.estimatedPartCount;
          try {
            const response = await elicitChoice(
                `Public snapshot download confirmation required\n` +
                `Estimated parts: ${partRange.min.toLocaleString()} - ${partRange.max.toLocaleString()}\n` +
                `Estimated in-stock parts: ~${(est.estimatedInStockParts ?? '?').toLocaleString?.() ?? est.estimatedInStockParts ?? '?'}\n` +
                `Estimated basic parts: ~${(est.estimatedBasicParts ?? '?').toLocaleString?.() ?? est.estimatedBasicParts ?? '?'}\n` +
                `Estimated changed download: ${est.estimatedUpdateDownloadMB ?? est.downloadSizeMB} MB\n` +
                `Estimated local DB size: ~${est.estimatedDatabaseSizeMB} MB\n` +
                `Estimated download time: ${fmtTimeRange(est.estimatedUpdateTimeMinutes || est.estimatedDownloadTimeMinutes)}\n` +
                `Archive reuse: changed=${est.changedArchiveParts ?? '?'} reused=${est.reusedArchiveParts ?? '?'}\n` +
                `Snapshot time: ${est.createdAt || 'unknown'}\n` +
                `Use case: ${est.recommendedUseCase || 'Broad public catalog snapshot.'}`,
              ['proceed', 'cancel'],
              ['Proceed with public snapshot', 'Cancel'],
            );

            const choice = response?.content?.choice;
            if (response?.action !== 'accept' || choice !== 'proceed') {
              return { content: [{ type: 'text', text: 'Public snapshot download cancelled.' }] };
            }

            startResult = await callKicadScript('download_jlcpcb_database', {
              force: Boolean(args.force),
              source: 'public',
              confirm: true,
              background: true,
            });
            if (!startResult.success) {
              return {
                content: [{
                  type: 'text',
                  text: `✗ Failed to start JLCPCB download: ${startResult.message || 'Unknown error'}`,
                }],
              };
            }
          } catch {
            return {
              content: [{
                type: 'text',
                text: `⚠ public snapshot download confirmation required\n` +
                  `Estimated parts: ${partRange.min.toLocaleString()} - ${partRange.max.toLocaleString()}\n` +
                  `Estimated in-stock parts: ~${(est.estimatedInStockParts ?? '?').toLocaleString?.() ?? est.estimatedInStockParts ?? '?'}\n` +
                  `Estimated basic parts: ~${(est.estimatedBasicParts ?? '?').toLocaleString?.() ?? est.estimatedBasicParts ?? '?'}\n` +
                  `Estimated changed download: ${est.estimatedUpdateDownloadMB ?? est.downloadSizeMB} MB\n` +
                  `Estimated local DB size: ~${est.estimatedDatabaseSizeMB} MB\n` +
                  `Estimated download time: ${fmtTimeRange(est.estimatedUpdateTimeMinutes || est.estimatedDownloadTimeMinutes)}\n` +
                  `Archive reuse: changed=${est.changedArchiveParts ?? '?'} reused=${est.reusedArchiveParts ?? '?'}\n` +
                  `Snapshot time: ${est.createdAt || 'unknown'}\n` +
                  `Use case: ${est.recommendedUseCase || 'Broad public catalog snapshot.'}\n` +
                  `Re-run with confirm=true to proceed.`,
              }],
            };
          }
        }

        if (startResult.requiresSourceSelection && startResult.options) {
          const official = startResult.options.official;
          const publicSnapshot = startResult.options.public;
          try {
            const response = await elicitChoice(
              `Select JLC download source:\n` +
                `1) official - available=${official.available ? 'yes' : 'no'}, est parts=${fmtRange(official.estimatedPartCount)}, est in-stock~${(official.estimatedInStockParts ?? '?').toLocaleString?.() ?? official.estimatedInStockParts ?? '?'}, est basic~${(official.estimatedBasicParts ?? '?').toLocaleString?.() ?? official.estimatedBasicParts ?? '?'}, est download=${official.estimatedDownloadSizeMB ?? '?'} MB, est DB=${official.estimatedDatabaseSizeMB} MB, est time=${fmtTimeRange(official.estimatedDownloadTimeMinutes)}\n` +
                `   Note: ${official.recommendedUseCase || 'Signed official API dataset.'}\n` +
                `2) public (hosted by yaqwsx) - est parts=${fmtRange(publicSnapshot.estimatedPartCount)}, est in-stock~${(publicSnapshot.estimatedInStockParts ?? '?').toLocaleString?.() ?? publicSnapshot.estimatedInStockParts ?? '?'}, est basic~${(publicSnapshot.estimatedBasicParts ?? '?').toLocaleString?.() ?? publicSnapshot.estimatedBasicParts ?? '?'}, est changed download=${publicSnapshot.estimatedUpdateDownloadMB ?? publicSnapshot.downloadSizeMB} MB, est DB=${publicSnapshot.estimatedDatabaseSizeMB} MB, est time=${fmtTimeRange(publicSnapshot.estimatedUpdateTimeMinutes || publicSnapshot.estimatedDownloadTimeMinutes)}\n` +
                `   Archive reuse: changed=${publicSnapshot.changedArchiveParts ?? '?'} reused=${publicSnapshot.reusedArchiveParts ?? '?'}\n` +
                `   Note: ${publicSnapshot.recommendedUseCase || 'Large public snapshot.'}`,
              ['official', 'public'],
              ['Official API', 'Public snapshot (hosted by yaqwsx)'],
            );

            const choice = response?.content?.choice;
            if (response?.action !== 'accept' || !choice) {
              return { content: [{ type: 'text', text: 'Download cancelled.' }] };
            }

            const nextArgs = choice === 'official'
              ? { force: Boolean(args.force), source: 'official' }
              : { force: Boolean(args.force), source: 'public', confirm: true };

            startResult = await callKicadScript('download_jlcpcb_database', {
              ...nextArgs,
              background: true,
            });
            if (!startResult.success) {
              return {
                content: [{
                  type: 'text',
                  text: `✗ Failed to start JLCPCB download: ${startResult.message || 'Unknown error'}`,
                }],
              };
            }
          } catch {
            return {
              content: [{
                type: "text",
                text: `Select JLC download source:\n` +
                  `1) official - available=${official.available ? 'yes' : 'no'}, est parts=${fmtRange(official.estimatedPartCount)}, est in-stock~${(official.estimatedInStockParts ?? '?').toLocaleString?.() ?? official.estimatedInStockParts ?? '?'}, est basic~${(official.estimatedBasicParts ?? '?').toLocaleString?.() ?? official.estimatedBasicParts ?? '?'}, est download=${official.estimatedDownloadSizeMB ?? '?'} MB, est DB=${official.estimatedDatabaseSizeMB} MB, est time=${fmtTimeRange(official.estimatedDownloadTimeMinutes)}\n` +
                  `   Note: ${official.recommendedUseCase || 'Signed official API dataset.'}\n` +
                  `2) public (hosted by yaqwsx) - est parts=${fmtRange(publicSnapshot.estimatedPartCount)}, est in-stock~${(publicSnapshot.estimatedInStockParts ?? '?').toLocaleString?.() ?? publicSnapshot.estimatedInStockParts ?? '?'}, est basic~${(publicSnapshot.estimatedBasicParts ?? '?').toLocaleString?.() ?? publicSnapshot.estimatedBasicParts ?? '?'}, est changed download=${publicSnapshot.estimatedUpdateDownloadMB ?? publicSnapshot.downloadSizeMB} MB, est DB=${publicSnapshot.estimatedDatabaseSizeMB} MB, est time=${fmtTimeRange(publicSnapshot.estimatedUpdateTimeMinutes || publicSnapshot.estimatedDownloadTimeMinutes)}\n` +
                  `   Archive reuse: changed=${publicSnapshot.changedArchiveParts ?? '?'} reused=${publicSnapshot.reusedArchiveParts ?? '?'}\n` +
                  `   Note: ${publicSnapshot.recommendedUseCase || 'Large public snapshot.'}\n` +
                  `Re-run with source=official or source=public.`,
              }],
            };
          }
        }

        return {
          content: [{
            type: "text",
            text: `✗ Failed to start JLCPCB download: ${startResult.message || 'Unknown error'}\n\n` +
              `For official source, provide credentials via ~/.kicad-mcp/config.json (jlcpcb.appId/apiKey/apiSecret) or env vars JLCPCB_APP_ID/JLCPCB_API_KEY/JLCPCB_API_SECRET.`
          }]
        };
      }

      return {
        content: [{
          type: "text",
          text: `✓ JLCPCB database download started in background (source=${startResult.source || args.source || 'auto'}). ` +
            `Run get_jlcpcb_download_status for progress and final result.`
        }]
      };
      }
  );

  server.tool(
    "get_jlcpcb_download_status",
    "Get current progress for an in-flight JLCPCB database download/import operation",
    {},
    async () => {
      const result = await callKicadScript("get_jlcpcb_download_status", {});
      if (!result.success) {
        return {
          content: [{
            type: "text",
            text: `Failed to get download status: ${result.message || 'Unknown error'}`
          }]
        };
      }

      const latestStatus = result.status;

      if (latestStatus?.stage === 'completed') {
        const success = latestStatus.lastSuccess || {};
        const updatedArchiveParts = latestStatus.updatedArchiveParts ?? success.updatedArchiveParts;
        const reusedArchiveParts = latestStatus.reusedArchiveParts ?? success.reusedArchiveParts;
        const downloadedNow =
          latestStatus.downloadedSizeMB ??
          latestStatus.totalSizeMB ??
          latestStatus.estimate?.downloadSizeMB ??
          latestStatus.estimate?.estimatedUpdateDownloadMB ??
          '?';
        const downloadedTotal =
          latestStatus.totalSizeMB ??
          latestStatus.estimate?.downloadSizeMB ??
          latestStatus.estimate?.estimatedUpdateDownloadMB ??
          '?';
        const importedNow = success.totalParts ?? latestStatus.totalParts ?? latestStatus.importedParts ?? '?';
        const importedTotal = success.totalParts ?? latestStatus.totalParts ?? '?';
        const elapsed = typeof latestStatus.elapsedSeconds === 'number' ? `${latestStatus.elapsedSeconds.toFixed(1)}s` : 'n/a';
        const archiveUpdateInfo =
          typeof updatedArchiveParts === 'number' || typeof reusedArchiveParts === 'number'
            ? ` | archive_changed=${updatedArchiveParts ?? '?'} | archive_reused=${reusedArchiveParts ?? '?'}`
            : '';
        return {
          content: [{
            type: "text",
            text: `completed | source=${latestStatus.source || success.source || 'unknown'} | downloaded=${downloadedNow}/${downloadedTotal} MB | imported=${importedNow}/${importedTotal} parts${archiveUpdateInfo} | evt=${latestStatus.message || 'done'} | elapsed=${elapsed}`
          }]
        };
      }

      if (latestStatus?.stage === 'failed') {
        return {
          content: [{
            type: "text",
            text: `✗ JLCPCB database download failed: ${latestStatus.error || latestStatus.message || 'Unknown error'}`
          }]
        };
      }

      if (latestStatus?.stage === 'awaiting_source_selection') {
        return {
          content: [{
            type: "text",
            text: "Download is awaiting source selection. Re-run download_jlcpcb_database with source=official or source=public."
          }]
        };
      }

      if (latestStatus) {
        const stage = latestStatus.stage || 'unknown';
        const elapsed = typeof latestStatus.elapsedSeconds === 'number' ? `${latestStatus.elapsedSeconds.toFixed(1)}s` : 'n/a';
        const downloadedMb = latestStatus.downloadedSizeMB;
        const downloaded = typeof downloadedMb === 'number'
          ? downloadedMb
          : Number(latestStatus.downloadedParts || 0);
        const fullDownloadMb =
          latestStatus.totalSizeMB ??
          latestStatus.estimate?.downloadSizeMB ??
          latestStatus.estimate?.estimatedUpdateDownloadMB ??
          '?';
        const imported = Number(latestStatus.importedParts || 0).toLocaleString();
        const importedTotal =
          latestStatus.totalParts ??
          latestStatus.estimate?.expectedTotalParts ??
          latestStatus.lastSuccess?.totalParts ??
          latestStatus.estimate?.estimatedPartCount?.max ??
          '?';
        const evtDetails = latestStatus.message || 'none';
        const archiveUpdateInfo =
          (typeof latestStatus.updatedArchiveParts === 'number' || typeof latestStatus.reusedArchiveParts === 'number')
            ? ` | archive_changed=${latestStatus.updatedArchiveParts ?? '?'} | archive_reused=${latestStatus.reusedArchiveParts ?? '?'}`
            : '';

        return {
          content: [{
            type: "text",
            text: `${stage} | source=${latestStatus.source || 'n/a'} | downloaded=${Number(downloaded).toLocaleString()}/${fullDownloadMb} MB | imported=${imported}/${importedTotal} parts${archiveUpdateInfo} | evt=${evtDetails} | elapsed=${elapsed}`
          }]
        };
      }

      return {
        content: [{
          type: "text",
          text: "No download status available"
        }]
      };
    }
  );

  // Search JLCPCB parts
  server.tool(
    "search_jlcpcb_parts",
    `Search JLCPCB parts catalog by specifications.

Searches the local JLCPCB database (must be downloaded first with download_jlcpcb_database).
Provides real pricing, stock info, and library type (Basic parts = free assembly).

Use this to find components with exact specifications and cost optimization.`,
    {
      query: z.string().optional()
        .describe("Free-text search (e.g., '10k resistor 0603', 'ESP32', 'STM32F103')"),
      category: z.string().optional()
        .describe("Filter by category (e.g., 'Resistors', 'Capacitors', 'Microcontrollers')"),
      package: z.string().optional()
        .describe("Filter by package type (e.g., '0603', 'SOT-23', 'QFN-32')"),
      library_type: z.enum(["Basic", "Extended", "Preferred", "All"]).optional().default("All")
        .describe("Filter by library type. Default All returns Basic-first ordering (Basic = free assembly at JLCPCB)."),
      manufacturer: z.string().optional()
        .describe("Filter by manufacturer name"),
      in_stock: z.boolean().optional().default(true)
        .describe("Only show parts with available stock"),
      limit: z.number().optional().default(20)
        .describe("Maximum number of results to return")
    },
    async (args: any) => {
      const result = await callKicadScript("search_jlcpcb_parts", args);
      if (result.success && result.parts) {
        if (result.parts.length === 0) {
          return {
            content: [{
              type: "text",
              text: `No JLCPCB parts found matching your criteria.\n\n` +
                    `Try broadening your search or check if the database is populated.`
            }]
          };
        }

        const partsList = result.parts.map((p: any) => {
          const priceInfo = p.price_breaks && p.price_breaks.length > 0
            ? ` - $${p.price_breaks[0].price}/ea`
            : '';
          const stockInfo = p.stock > 0 ? ` (${p.stock} in stock)` : ' (out of stock)';
          return `${p.lcsc}: ${p.mfr_part} - ${p.description} [${p.library_type}]${priceInfo}${stockInfo}`;
        }).join('\n');

        return {
          content: [{
            type: "text",
            text: `Found ${result.count} JLCPCB parts${result.basicFirst ? ' (Basic-first order)' : ''}:\n\n${partsList}\n\n` +
                  `💡 Basic parts have free assembly. Extended parts charge $3 setup fee per unique part.`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to search JLCPCB parts: ${result.message || 'Unknown error'}\n\n` +
                `Make sure you've downloaded the database first using download_jlcpcb_database.`
        }]
      };
    }
  );

  // Get JLCPCB part details
  server.tool(
    "get_jlcpcb_part",
    "Get detailed information about a specific JLCPCB part by LCSC number",
    {
      lcsc_number: z.string()
        .describe("LCSC part number (e.g., 'C25804', 'C2286')")
    },
    async (args: { lcsc_number: string }) => {
      const result = await callKicadScript("get_jlcpcb_part", args);
      if (result.success && result.part) {
        const p = result.part;
        const priceTable = p.price_breaks && p.price_breaks.length > 0
          ? '\n\nPrice Breaks:\n' + p.price_breaks.map((pb: any) =>
              `  ${pb.qty}+: $${pb.price}/ea`
            ).join('\n')
          : '';

        const footprints = result.footprints && result.footprints.length > 0
          ? '\n\nSuggested KiCAD Footprints:\n' + result.footprints.map((f: string) =>
              `  - ${f}`
            ).join('\n')
          : '';

        return {
          content: [{
            type: "text",
            text: `LCSC: ${p.lcsc}\n` +
                  `MFR Part: ${p.mfr_part}\n` +
                  `Manufacturer: ${p.manufacturer}\n` +
                  `Category: ${p.category} / ${p.subcategory}\n` +
                  `Package: ${p.package}\n` +
                  `Description: ${p.description}\n` +
                  `Library Type: ${p.library_type} ${p.library_type === 'Basic' ? '(Free assembly!)' : ''}\n` +
                  `Stock: ${p.stock}\n` +
                  (p.datasheet ? `Datasheet: ${p.datasheet}\n` : '') +
                  priceTable +
                  footprints
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Part not found: ${args.lcsc_number}\n\n` +
                `Make sure you've downloaded the JLCPCB database first.`
        }]
      };
    }
  );

  // Get JLCPCB database statistics
  server.tool(
    "get_jlcpcb_database_stats",
    "Get statistics about the local JLCPCB parts database",
    {},
    async () => {
      const result = await callKicadScript("get_jlcpcb_database_stats", {});
      if (result.success) {
        const stats = result.stats;
        return {
          content: [{
            type: "text",
            text: `JLCPCB Database Statistics:\n\n` +
                  `Total parts: ${stats.total_parts.toLocaleString()}\n` +
                  `Basic parts: ${stats.basic_parts.toLocaleString()} (free assembly)\n` +
                  `Extended parts: ${stats.extended_parts.toLocaleString()} ($3 setup fee each)\n` +
                  `In stock: ${stats.in_stock.toLocaleString()}\n` +
                  `Database path: ${stats.db_path}`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `JLCPCB database not found or empty.\n\n` +
                `Run download_jlcpcb_database first to populate the database.`
        }]
      };
    }
  );

  // Suggest alternative parts
  server.tool(
    "suggest_jlcpcb_alternatives",
    `Suggest alternative JLCPCB parts for a given component.

Finds similar parts that may be cheaper, have more stock, or are Basic library type.
Useful for cost optimization and finding alternatives when parts are out of stock.`,
    {
      lcsc_number: z.string()
        .describe("Reference LCSC part number to find alternatives for"),
      limit: z.number().optional().default(5)
        .describe("Maximum number of alternatives to return")
    },
    async (args: { lcsc_number: string; limit?: number }) => {
      const result = await callKicadScript("suggest_jlcpcb_alternatives", args);
      if (result.success && result.alternatives) {
        if (result.alternatives.length === 0) {
          return {
            content: [{
              type: "text",
              text: `No alternatives found for ${args.lcsc_number}`
            }]
          };
        }

        const altsList = result.alternatives.map((p: any, i: number) => {
          const priceInfo = p.price_breaks && p.price_breaks.length > 0
            ? ` - $${p.price_breaks[0].price}/ea`
            : '';
          const savings = result.reference_price && p.price_breaks && p.price_breaks.length > 0
            ? ` (${((1 - p.price_breaks[0].price / result.reference_price) * 100).toFixed(0)}% cheaper)`
            : '';
          return `${i + 1}. ${p.lcsc}: ${p.mfr_part} [${p.library_type}]${priceInfo}${savings}\n   ${p.description}\n   Stock: ${p.stock}`;
        }).join('\n\n');

        return {
          content: [{
            type: "text",
            text: `Alternative parts for ${args.lcsc_number}:\n\n${altsList}`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to find alternatives: ${result.message || 'Unknown error'}`
        }]
      };
    }
  );
}
