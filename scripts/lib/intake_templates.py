"""Writes docs/process/templates/ from the intake registry (D-205).

The four templates (intake, research, audit, plan) are rendered from config/registry/intake.json's
`intake.template_sections`: the title, the comment under the header and each section's heading and hint. The drift
check holds the rendering to the committed files and holds the section names the checker reads (intake.*_sections,
intake.choice_section and intake.alternatives_section) to the templates that carry them.
`scripts/intake-templates` writes the files; `--check` exits 1 on drift (no file is written).
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES = ('intake', 'research', 'audit', 'plan')


def templates_dir(root=ROOT):
    return Path(root) / 'docs' / 'process' / 'templates'


def template_file(name, root=ROOT):
    return templates_dir(root) / f'{name}.md'


def specs(sections=None):
    """{template name: its spec} from the registry list (or from `sections`, the same shape, for a test)."""
    return {item['name']: item for item in (sections or config.get('intake.template_sections'))}


def render(name, sections=None):
    """The text of one template, from the registry (or from `sections`, the same shape, for a test)."""
    spec = specs(sections)[name]
    blocks = [f"# <UNIT> — {spec['title']}", f"<!--{spec['header']}-->"]
    for section in spec['sections']:
        if 'comment' in section:
            blocks.append(f"## {section['heading']}\n<!--{section['comment']}-->")
        else:
            blocks.append(f"## {section['heading']}\n{section['lines']}")
    return '\n\n'.join(blocks) + '\n'


def headings(name, sections=None):
    spec = specs(sections)[name]
    return [section['heading'] for section in spec['sections']]


def registry_sections():
    """{template: the section names the checker reads, which the template must carry}."""
    get = config.get
    return {
        'intake': list(get('intake.intake_sections')),
        'research': list(get('intake.research_sections')),
        'audit': list(get('intake.audit_sections')),
        'plan': [get('intake.choice_section'), get('intake.alternatives_section')],  # effort.* left with D-328
    }


def check(root=ROOT, sections=None):
    """The drift: a list of problems, empty when the templates match the registry."""
    problems = []
    for name in TEMPLATES:
        path = template_file(name, root)
        rendered = render(name, sections)
        if not path.is_file():
            problems.append(f'{path}: missing; scripts/intake-templates writes it')
            continue
        if path.read_text() != rendered:
            problems.append(f'{path}: differs from the registry render; run scripts/intake-templates')
        present = set(headings(name, sections))
        for wanted in registry_sections()[name]:
            if wanted not in present:
                problems.append(f'{name}: the registry names "{wanted}", the template does not carry it')
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/intake-templates', description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='exit 1 on drift; write nothing')
    args = parser.parse_args(argv)
    if args.check:
        problems = check()
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    for name in TEMPLATES:
        path = template_file(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(name))
        print(f'wrote {path.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
