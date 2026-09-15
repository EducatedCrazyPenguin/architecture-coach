import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = path.resolve(process.argv[2]);
const relativeFiles = process.argv.slice(3).map(value => value.replaceAll("\\", "/"));
const absoluteFiles = relativeFiles.map(value => path.resolve(root, value));
const allowed = new Set();

function insideRoot(candidate) {
  const relative = path.relative(root, path.resolve(candidate));
  return relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function addTree(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) addTree(candidate);
    else allowed.add(path.resolve(candidate));
  }
}
addTree(root);

const host = {
  fileExists: candidate => insideRoot(candidate) && allowed.has(path.resolve(candidate)),
  readFile: candidate => host.fileExists(candidate) ? fs.readFileSync(candidate, "utf8") : undefined,
  directoryExists: candidate => insideRoot(candidate) && fs.existsSync(candidate) && fs.statSync(candidate).isDirectory(),
  realpath: candidate => path.resolve(candidate),
  getCurrentDirectory: () => root,
  getDirectories: candidate => host.directoryExists(candidate)
    ? fs.readdirSync(candidate, { withFileTypes: true }).filter(item => item.isDirectory()).map(item => item.name)
    : [],
};

let options = {
  allowJs: true,
  checkJs: false,
  moduleResolution: ts.ModuleResolutionKind.NodeNext,
  module: ts.ModuleKind.NodeNext,
  resolveJsonModule: true,
};
for (const configName of ["tsconfig.json", "jsconfig.json"]) {
  const configPath = path.join(root, configName);
  if (host.fileExists(configPath)) {
    const loaded = ts.readConfigFile(configPath, host.readFile);
    if (!loaded.error) {
      const parsed = ts.parseJsonConfigFileContent(loaded.config, {
        useCaseSensitiveFileNames: true,
        readDirectory: () => relativeFiles.map(value => path.resolve(root, value)),
        fileExists: host.fileExists,
        readFile: host.readFile,
      }, root);
      options = { ...options, ...parsed.options };
    }
    break;
  }
}

const result = [];
for (let index = 0; index < absoluteFiles.length; index += 1) {
  const file = absoluteFiles[index];
  const relativeFile = relativeFiles[index];
  const text = fs.readFileSync(file, "utf8");
  const extension = path.extname(file).toLowerCase();
  const kind = extension === ".tsx" ? ts.ScriptKind.TSX
    : extension === ".jsx" ? ts.ScriptKind.JSX
    : extension === ".js" || extension === ".mjs" || extension === ".cjs" ? ts.ScriptKind.JS
    : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const imports = [];
  const definitions = [];

  function recordImport(specifier, node, importKind) {
    const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    if (specifier === null) {
      imports.push({ specifier: null, line, kind: importKind, resolved: null });
      return;
    }
    const resolution = ts.resolveModuleName(specifier, file, options, host).resolvedModule;
    let resolved = null;
    if (resolution && host.fileExists(resolution.resolvedFileName)) {
      resolved = path.relative(root, resolution.resolvedFileName).replaceAll("\\", "/");
    }
    imports.push({ specifier, line, kind: importKind, resolved });
  }

  function visit(node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      recordImport(node.moduleSpecifier.text, node, "import");
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      recordImport(node.moduleSpecifier.text, node, "re-export");
    } else if (ts.isCallExpression(node)) {
      const isRequire = ts.isIdentifier(node.expression) && node.expression.text === "require";
      const isDynamicImport = node.expression.kind === ts.SyntaxKind.ImportKeyword;
      if (isRequire || isDynamicImport) {
        const argument = node.arguments[0];
        recordImport(argument && ts.isStringLiteralLike(argument) ? argument.text : null, node, isRequire ? "require" : "dynamic-import");
      }
    }
    if ((ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)) && node.name) {
      definitions.push({
        name: node.name.text,
        kind: ts.isClassDeclaration(node) ? "class" : "function",
        line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  result.push({
    file: relativeFile,
    imports,
    definitions,
    diagnostics: source.parseDiagnostics.map(diagnostic => {
      const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n");
      if (diagnostic.start === undefined) return message;
      return `line ${source.getLineAndCharacterOfPosition(diagnostic.start).line + 1}: ${message}`;
    }),
  });
}
process.stdout.write(JSON.stringify(result));
