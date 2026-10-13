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

const defaultOptions = {
  allowJs: true,
  checkJs: false,
  moduleResolution: ts.ModuleResolutionKind.NodeNext,
  module: ts.ModuleKind.NodeNext,
  resolveJsonModule: true,
};
const configurationIssues = new Map();
function optionsFor(file) {
 let directory = path.dirname(file);
 while (insideRoot(directory)) {
 for (const configName of ["tsconfig.json", "jsconfig.json"]) {
  const configPath = path.join(directory, configName);
  if (host.fileExists(configPath)) {
    const loaded = ts.readConfigFile(configPath, host.readFile);
    if (!loaded.error) {
      const parsed = ts.parseJsonConfigFileContent(loaded.config, {
        useCaseSensitiveFileNames: true,
        readDirectory: () => relativeFiles.map(value => path.resolve(root, value)),
        fileExists: host.fileExists,
        readFile: host.readFile,
      }, directory);
      configurationIssues.set(file, parsed.errors.map(d => ts.flattenDiagnosticMessageText(d.messageText, '\n')));
      return { ...defaultOptions, ...parsed.options };
    }
    configurationIssues.set(file, [ts.flattenDiagnosticMessageText(loaded.error.messageText, '\n')]);
    return defaultOptions;
  }
 }
 if(directory === root) break;
 directory = path.dirname(directory);
 }
 return defaultOptions;
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
  const options = optionsFor(file);
  const imports = [];
  const definitions = [];
  const functions = [];
  const bindings = {};
  const handlers = new Set();
  const literal = node => source.text.slice(node.getStart(source), node.end).slice(0, 160);
  const location = node => ({line:source.getLineAndCharacterOfPosition(node.getStart(source)).line+1, end_line:source.getLineAndCharacterOfPosition(node.end).line+1});
  for (const node of source.statements) {
    if(ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const target = ts.resolveModuleName(node.moduleSpecifier.text, file, options, host).resolvedModule;
      const relative = target && host.fileExists(target.resolvedFileName) ? path.relative(root,target.resolvedFileName).replaceAll('\\','/') : null;
      const names = node.importClause?.namedBindings;
      if(names && ts.isNamedImports(names)) for(const item of names.elements) bindings[item.name.text] = {path:relative,name:(item.propertyName || item.name).text};
      if(names && ts.isNamespaceImport(names)) bindings[names.name.text] = {path:relative,name:null};
    }
    const exported = !!node.modifiers?.some(m=>m.kind===ts.SyntaxKind.ExportKeyword);
    if(ts.isFunctionDeclaration(node) && node.name && node.body) functions.push({name:node.name.text, node, exported});
    if(ts.isVariableStatement(node)) for(const declaration of node.declarationList.declarations) {
      if(ts.isIdentifier(declaration.name) && declaration.initializer && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))) functions.push({name:declaration.name.text,node:declaration.initializer,exported});
    }
  }
  function declaredNames(name) {
    if(ts.isIdentifier(name)) return [name.text];
    if(ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) return name.elements.flatMap(item=>ts.isBindingElement(item)?declaredNames(item.name):[]);
    return [];
  }
  function hasLocalBinding(scope, name) {
    if(scope.parameters.some(parameter=>declaredNames(parameter.name).includes(name))) return true;
    let found=false;
    function visit(node) {
      if(node !== scope && ts.isFunctionLike(node)) {if(node.name?.text===name)found=true;return;}
      if(ts.isVariableDeclaration(node) && declaredNames(node.name).includes(name)) found=true;
      ts.forEachChild(node,visit);
    }
    visit(scope);return found;
  }
  function findHandlers(node) {
    if(ts.isJsxAttribute(node) && /^on[A-Z]/.test(node.name.text) && node.initializer && ts.isJsxExpression(node.initializer) && node.initializer.expression && ts.isIdentifier(node.initializer.expression)) {
      const name=node.initializer.expression.text;let shadowed=false;
      for(let parent=node.parent;parent;parent=parent.parent) if(ts.isFunctionLike(parent) && hasLocalBinding(parent,name))shadowed=true;
      if(!shadowed && functions.filter(fn=>fn.name===name).length===1)handlers.add(name);
    }
    ts.forEachChild(node,findHandlers);
  }
  findHandlers(source);
  const outlines = functions.slice(0,4).map(fn => {
    const steps = [{title:`Input boundary: ${fn.name}`,explanation:`Declared inputs: ${fn.node.parameters.map(p=>literal(p.name)).join(', ') || 'none'}. Actual caller values are unknown.`,...location(fn.node),inferred:false}];
    const shadowed = new Set(fn.node.parameters.flatMap(p=>declaredNames(p.name)));
    function collectBindings(node) {
      if(node !== fn.node && ts.isFunctionLike(node)) return;
      if(ts.isVariableDeclaration(node)) declaredNames(node.name).forEach(name=>shadowed.add(name));
      if(ts.isBinaryExpression(node) && node.operatorToken.kind===ts.SyntaxKind.EqualsToken && ts.isIdentifier(node.left)) shadowed.add(node.left.text);
      ts.forEachChild(node,collectBindings);
    }
    collectBindings(fn.node);
    function step(node,title,explanation,branch,extra={}) {if(steps.length<30)steps.push({title,explanation:branch ? `${branch}. ${explanation}`:explanation,branch,...location(node),inferred:true,...extra});}
    function read(node,branch='') {
      if(!node || steps.length>=30) return;
      if(ts.isFunctionLike(node) && node !== fn.node) return;
      if(ts.isIfStatement(node) || ts.isConditionalExpression(node)) {
        const isIf = ts.isIfStatement(node);
        const condition = isIf ? node.expression : node.condition;
        const prefix = branch ? `${branch}; ` : '';
        read(condition,branch);
        step(node,'Decision',`Read the condition ${literal(condition)}. Only the selected branch applies.`,branch);
        read(isIf ? node.thenStatement : node.whenTrue,`${prefix}If ${literal(condition)} is true`);
        read(isIf ? node.elseStatement : node.whenFalse,`${prefix}If ${literal(condition)} is false`); return;
      }
      if(ts.isBinaryExpression(node) && [ts.SyntaxKind.AmpersandAmpersandToken,ts.SyntaxKind.BarBarToken,ts.SyntaxKind.QuestionQuestionToken].includes(node.operatorToken.kind)) {
        read(node.left,branch);
        const condition = node.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken ? 'counts as true'
          : node.operatorToken.kind===ts.SyntaxKind.BarBarToken ? 'counts as false' : 'is null or undefined (a missing value)';
        const prefix = branch ? `${branch}; ` : '';
        read(node.right,`${prefix}If earlier value ${condition}`); return;
      }
      if(ts.isThrowStatement(node)) {read(node.expression,branch);step(node,'Possible failure','This statement throws. Later statements in this block are not on this failure path.',branch);return;}
      if(ts.isReturnStatement(node)) {read(node.expression,branch);step(node,'Output','This expression is returned if this point is reached; its value has not been measured.',branch);return;}
      if(ts.isCallExpression(node)) {
        read(node.expression,branch);node.arguments.forEach(argument=>read(argument,branch));
        let target=null; const expression=node.expression;
        if(ts.isIdentifier(expression) && !shadowed.has(expression.text)) {
          const matches=functions.filter(f=>f.name===expression.text);
          target=matches.length===1 ? {path:relativeFile,name:expression.text}:matches.length===0?bindings[expression.text]:null;
        } else if(ts.isPropertyAccessExpression(expression) && ts.isIdentifier(expression.expression) && !shadowed.has(expression.expression.text)) {
          const binding=bindings[expression.expression.text]; if(binding && binding.name===null)target={path:binding.path,name:expression.name.text};
        }
        step(node,'Call',`Calls ${literal(expression)} if reached. Dynamic or external targets remain unconfirmed.`,branch,{target:target?.path?target:null});return;
      }
      if(ts.isBinaryExpression(node) && node.operatorToken.kind===ts.SyntaxKind.EqualsToken && ts.isPropertyAccessExpression(node.left)) step(node,'State change','This statement assigns a property; storage lifetime is unknown.',branch);
      if(ts.isBlock(node)) {
        for(const statement of node.statements) {read(statement,branch); if(ts.isThrowStatement(statement) || ts.isReturnStatement(statement)) break;}
      } else ts.forEachChild(node,child=>read(child,branch));
    }
    read(fn.node.body);
    if(ts.isArrowFunction(fn.node) && !ts.isBlock(fn.node.body)) step(fn.node.body,'Output','This arrow function returns its expression when reached. Its actual value is unobserved.','');
    return {name:fn.name,exported:fn.exported,entry:handlers.has(fn.name)?'Direct JSX handler binding':fn.exported?'Exported function':'Declared function',...location(fn.node),steps};
  });

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
    outlines: source.parseDiagnostics.length ? [] : outlines,
    configuration_issues: configurationIssues.get(file) || [],
    diagnostics: source.parseDiagnostics.map(diagnostic => {
      const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n");
      if (diagnostic.start === undefined) return message;
      return `line ${source.getLineAndCharacterOfPosition(diagnostic.start).line + 1}: ${message}`;
    }),
  });
}
process.stdout.write(JSON.stringify(result));
