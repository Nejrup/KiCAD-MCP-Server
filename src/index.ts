/**
 * KiCAD Model Context Protocol Server
 * Main entry point
 */

import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { KiCADMcpServer } from './server.js';
import { loadConfig, type Config } from './config.js';
import { logger } from './logger.js';

// Get the current directory
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function applyConfigToEnvironment(config: Config): void {
  if (config.pythonPath && !process.env.KICAD_PYTHON) {
    process.env.KICAD_PYTHON = config.pythonPath;
    logger.info('Loaded KICAD_PYTHON from config file');
  }

  const credentials = config.jlcpcb;
  if (!credentials) {
    return;
  }

  let applied = 0;

  if (credentials.appId && !process.env.JLCPCB_APP_ID) {
    process.env.JLCPCB_APP_ID = credentials.appId;
    applied += 1;
  }

  if (credentials.apiKey && !process.env.JLCPCB_API_KEY) {
    process.env.JLCPCB_API_KEY = credentials.apiKey;
    applied += 1;
  }

  if (credentials.apiSecret && !process.env.JLCPCB_API_SECRET) {
    process.env.JLCPCB_API_SECRET = credentials.apiSecret;
    applied += 1;
  }

  if (applied > 0) {
    logger.info(`Loaded ${applied} JLCPCB credential values from config file`);
  }
}

/**
 * Main function to start the KiCAD MCP server
 */
async function main() {
  try {
    // Parse command line arguments
    const args = process.argv.slice(2);
    const options = parseCommandLineArgs(args);
    
    // Load configuration
    const config = await loadConfig(options.configPath);
    applyConfigToEnvironment(config);
    
    // Path to the Python script that interfaces with KiCAD
    const kicadScriptPath = join(dirname(__dirname), 'python', 'kicad_interface.py');
    
    // Create the server
    const server = new KiCADMcpServer(
      kicadScriptPath,
      config.logLevel
    );
    
    // Start the server
    await server.start();
    
    // Setup graceful shutdown
    setupGracefulShutdown(server);
    
    logger.info('KiCAD MCP server started with STDIO transport');
    
  } catch (error) {
    logger.error(`Failed to start KiCAD MCP server: ${error}`);
    process.exit(1);
  }
}

/**
 * Parse command line arguments
 */
function parseCommandLineArgs(args: string[]) {
  let configPath = undefined;
  
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--config' && i + 1 < args.length) {
      configPath = args[i + 1];
      i++;
    }
  }
  
  return { configPath };
}

/**
 * Setup graceful shutdown handlers
 */
function setupGracefulShutdown(server: KiCADMcpServer) {
  process.once('SIGINT', async () => {
    logger.info('Received SIGINT signal. Shutting down...');
    await shutdownServer(server, 0);
  });

  process.once('SIGTERM', async () => {
    logger.info('Received SIGTERM signal. Shutting down...');
    await shutdownServer(server, 0);
  });

  process.on('uncaughtException', async (error) => {
    logger.error(`Uncaught exception: ${error}`);
    await shutdownServer(server, 1);
  });

  process.on('unhandledRejection', async (reason) => {
    logger.error(`Unhandled promise rejection: ${reason}`);
    await shutdownServer(server, 1);
  });
}

/**
 * Shut down the server and exit
 */
let shutdownInProgress = false;

async function shutdownServer(server: KiCADMcpServer, exitCode: number) {
  if (shutdownInProgress) {
    return;
  }
  shutdownInProgress = true;

  try {
    logger.info('Shutting down KiCAD MCP server...');
    await server.stop();
    logger.info('Server shutdown complete. Exiting...');
    process.exit(exitCode);
  } catch (error) {
    logger.error(`Error during shutdown: ${error}`);
    process.exit(1);
  }
}

// Run the main function - always run when imported as module entry point
// The import.meta.url check was failing on Windows due to path separators
main().catch((error) => {
  console.error(`Unhandled error in main: ${error}`);
  process.exit(1);
});

// For testing and programmatic usage
export { KiCADMcpServer };
