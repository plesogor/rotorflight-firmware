#!/usr/bin/env python3
"""Generate CLI dictionary JSON from firmware source.

Extracts:
- cmdTable[] from src/main/cli/cli.c
- valueTable[] from src/main/cli/settings.c

This generator is intended to be re-run for future firmware revisions
when CLI commands/settings change.
"""
from __future__ import annotations
import argparse, json, pathlib, re


def extract_brace_block(text: str, anchor: str) -> str:
    start = text.index(anchor)
    start = text.index('{', start)
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    raise ValueError(f"unterminated block for {anchor}")


def decode_c_string(token: str | None) -> str | None:
    if token is None or token == 'NULL':
        return None
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', token)
    return bytes(''.join(parts), 'utf-8').decode('unicode_escape')


def collect_conditional_stack(line: str, stack: list[str]) -> None:
    s = line.strip()
    if s.startswith(('#if', '#ifdef', '#ifndef')):
        stack.append(s)
    elif s.startswith('#else'):
        if stack:
            stack[-1] = f"{stack[-1]} | ELSE"
    elif s.startswith('#endif'):
        if stack:
            stack.pop()


def parse_commands(cli_text: str) -> list[dict]:
    block = extract_brace_block(cli_text, 'const clicmd_t cmdTable[]')
    stack: list[str] = []
    out = []
    rx = re.compile(
        r'CLI_COMMAND_DEF\("([^"]+)",\s*(NULL|"(?:[^"\\]|\\.)*")\s*,\s*'
        r'(NULL|"(?:[^"\\]|\\.)*"(?:\s*"(?:[^"\\]|\\.)*")*)\s*,\s*([A-Za-z0-9_]+)\)'
    )
    for line in block.splitlines():
        collect_conditional_stack(line, stack)
        m = rx.search(line)
        if not m:
            continue
        name, desc, args, handler = m.groups()
        args_decoded = decode_c_string(args)
        patterns = []
        if args_decoded:
            patterns = [p.strip() for p in args_decoded.replace('\r', '').split('\n') if p.strip()]
        out.append({
            'name': name,
            'description': decode_c_string(desc),
            'args': args_decoded,
            'handler': handler,
            'feature_flags': stack.copy(),
            'argument_patterns': patterns,
        })
    return out


def parse_settings(settings_text: str) -> list[dict]:
    block = extract_brace_block(settings_text, 'const clivalue_t valueTable[]')
    stack: list[str] = []
    out = []
    rx = re.compile(
        r'\{\s*"([^"]+)"\s*,\s*([^,]+),\s*\.config\.([A-Za-z0-9_]+)\s*=\s*\{\s*([^}]*)\}\s*,\s*'
        r'([A-Z0-9_]+)\s*,\s*offsetof\(([^)]+)\)\s*\},?'
    )
    for line in block.splitlines():
        collect_conditional_stack(line, stack)
        m = rx.search(line.strip())
        if not m:
            continue
        name, type_expr, cfg_kind, cfg_expr, pgn, offset = m.groups()
        out.append({
            'name': name,
            'type_expr': type_expr.strip(),
            'config_kind': cfg_kind,
            'config_expr': cfg_expr.strip(),
            'pgn': pgn,
            'offset': offset,
            'feature_flags': stack.copy(),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2])
    ap.add_argument('--out', type=pathlib.Path, default=None)
    args = ap.parse_args()

    root = args.root.resolve()
    out = args.out or (root / 'src/main/cli/cli_command_dictionary.json')

    cli_text = (root / 'src/main/cli/cli.c').read_text()
    settings_text = (root / 'src/main/cli/settings.c').read_text()

    data = {
        'source_files': ['src/main/cli/cli.c', 'src/main/cli/settings.c', 'src/main/cli/settings.h'],
        'commands': parse_commands(cli_text),
        'settings': parse_settings(settings_text),
        'metadata': {
            'generated_from_source_only': True,
            'generator': 'scripts/generate_cli_dictionary.py',
            'notes': [
                'No commands inferred from sample dumps; intended for autocomplete and dump validation.',
                'Regenerate this file for new firmware revisions when CLI commands/settings change.',
                'Future direction: firmware-emitted CLI metadata would simplify this extraction path.'
            ],
        },
    }
    out.write_text(json.dumps(data, indent=2) + '\n')
    print(f'wrote {out} commands={len(data["commands"])} settings={len(data["settings"])}')


if __name__ == '__main__':
    main()
