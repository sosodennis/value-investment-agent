import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../src/app/globals.css', import.meta.url), 'utf8');
const minimumContrast = 4.5;
const configuredPairs = [
    ['foreground/background', '--foreground', '--background'],
    ['card foreground/card', '--card-foreground', '--card'],
    ['popover foreground/popover', '--popover-foreground', '--popover'],
    ['primary foreground/primary', '--primary-foreground', '--primary'],
    ['secondary foreground/secondary', '--secondary-foreground', '--secondary'],
    ['accent foreground/accent', '--accent-foreground', '--accent'],
    ['muted foreground/muted', '--muted-foreground', '--muted'],
    ['destructive foreground/destructive', '--destructive-foreground', '--destructive'],
    ['sidebar foreground/sidebar', '--sidebar-foreground', '--sidebar'],
    ['sidebar primary foreground/sidebar primary', '--sidebar-primary-foreground', '--sidebar-primary'],
    ['chart axis/background', '--chart-axis', '--background'],
    ['chart tooltip foreground/background', '--chart-tooltip-foreground', '--chart-tooltip-background'],
];

const parseDeclarations = (block) => new Map(
    [...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(([, name, value]) => [name, value.trim()])
);

const readTheme = (selector) => {
    const match = css.match(new RegExp(`(?:^|\\n)${selector}\\s*\\{([^}]*)\\}`, 'm'));
    if (!match) throw new Error(`Could not find the ${selector} theme token block.`);
    return parseDeclarations(match[1]);
};

const resolveToken = (name, declarations, seen = new Set()) => {
    if (seen.has(name)) throw new Error(`Circular token reference: ${[...seen, name].join(' -> ')}`);
    const rawValue = declarations.get(name);
    if (!rawValue) throw new Error(`Missing configured token ${name}.`);
    const reference = rawValue.match(/^var\(\s*(--[\w-]+)\s*\)$/);
    if (reference) {
        seen.add(name);
        return resolveToken(reference[1], declarations, seen);
    }
    if (!/^#[\da-f]{3}(?:[\da-f]{3})?$/i.test(rawValue)) {
        throw new Error(`Expected ${name} to resolve to a hex color, got ${rawValue}.`);
    }
    return rawValue;
};

const parseHex = (hex) => {
    const digits = hex.slice(1);
    const normalized = digits.length === 3
        ? [...digits].map((digit) => `${digit}${digit}`).join('')
        : digits;
    return [0, 2, 4].map((offset) => Number.parseInt(normalized.slice(offset, offset + 2), 16) / 255);
};

const linearize = (channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4;

const luminance = (hex) => {
    const [red, green, blue] = parseHex(hex).map(linearize);
    return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
};

const contrastRatio = (foreground, background) => {
    const first = luminance(foreground);
    const second = luminance(background);
    return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
};

let failed = false;
for (const [themeName, selector] of [['light', ':root'], ['dark', '\\.dark']]) {
    const declarations = readTheme(selector);
    for (const [label, foregroundToken, backgroundToken] of configuredPairs) {
        const foreground = resolveToken(foregroundToken, declarations);
        const background = resolveToken(backgroundToken, declarations);
        const ratio = contrastRatio(foreground, background);
        const passes = ratio >= minimumContrast;
        console.log(`${passes ? 'PASS' : 'FAIL'} ${themeName} ${label}: ${ratio.toFixed(2)}:1 (minimum ${minimumContrast}:1)`);
        if (!passes) failed = true;
    }
}

if (failed) process.exitCode = 1;
