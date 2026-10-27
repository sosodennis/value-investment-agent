import { readFileSync } from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const appDirectory = path.dirname(fileURLToPath(import.meta.url));
const routeOwners = [
    { route: 'login/page.tsx', module: '@/features/auth/login-page', component: 'LoginPage' },
    { route: 'register/page.tsx', module: '@/features/auth/register-page', component: 'RegisterPage' },
    { route: 'settings/llm/page.tsx', module: '@/features/llm-settings/llm-settings-page', component: 'LlmSettingsPage' },
    { route: 'settings/search/page.tsx', module: '@/features/search-settings/search-settings-page', component: 'SearchSettingsPage' },
] as const;

describe('App Router feature boundaries', () => {
    it.each(routeOwners)('$route composes its feature page only', ({ route, module, component }) => {
        const file = path.join(appDirectory, route);
        const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

        expect(source.statements).toHaveLength(2);

        const [importStatement, exportStatement] = source.statements;
        expect(ts.isImportDeclaration(importStatement)).toBe(true);
        if (!ts.isImportDeclaration(importStatement)) throw new Error(`${route} must import its feature page.`);
        expect(ts.isStringLiteral(importStatement.moduleSpecifier) && importStatement.moduleSpecifier.text).toBe(module);
        expect(importStatement.importClause?.name?.text).toBe(component);

        expect(ts.isFunctionDeclaration(exportStatement)).toBe(true);
        if (!ts.isFunctionDeclaration(exportStatement)) throw new Error(`${route} must export a route component.`);
        expect(exportStatement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword)).toBe(true);
        expect(exportStatement.body?.statements).toHaveLength(1);
        const [returnStatement] = exportStatement.body?.statements ?? [];
        expect(returnStatement && ts.isReturnStatement(returnStatement)).toBe(true);
        if (!returnStatement || !ts.isReturnStatement(returnStatement)) throw new Error(`${route} must directly render its feature page.`);

        const element = returnStatement.expression;
        expect(element && ts.isJsxSelfClosingElement(element)).toBe(true);
        if (!element || !ts.isJsxSelfClosingElement(element)) throw new Error(`${route} cannot own route-level feature behavior.`);
        expect(ts.isIdentifier(element.tagName) && element.tagName.text).toBe(component);
        expect(element.attributes.properties).toHaveLength(0);
    });
});
