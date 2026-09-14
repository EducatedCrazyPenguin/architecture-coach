import fs from "node:fs";
import ts from "typescript";

const result = [];
for (const file of process.argv.slice(2)) {
  const text = fs.readFileSync(file, "utf8");
  const kind = file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const imports = [];
  const definitions = [];
  function visit(node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) imports.push(node.moduleSpecifier.text);
    if ((ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)) && node.name) {
      definitions.push({ name: node.name.text, kind: ts.isClassDeclaration(node) ? "class" : "function", line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1 });
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  result.push({ file, imports, definitions, diagnostics: source.parseDiagnostics.map(d => ts.flattenDiagnosticMessageText(d.messageText, "\n")) });
}
process.stdout.write(JSON.stringify(result));

