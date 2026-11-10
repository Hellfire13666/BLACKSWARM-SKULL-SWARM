"""ANSI truecolor output for BLACKSWARM; never modifies terminal settings.

`auto` paints only interactive terminal output when NO_COLOR is unset.
`always` explicitly requests color even if piped or NO_COLOR is set.
"""
from __future__ import annotations
import os
import sys
import json

RESET = "\x1b[0m"
PALETTE = (
    (128, 255, 79),  # acid green
    (98, 231, 255),  # cyan
    (154, 108, 255), # electric violet
    (255, 88, 196),  # magenta
    (255, 200, 82),  # solar yellow
    (52, 155, 255),  # cobalt blue
)
COLORS = {
    "green": (128, 255, 79),
    "cyan": (98, 231, 255),
    "purple": (177, 117, 255),
    "pink": (255, 88, 196),
    "yellow": (255, 204, 103),
    "blue": (82, 164, 255),
    "red": (255, 105, 105),
    "white": (235, 241, 255),
}


def paint(text, rgb, enabled=True, bold=False):
    value = str(text)
    if not enabled:
        return value
    r, g, b = rgb
    return f"\x1b[{'1;' if bold else ''}38;2;{r};{g};{b}m{value}{RESET}"


class Neon:
    def __init__(self, mode='auto', stream=None, environment=None):
        if mode not in ('auto', 'always', 'never'):
            raise ValueError('color mode must be auto, always or never')
        self.stream = stream if stream is not None else sys.stdout
        env = environment if environment is not None else os.environ
        self.env = env
        self.mode = mode
        self.enabled = mode == 'always' or (mode == 'auto'
             and bool(getattr(self.stream, 'isatty', lambda: False)())
             and env.get('TERM', '').lower() not in ('', 'dumb')
             and not env.get('NO_COLOR'))

    def fg(self, text, color='green', bold=False):
        return paint(text, COLORS[color], self.enabled, bold)

    def spectrum(self, text):
        # Keeps each letter legible and explicitly paints every visible glyph.
        return ''.join(paint(ch, PALETTE[i % len(PALETTE)], self.enabled, bold=True)
                       for i, ch in enumerate(text))

    def rainbow_words(self, value, offset=0):
        """Truecolor rainbow across *words*, preserving readable copied text.

        Input is pre-sanitized in terminal_event. No terminal configuration edits.
        """
        import re
        value = str(value)
        if not self.enabled:
            return value
        output = []
        index = 0
        for piece in re.findall(r'\s+|\S+', value):
            if piece.isspace():
                output.append(piece)
            else:
                output.append(paint(piece, PALETTE[(offset + index) % len(PALETTE)], True,
                                    bold=(index % 3 == 0)))
                index += 1
        return ''.join(output)

    def rainbow_band(self, offset=0, cells=12):
        """Small six-color rotating scanline, invisible when color is disabled."""
        if not self.enabled:
            return ''
        return ''.join(paint('▰', PALETTE[(offset + i) % len(PALETTE)], True)
                       for i in range(max(0, min(cells, 24))))

    def banner(self):
        print(self.fg('╔' + '═'*48 + '╗', 'purple'))
        print(self.fg('║', 'purple') + '  ☣  ' + self.spectrum('BLACKSWARM') +
              self.fg('  // GLITCHBYTE PHANTOM LABS', 'cyan') + '     ' + self.fg('║', 'purple'))
        print(self.fg('╚' + '═'*48 + '╝', 'purple'))
        print(' ' + self.fg('▰▰', 'green') + self.fg('▰▰', 'cyan') + self.fg('▰▰', 'purple') +
              self.fg('▰▰', 'pink') + self.fg('▰▰', 'yellow') + self.fg('▰▰', 'blue'))

    def startup(self, url, dbpath):
        self.banner()
        print(self.fg('  ● LAB v0.6.5', 'green') + '  ' + self.fg('LOCAL / PRIVATE', 'purple'))
        print(self.fg('  ◈ DASHBOARD  ', 'cyan') + url)
        print(self.fg('  ◈ VAULT      ', 'purple') + str(dbpath))
        print(self.fg('  ◈ CTRL+C     ', 'yellow') + 'Return to terminal with Ctrl+C')
        print(self.fg('  Existing projects and servers: UNTOUCHED', 'green'))

    def summary(self, row, dbpath, rid):
        self.banner()
        print(self.fg('  ◈ MODE       ', 'purple') + str(row['mode']).upper())
        print(self.fg('  ◈ LINKS      ', 'cyan') + self.fg(str(row['total']), 'green', True) + ' unique')
        print(self.fg('  ◈ SESSION    ', 'purple') + str(rid))
        reports = row.get('reports', {})
        if isinstance(reports, str):
            try:
                reports = json.loads(reports)
            except (ValueError, TypeError):
                reports = {}
        if not isinstance(reports, dict):
            reports = {}
        stats=row.get('stats',{})
        if isinstance(stats,str):
            try: stats=json.loads(stats)
            except (ValueError,TypeError): stats={}
        if isinstance(stats,dict) and stats.get('candidates') is not None:
            print(self.fg('  QUALITY      ', 'purple') + str(stats.get('quality','focused')).upper())
            print(self.fg('  CANDIDATES   ', 'cyan') + str(stats['candidates']) +
                  self.fg('   HIGH ', 'green') + str(stats.get('high',0)) +
                  self.fg('   POSSIBLE ', 'yellow') + str(stats.get('possible',0)) +
                  self.fg('   LOW ', 'red') + str(stats.get('filtered_low',0)))
            print(self.fg('  Scores are keyword heuristics, not verified accuracy.', 'yellow'))
        print(self.fg('  PROVIDER SIGNALS', 'pink', True))
        for name, report in reports.items():
            if not isinstance(report, dict):
                report = {'status': str(report), 'found': 0}
            status = report.get('status', 'unknown')
            failed = status == 'error'
            mark = '✗' if failed else '✓' if status == 'ok' else '·'
            color = 'red' if failed else 'green' if status == 'ok' else 'yellow'
            count = str(report.get('found', 0))
            print('    ' + self.fg(mark + ' ' + name.upper().ljust(12), color)
                + self.fg(status.upper().ljust(12), color) + self.fg(count.rjust(5), 'cyan'))
            if failed and report.get('detail'):
                print('      ' + self.fg(str(report['detail']), 'yellow'))
        print(self.fg('  ✓ SAVED TO   ', 'green') + str(dbpath))
        # Keep legacy report line available for scripts, except in colorful TTY output.
        if not self.enabled:
            print('Provider status:', reports)

    def test(self):
        print('BLACKSWARM // LINUX TERMINAL NEON CHECK (read-only)')
        print('  TERM=' + (self.env.get('TERM') or '(not set)'))
        print('  COLORTERM=' + (self.env.get('COLORTERM') or '(not set)'))
        print('  NO_COLOR=' + ('set' if self.env.get('NO_COLOR') else 'not set'))
        print('  TTY=' + ('yes' if getattr(self.stream, 'isatty', lambda: False)() else 'no'))
        print('  COLOR MODE=' + self.mode)
        self.banner()
        for label in ('green', 'cyan', 'purple', 'pink', 'yellow', 'blue', 'red'):
            print(self.fg('  ■■■■■■■■  ' + label.upper(), label, True))
        print('  If the blocks above have vivid colors, your terminal can show neon.')
        print('  No settings, themes, files or vault data were changed.')
