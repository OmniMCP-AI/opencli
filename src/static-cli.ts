import * as path from 'node:path';
import ts from 'typescript';
import { type Arg, type CliCommand, type RequiredEnv, Strategy } from './registry.js';

type StaticValue =
  | string
  | number
  | boolean
  | null
  | StaticValue[]
  | { [key: string]: StaticValue };

const STRATEGY_VALUES = new Set<string>(Object.values(Strategy));

export function extractStaticCliCommands(
  sourceText: string,
  filePath: string,
  expectedSite?: string,
): CliCommand[] | null {
  const sourceFile = ts.createSourceFile(
    filePath,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    scriptKindForFile(filePath),
  );
  const bindings = collectTopLevelBindings(sourceFile);
  const commands: CliCommand[] = [];
  let cliCallCount = 0;
  let unsupported = false;

  const visit = (node: ts.Node): void => {
    if (unsupported) return;

    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'cli') {
      cliCallCount += 1;
      const [firstArg] = node.arguments;
      if (!firstArg || !ts.isObjectLiteralExpression(firstArg)) {
        unsupported = true;
        return;
      }

      const raw = evaluateExpression(firstArg, bindings, new Set());
      const command = raw ? toStaticCliCommand(raw, expectedSite) : null;
      if (!command) {
        unsupported = true;
        return;
      }
      commands.push(command);
      return;
    }

    ts.forEachChild(node, visit);
  };

  visit(sourceFile);

  if (cliCallCount === 0) return null;
  if (unsupported || commands.length !== cliCallCount) return null;
  return commands;
}

function scriptKindForFile(filePath: string): ts.ScriptKind {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.ts' || ext === '.mts' || ext === '.cts') return ts.ScriptKind.TS;
  if (ext === '.tsx') return ts.ScriptKind.TSX;
  if (ext === '.jsx') return ts.ScriptKind.JSX;
  return ts.ScriptKind.JS;
}

function collectTopLevelBindings(sourceFile: ts.SourceFile): Map<string, ts.Expression> {
  const bindings = new Map<string, ts.Expression>();

  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    if (!(statement.declarationList.flags & ts.NodeFlags.Const)) continue;

    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !declaration.initializer) continue;
      bindings.set(declaration.name.text, declaration.initializer);
    }
  }

  return bindings;
}

function evaluateExpression(
  expression: ts.Expression,
  bindings: Map<string, ts.Expression>,
  seenBindings: Set<string>,
): StaticValue | undefined {
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return expression.text;
  }

  if (ts.isNumericLiteral(expression)) {
    return Number(expression.text);
  }

  if (expression.kind === ts.SyntaxKind.TrueKeyword) return true;
  if (expression.kind === ts.SyntaxKind.FalseKeyword) return false;
  if (expression.kind === ts.SyntaxKind.NullKeyword) return null;

  if (ts.isParenthesizedExpression(expression) || ts.isAsExpression(expression) || ts.isTypeAssertionExpression(expression)) {
    return evaluateExpression(expression.expression, bindings, seenBindings);
  }

  if (ts.isPrefixUnaryExpression(expression)) {
    const value = evaluateExpression(expression.operand, bindings, seenBindings);
    if (typeof value !== 'number' && typeof value !== 'boolean') return undefined;
    switch (expression.operator) {
      case ts.SyntaxKind.MinusToken:
        return typeof value === 'number' ? -value : undefined;
      case ts.SyntaxKind.PlusToken:
        return typeof value === 'number' ? value : undefined;
      case ts.SyntaxKind.ExclamationToken:
        return !value;
      default:
        return undefined;
    }
  }

  if (ts.isIdentifier(expression)) {
    const binding = bindings.get(expression.text);
    if (!binding || seenBindings.has(expression.text)) return undefined;
    seenBindings.add(expression.text);
    const value = evaluateExpression(binding, bindings, seenBindings);
    seenBindings.delete(expression.text);
    return value;
  }

  if (
    ts.isPropertyAccessExpression(expression)
    && ts.isIdentifier(expression.expression)
    && expression.expression.text === 'Strategy'
  ) {
    const strategy = Strategy[expression.name.text as keyof typeof Strategy];
    return typeof strategy === 'string' ? strategy : undefined;
  }

  if (ts.isArrayLiteralExpression(expression)) {
    const values: StaticValue[] = [];
    for (const element of expression.elements) {
      if (ts.isSpreadElement(element)) return undefined;
      const value = evaluateExpression(element, bindings, seenBindings);
      if (value === undefined) return undefined;
      values.push(value);
    }
    return values;
  }

  if (ts.isObjectLiteralExpression(expression)) {
    const result: Record<string, StaticValue> = {};
    for (const property of expression.properties) {
      if (!ts.isPropertyAssignment(property)) return undefined;
      const key = getPropertyName(property.name);
      if (!key) return undefined;
      if (key === 'func') continue;
      const value = evaluateExpression(property.initializer, bindings, seenBindings);
      if (value === undefined) return undefined;
      result[key] = value;
    }
    return result;
  }

  return undefined;
}

function getPropertyName(name: ts.PropertyName): string | undefined {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text;
  }
  return undefined;
}

