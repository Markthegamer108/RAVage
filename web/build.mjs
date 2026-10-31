import { build } from 'esbuild';
import JavaScriptObfuscator from 'javascript-obfuscator';
import { readFile, writeFile } from 'node:fs/promises';

await build({
  entryPoints: ['src/converter.js'],
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2020',
  legalComments: 'none',
  outfile: 'build/app.js',
});

const raw = await readFile('build/app.js', 'utf8');
const result = JavaScriptObfuscator.obfuscate(raw, {
  compact: true,
  controlFlowFlattening: false,
  deadCodeInjection: false,
  debugProtection: false,
  disableConsoleOutput: false,
  identifierNamesGenerator: 'hexadecimal',
  numbersToExpressions: false,
  renameGlobals: false,
  selfDefending: false,
  simplify: false,
  splitStrings: true,
  splitStringsChunkLength: 8,
  stringArray: true,
  stringArrayCallsTransform: false,
  stringArrayEncoding: ['base64'],
  stringArrayIndexShift: true,
  stringArrayRotate: true,
  stringArrayShuffle: true,
  stringArrayThreshold: 0.75,
  transformObjectKeys: false,
  unicodeEscapeSequence: false,
});

await writeFile('../docs/app.js', result.getObfuscatedCode(), 'utf8');
console.log('docs/app.js', (await readFile('../docs/app.js', 'utf8')).length, 'chars');
