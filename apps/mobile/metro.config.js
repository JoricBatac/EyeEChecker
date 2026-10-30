// Let Metro resolve the shared TypeScript package outside this app folder (packages/shared_ts).
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
config.watchFolders = [path.resolve(__dirname, '../../packages/shared_ts')];
config.resolver.nodeModulesPaths = [path.resolve(__dirname, 'node_modules')];
config.resolver.unstable_enableSymlinks = true;

module.exports = config;
