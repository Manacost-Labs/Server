// Use the actual compiler for alias/overload bindings, keeping runtime dispatch explicit.
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const raw = fs.readFileSync(0, 'utf8');
if (Buffer.byteLength(raw) > 50000) throw new Error('Compiler request budget exceeded');
const input = JSON.parse(raw);
const root = fs.realpathSync(input.root);
if (!Array.isArray(input.files) || input.files.length > 200) throw new Error('Select at most 200 files');
const selected = new Set(input.files.map(file => fs.realpathSync(path.join(root, file))));
if ([...selected].some(file => !file.startsWith(root + path.sep))) throw new Error('Source escapes project');
const libraryRoot = path.dirname(ts.getDefaultLibFilePath({}));
let bytes = 0;
const reads = new Map();
function read(file) {
  let real;
  try { real = fs.realpathSync(file); } catch { return undefined; }
  if (!real.startsWith(root + path.sep) && !real.startsWith(libraryRoot + path.sep)) return undefined;
  if (reads.has(real)) return reads.get(real);
  const size = fs.statSync(real).size;
  if (reads.size >= 400 || bytes + size > 16000000) throw new Error('Compiler dependency budget exceeded');
  const text = fs.readFileSync(real, 'utf8');
  bytes += size;
  reads.set(real, text);
  return text;
}
const configPath = path.join(root, input.config || 'tsconfig.json');
let options = {noEmit: true, allowJs: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.NodeNext,
  moduleResolution: ts.ModuleResolutionKind.NodeNext, jsx: ts.JsxEmit.Preserve, types: []};
if (fs.existsSync(configPath)) {
  const config = ts.readConfigFile(configPath, read);
  if (config.error) throw new Error('Invalid TypeScript configuration');
  // Override directory discovery: the compiler roots are always explicitly selected.
  const parsed = ts.parseJsonConfigFileContent(config.config,
    {...ts.sys, readFile: read, readDirectory: () => [...selected]}, path.dirname(configPath));
  if (parsed.errors.length) throw new Error('TypeScript configuration could not be resolved');
  options = {...options, ...parsed.options, noEmit: true, types: []};
}
const host = ts.createCompilerHost(options);
host.readFile = read;
host.getSourceFile = (file, languageVersion) => {
  const text = read(file);
  return text === undefined ? undefined : ts.createSourceFile(file, text, languageVersion, true);
};
const program = ts.createProgram({rootNames: [...selected], options, host});
const checker = program.getTypeChecker();
const relations = [];
const imports = [];
function name(node) {
  return node.name?.getText() || (ts.isVariableDeclaration(node.parent) ? node.parent.name.getText() : '<anonymous>');
}
function location(node) {
  const source = node.getSourceFile();
  const start = source.getLineAndCharacterOfPosition(node.getStart(source));
  const end = source.getLineAndCharacterOfPosition(node.getEnd());
  return {path: path.relative(root, source.fileName), name: name(node), start: start.line + 1,
    column: start.character + 1, end: end.line + 1};
}
for (const file of selected) {
  const source = program.getSourceFile(file);
  if (!source) continue;
  function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      imports.push({path: path.relative(root, file), text: node.getText(source).slice(0, 500)});
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      const declaration = checker.getResolvedSignature(node)?.getDeclaration();
      let caller = node.parent;
      while (caller && !ts.isFunctionLike(caller)) caller = caller.parent;
      const target = declaration ? location(declaration) : null;
      const included = declaration && selected.has(path.resolve(declaration.getSourceFile().fileName));
      relations.push({call: {...location(node), name: node.expression.getText(source).slice(0, 180)},
        caller: caller ? location(caller) : null, target: included ? target : null,
        evidence: included ? 'TypeScript compiler declaration binding' : 'unresolved or outside selected source',
        runtime_dispatch_verified: false});
      if (relations.length > 5000) throw new Error('Call budget exceeded; narrow selected files');
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
process.stdout.write(JSON.stringify({engine: `TypeScript ${ts.version}`, relations, imports,
  inspected_files: reads.size, inspected_bytes: bytes,
  notice: 'Compiler bindings resolve aliases and declarations; dynamic runtime dispatch is not proven.'}));
