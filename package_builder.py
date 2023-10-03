#!/usr/bin/python3

import os
import zipfile


package_name = 'PgcliSublime.sublime-package'


if os.path.isfile(package_name):
    os.remove(package_name)
d = os.path.dirname(__file__)
with zipfile.ZipFile(package_name, mode='a',
                     compression=zipfile.ZIP_DEFLATED) as zf:
    zf.write(os.path.join(d, 'CHANGELOG.md'),
             arcname='CHANGELOG.md')
    zf.write(os.path.join(d, '.python-version'),
             arcname='.python-version')
    zf.write(os.path.join(d, 'Default (Linux).sublime-keymap'),
             arcname='Default (Linux).sublime-keymap')
    zf.write(os.path.join(d, 'Default (OSX).sublime-keymap'),
             arcname='Default (OSX).sublime-keymap')
    zf.write(os.path.join(d, 'Default (Windows).sublime-keymap'),
             arcname='Default (Windows).sublime-keymap')
    zf.write(os.path.join(d, 'Default.sublime-commands'),
             arcname='Default.sublime-commands')
    zf.write(os.path.join(d, 'LICENSE.txt'),
             arcname='LICENSE.txt')
    zf.write(os.path.join(d, 'Main.sublime-menu'),
             arcname='Main.sublime-menu')
    zf.write(os.path.join(d, 'PgcliSublime.sublime_settings'),
             arcname='PgcliSublime.sublime_settings')
    zf.write(os.path.join(d, 'README.md'),
             arcname='README.md')
    zf.write(os.path.join(d, 'pgcli_sublime.py'),
             arcname='pgcli_sublime.py')
    zf.write(os.path.join(d, 'pgcli_sublime_repl.py'),
             arcname='pgcli_sublime_repl.py')
print(f'write to {package_name}')