function toStaticCliCommand(value: StaticValue, expectedSite?: string): CliCommand | null {
  if (!isStaticRecord(value)) return null;
  if (!hasStaticMetadataBeyondIdentity(value)) return null;

  const site = typeof value.site === 'string' ? value.site : '';
  const name = typeof value.name === 'string' ? value.name : '';
  if (!site || !name) return null;
  if (expectedSite && site !== expectedSite) return null;

  const strategy = normalizeStrategy(value.strategy, value.browser);
  const browser = typeof value.browser === 'boolean'
    ? value.browser
    : (strategy !== Strategy.PUBLIC && strategy !== Strategy.LOCAL);

  let navigateBefore: boolean | string | undefined;
  if (typeof value.navigateBefore === 'boolean' || typeof value.navigateBefore === 'string') {
    navigateBefore = value.navigateBefore;
  } else if ((strategy === Strategy.COOKIE || strategy === Strategy.HEADER) && typeof value.domain === 'string') {
    navigateBefore = `https://${value.domain}`;
  } else if (strategy !== Strategy.PUBLIC && strategy !== Strategy.LOCAL) {
    navigateBefore = true;
  }

  const aliases = toStringArray(value.aliases);
  if (value.aliases !== undefined && aliases === null) return null;
  const argsValue = toArgs(value.args);
  if (argsValue === null) return null;
  const columns = toStringArray(value.columns);
  if (value.columns !== undefined && columns === null) return null;
  const pipelineValue = toPipeline(value.pipeline);
  if (pipelineValue === null) return null;
  const requiredEnvValue = toRequiredEnv(value.requiredEnv);
  if (requiredEnvValue === null) return null;
  const timeoutSeconds = typeof value.timeoutSeconds === 'number' && Number.isFinite(value.timeoutSeconds)
    ? value.timeoutSeconds
    : undefined;
  const deprecated = typeof value.deprecated === 'boolean' || typeof value.deprecated === 'string'
    ? value.deprecated
    : undefined;
  const replacedBy = typeof value.replacedBy === 'string' ? value.replacedBy : undefined;
  const workspace = typeof value.workspace === 'string' ? value.workspace : undefined;
  const description = typeof value.description === 'string' ? value.description : '';
  const domain = typeof value.domain === 'string' ? value.domain : undefined;
  const defaultFormat = typeof value.defaultFormat === 'string' ? value.defaultFormat as CliCommand['defaultFormat'] : undefined;

  return {
    site,
    name,
    workspace,
    aliases: normalizeAliases(aliases ?? undefined, name),
    description,
    domain,
    strategy,
    browser,
    args: argsValue,
    columns: columns ?? undefined,
    pipeline: pipelineValue,
    timeoutSeconds,
    requiredEnv: requiredEnvValue,
    deprecated,
    replacedBy,
    navigateBefore,
    defaultFormat,
  };
}

function hasStaticMetadataBeyondIdentity(value: { [key: string]: StaticValue }): boolean {
  const metadataKeys = [
    'workspace',
    'aliases',
    'description',
    'domain',
    'strategy',
    'browser',
    'args',
    'columns',
    'pipeline',
    'timeoutSeconds',
    'deprecated',
    'replacedBy',
    'navigateBefore',
    'requiredEnv',
    'defaultFormat',
  ];
  return metadataKeys.some(key => value[key] !== undefined);
}

function normalizeStrategy(raw: StaticValue | undefined, browser: StaticValue | undefined): Strategy {
  if (typeof raw === 'string' && STRATEGY_VALUES.has(raw)) {
    return raw as Strategy;
  }
  return browser === false ? Strategy.PUBLIC : Strategy.COOKIE;
}

function normalizeAliases(aliases: string[] | undefined, commandName: string): string[] | undefined {
  if (!aliases?.length) return undefined;

  const seen = new Set<string>();
  const result: string[] = [];
  for (const alias of aliases) {
    const value = alias.trim();
    if (!value || value === commandName || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result.length > 0 ? result : undefined;
}

function toStringArray(value: StaticValue | undefined): string[] | null | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) return null;
  if (!value.every(item => typeof item === 'string')) return null;
  return [...value];
}

function toArgs(value: StaticValue | undefined): Arg[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return null;

  const args: Arg[] = [];
  for (const item of value) {
    if (!isStaticRecord(item)) return null;
    if (typeof item.name !== 'string') return null;

    const arg: Arg = { name: item.name };
    if (typeof item.type === 'string') arg.type = item.type;
    if (item.default !== undefined) arg.default = item.default;
    if (typeof item.required === 'boolean') arg.required = item.required;
    if (typeof item.valueRequired === 'boolean') arg.valueRequired = item.valueRequired;
    if (typeof item.positional === 'boolean') arg.positional = item.positional;
    if (typeof item.help === 'string') arg.help = item.help;
    if (item.choices !== undefined) {
      if (!Array.isArray(item.choices) || !item.choices.every(choice => typeof choice === 'string')) return null;
      arg.choices = [...item.choices];
    }
    args.push(arg);
  }

  return args;
}

function toPipeline(value: StaticValue | undefined): Record<string, unknown>[] | null | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) return null;
  if (!value.every(item => isStaticRecord(item))) return null;
  return value.map(item => ({ ...item }));
}

function toRequiredEnv(value: StaticValue | undefined): RequiredEnv[] | null | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) return null;

  const envs: RequiredEnv[] = [];
  for (const item of value) {
    if (!isStaticRecord(item) || typeof item.name !== 'string') return null;
    const env: RequiredEnv = { name: item.name };
    if (item.help !== undefined) {
      if (typeof item.help !== 'string') return null;
      env.help = item.help;
    }
    envs.push(env);
  }
  return envs;
}

function isStaticRecord(value: StaticValue | undefined): value is { [key: string]: StaticValue } {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
