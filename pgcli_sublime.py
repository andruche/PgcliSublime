import sublime
import sublime_plugin
import logging
import sys
import os
import site
import traceback
import queue
import datetime
import time
import re
from urllib.parse import urlparse
from threading import Lock, Thread

try:
    from SublimeREPL.repls import Repl
    SUBLIME_REPL_AVAIL = True
except ImportError:
    SUBLIME_REPL_AVAIL = False

CLOSE_CONNECT_AFTER_IDLE_TIMEOUT = 30

maintain_job = None
completers = {}  # Dict mapping urls to pgcompleter objects
completer_lock = Lock()

executors = {}  # Dict mapping buffer ids to pgexecutor objects
executor_lock = Lock()

recent_urls = []


logger = logging.getLogger('pgcli_sublime')


def plugin_loaded():
    global settings
    settings = sublime.load_settings('PgcliSublime.sublime_settings')

    init_logging()
    logger.debug('Plugin loaded')

    # Before we can import pgcli, we need to know its path. We can't know that
    # until we load settings, and we can't load settings until plugin_loaded is
    # called, which is why we need to import to a global variable here

    sys.path = settings.get('pgcli_dirs') + sys.path
    for sdir in settings.get('pgcli_site_dirs'):
        site.addsitedir(sdir)

    logger.debug('System path: %r', sys.path)

    global PGCli, need_completion_refresh, need_search_path_refresh
    global has_meta_cmd, has_change_path_cmd, has_change_db_cmd, OutputSettings
    from pgcli.main import (
        PGCli, has_meta_cmd, has_change_path_cmd, has_change_db_cmd, OutputSettings
    )

    global PGExecute
    from pgcli.pgexecute import PGExecute

    global PGCompleter
    from pgcli.pgcompleter import PGCompleter

    global special
    from pgspecial.main import PGSpecial
    special = PGSpecial()

    global CompletionRefresher
    from pgcli.completion_refresher import CompletionRefresher

    global Document
    from prompt_toolkit.document import Document

    global fragment_list_to_text
    from prompt_toolkit.formatted_text import fragment_list_to_text

    global format_output
    from pgcli.main import format_output

    global psycopg2
    import psycopg2

    global ext
    import psycopg2.extensions as ext

    global sqlparse
    import sqlparse

    global maintain_job
    maintain_job = Thread(
        target=connection_maintain,
        args=(),
        name='connection_maintain'
    )
    maintain_job.setDaemon(True)
    maintain_job.start()


def plugin_unloaded():
    global MONITOR_URL_REQUESTS
    MONITOR_URL_REQUESTS = False

    global pgclis
    pgclis = {}

    global url_requests
    url_requests = queue.Queue()


def connection_maintain():
    if CLOSE_CONNECT_AFTER_IDLE_TIMEOUT == -1:
        return
    while True:
        time.sleep(5)
        for view_id, e in list(executors.items()):
            if e.conn.get_transaction_status() == ext.TRANSACTION_STATUS_IDLE:
                if e.last_use + CLOSE_CONNECT_AFTER_IDLE_TIMEOUT < time.time():
                    e.conn.close()
                    del executors[view_id]


class PgcliPlugin(sublime_plugin.EventListener):
    def on_close(self, view):
        executor = executors.pop(view.id(), None)
        if executor:
            executor.conn.close()

    def on_post_save_async(self, view):
        refresh_status(view)

    def on_load_async(self, view):
        refresh_status(view)

    def on_activated(self, view):
        refresh_status(view)

    def on_query_completions(self, view, prefix, locations):
        for pattern in settings.get('autocomplete_exclusions', []):
            if view.file_name() and re.match(pattern, view.file_name()):
                logger.debug('File excluded from autocompletion')
                return
        if not get(view, 'pgcli_autocomplete') or not is_sql(view):
            return []

        logger.debug('Searching for completions')

        url = get(view, 'pgcli_url')
        if not url:
            return

        with completer_lock:
            completer = completers.get(url)

        if not completer:
            return

        # Get current query
        text, cursor_pos = get_current_query(view)
        logger.debug('Position: %d Text: %r', cursor_pos, text)

        comps = completer.get_completions(
            Document(text=text, cursor_position=cursor_pos), None)

        if not comps:
            logger.debug('No completions found')
            return []

        comps = [('{}\t{}'.format(fragment_list_to_text(c.display),
                                  fragment_list_to_text(c.display_meta)),
                  c.text)
                 for c in comps]
        logger.debug('Found completions: %r', comps)

        return comps, (
                sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS
        )


class PgcliSwitchConnectionStringCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Change the current connection string'

    def run(self, edit):

        recent = set(recent_urls)
        extra = get(self.view, 'pgcli_urls')
        urls = list(reversed(recent_urls)) + [
            u for u in extra if u not in recent]

        def callback(i):
            if i == -1:
                return
            self.view.settings().set('pgcli_url', urls[i])
            executor = executors.pop(self.view.id(), None)
            if executor:
                executor.conn.close()

            check_pgcli(self.view)

        self.view.window().show_quick_panel(urls, callback)


class PgcliRunAllCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Run the entire contents of the view as a query'

    def run(self, edit):
        logger.debug('PgcliRunAllCommand')
        check_pgcli(self.view)
        sql = get_entire_view_text(self.view)
        t = Thread(target=run_sqls_async,
                   args=(self.view, [sql]),
                   name='run_sqls_async')
        t.setDaemon(True)
        t.start()


class PgcliRunCurrentCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Run the current selection or line as a query'

    def run(self, edit):
        logger.debug('PgcliRunCurrentCommand')
        check_pgcli(self.view)

        # Note that there can be multiple selections
        sel = self.view.sel()
        contents = [self.view.substr(reg) for reg in sel]
        sql = '\n'.join(contents)

        if not sql and len(sel) == 1:
            # Nothing highlighted - find the current query
            sql, _ = get_current_query(self.view)

        # Run the sql in a separate thread
        t = Thread(target=run_sqls_async,
                   args=(self.view, [sql]),
                   name='run_sqls_async')
        t.setDaemon(True)
        t.start()


class PgcliCancelExecuteCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Cancel running query'

    def run(self, edit):
        logger.debug('PgcliCancelExecuteCommand')
        panel = get_output_panel(self.view)

        executor = executors.get(self.view.id(), None)
        if executor:
            if executor.conn.get_transaction_status() == ext.TRANSACTION_STATUS_ACTIVE:
                executor.conn.cancel()
                out = 'send cancel signal to server\n\n'
            elif executor.conn.get_transaction_status() == ext.TRANSACTION_STATUS_INTRANS:
                out = 'no running commands for cancel\n'
                out += 'but connection is "idle in transaction"!!!\n'
                out += 'use commit/rollback for stop transaction\n\n'
        else:
            out = 'no running commands for cancel\n\n'
        panel.run_command('append', {'characters': out})


class PgcliCloseConnectionCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Close current connection'

    def run(self, edit):
        logger.debug('PgcliCloseConnectionCommand')
        panel = get_output_panel(self.view)

        executor = executors.get(self.view.id(), None)
        if executor:
            if executor.conn.get_transaction_status() == ext.TRANSACTION_STATUS_ACTIVE:
                executor.conn.cancel()
                time.sleep(0.2)
            executor.conn.close()
            del executors[self.view.id()]
            refresh_status(view)
            out = 'connection closed\n\n'
        else:
            out = 'no opened connection\n\n'
        panel.run_command('append', {'characters': out})


class PgcliRunCurrentOnCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Run the current selection on defined connection'

    def run(self, edit, url):
        logger.debug('PgcliRunCurrentOnCommand')
        panel = get_output_panel(self.view)

        if get(self.view, 'pgcli_url') != url:
            executor = executors.get(self.view.id(), None)
            if executor:
                if executor.conn.get_transaction_status() == ext.TRANSACTION_STATUS_ACTIVE:
                    out = 'connection processing sql-command; you need cancel it before\n\n'
                    panel.run_command('append', {'characters': out})
                    return
                if executor.conn.get_transaction_status() == ext.TRANSACTION_STATUS_INTRANS:
                    out = 'connection in transaction; you need commit/rollback before\n\n'
                    panel.run_command('append', {'characters': out})
                    return
                del executors[self.view.id()]
                executor.conn.close()
            self.view.settings().set('pgcli_url', url)

        check_pgcli(self.view)

        # Note that there can be multiple selections
        sel = self.view.sel()
        contents = [self.view.substr(reg) for reg in sel]
        sql = '\n'.join(contents)

        if not sql and len(sel) == 1:
            # Nothing highlighted - find the current query
            sql, _ = get_current_query(self.view)

        # Run the sql in a separate thread
        t = Thread(target=run_sqls_async,
                   args=(self.view, [sql]),
                   name='run_sqls_async')
        t.setDaemon(True)
        t.start()


class PgcliRunMacrosCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Run the macros with current selection'

    def run(self, edit, macros):
        def strip_query(query):
            query = query.strip()
            if query and query[-1] == ';':
                query = query[:-1]
            return query

        logger.debug('PgcliRunMacrosCommand')
        check_pgcli(self.view)

        if isinstance(macros, list):
            macros = '\n'.join(macros)

        # Note that there can be multiple selections
        sel = self.view.sel()
        selections = [strip_query(self.view.substr(reg))
                      for reg in sel]

        if selections == ['']:
            # Nothing highlighted - find the current query
            sql, _ = get_current_query(self.view)
            selections = [strip_query(sql)]

        sql = [macros.format(selection=selection)
               for selection in selections]
        if not sql:
            return

        # Run the sql in a separate thread
        t = Thread(target=run_sqls_async,
                   args=(self.view, sql),
                   name='run_sqls_async')
        t.setDaemon(True)
        t.start()


class PgcliExplainCurrentCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Run the current selection or line as a query'

    def run(self, edit):
        logger.debug('PgcliRunCurrentCommand')
        check_pgcli(self.view)

        # Note that there can be multiple selections
        sel = self.view.sel()
        contents = [self.view.substr(reg) for reg in sel]
        sql = '\n'.join(contents)

        if not sql and len(sel) == 1:
            # Nothing highlighted - find the current query
            sql, _ = get_current_query(self.view)

        sql = 'explain ' + sql

        # Run the sql in a separate thread
        t = Thread(target=run_sqls_async,
                   args=(self.view, [sql]),
                   name='run_sqls_async')
        t.setDaemon(True)
        t.start()


class PgcliDescribeTable(sublime_plugin.TextCommand):
    def description(self):
        return 'Describe table'

    def run(self, edit):
        logger.debug('PgcliDescribeTable')
        check_pgcli(self.view)

        def fix_region(reg):
            if reg.size():  # User selected a table/function name
                word = self.view.substr(reg)
                par = re.search('\\(.*', word)
                if par:  # Strip opening parenthesis and what follows
                    parlen = par.end() - par.start()
                    return sublime.Region(reg.begin(), reg.end() - parlen)
            else:  # Selection is just a cursor; expand to nearest word
                reg = self.view.word(reg)
                word = self.view.substr(reg)
                if re.match('\\(\\)?[;,]?\n?', word):
                    # Cursor after (; step back
                    newpos = reg.end() - len(word)
                    return fix_region(sublime.Region(newpos, newpos))
                elif self.view.substr(reg.begin() - 1) == '.':
                    # schema.table; cursor in table
                    schema = self.view.word(reg.begin() - 2)
                    reg = sublime.Region(schema.begin(), reg.end())
                elif self.view.substr(reg.end()) == '.':
                    # schema.table; cursor in schema
                    tbl = self.view.word(reg.end() + 1)
                    reg = sublime.Region(reg.begin(), tbl.end())

            return reg

        def is_func(region):
            return self.view.substr(region.end()) == '('

        sel = (fix_region(r) for r in self.view.sel())
        tbls = ((self.view.substr(reg), is_func(reg)) for reg in sel)
        sqls = (('\\df+ ' if f else '\\d+ ') + n for n, f in tbls)
        t = Thread(
            target=run_sqls_async,
            args=(self.view, sqls),
            name='run_sqls_async'
        )
        t.setDaemon(True)
        t.start()


class PgcliShowOutputPanelCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Show the output panel'

    def run(self, edit):
        logger.debug('PgcliShowOutputPanelCommand')
        sublime.active_window().run_command(
            'show_panel',
            {'panel': 'output.' + output_panel_name(self.view)}
        )


class PgcliOpenCliCommand(sublime_plugin.TextCommand):
    def description(self):
        return 'Open a pgcli command line prompt'

    def run(self, edit):
        logger.debug('PgcliOpenCliCommand')

        url = get(self.view, 'pgcli_url')
        if not url:
            logger.debug('No url for current view')
            return

        logger.debug('Opening a command prompt for url: %r', url)
        cmd = get(self.view, 'pgcli_system_cmd')
        cmd = cmd.format(url=url)
        os.system(cmd)


class PgcliNewSqlFileCommand(sublime_plugin.WindowCommand):
    def description(self):
        return 'Open a new SQL file'

    def run(self):
        """Open a new file with syntax defaulted to SQL"""
        logger.debug('PgcliNewSqlFile')
        self.window.run_command('new_file')
        view = self.window.active_view()
        view.set_syntax_file('Packages/SQL/SQL.tmLanguage')
        view.set_scratch(True)
        sublime.set_timeout_async(lambda: check_pgcli(view), 0)


class PgcliNewSublimeReplCommand(sublime_plugin.WindowCommand):
    def description(self):
        return 'Open a new pgcli REPL in SublimeREPL'

    def run(self):
        logger.debug('PgcliNewSublimeRepl')
        if self.window.active_view():
            url = get(self.window.active_view(), 'pgcli_url')
        else:
            url = settings.get('pgcli_url')

        self.window.run_command(
            'repl_open',
            {
                'encoding': 'utf8',
                'type': 'pgcli',
                'syntax': 'Packages/SQL/SQL.tmLanguage',
                'pgcli_url': url
            }
        )

    def is_enabled(self):
        return SUBLIME_REPL_AVAIL

    def is_visible(self):
        return SUBLIME_REPL_AVAIL


class PgcliSetScratchCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.active_view().set_scratch(True)


def get_current_query(view):
    text = get_entire_view_text(view)
    cursor_pos = view.sel()[0].begin()

    # Parse sql
    stack = sqlparse.engine.FilterStack()
    stack.split_statements = True
    cum_len = 0
    current_query = ""
    for query in stack.run(text):
        current_query = str(query)
        cum_len += len(current_query)
        if cursor_pos <= cum_len:
            break

    # calculate cursor position in query
    query_cursor_pos = len(current_query) - (cum_len - cursor_pos)

    return current_query, query_cursor_pos


def init_logging():
    for h in logger.handlers:
        logger.removeHandler(h)

    logger.setLevel(settings.get('pgcli_log_level', 'WARNING'))

    h = logging.StreamHandler(sys.stdout)
    h.setLevel(settings.get('pgcli_console_log_level', 'WARNING'))
    fmt = logging.Formatter('%(name)s: %(levelname)s: %(message)s')
    h.setFormatter(fmt)
    logger.addHandler(h)

    pgcli_logger = logging.getLogger('pgcli')
    pgcli_logger.addHandler(h)


def is_sql(view):
    if view.settings().get('repl'):
        # pgcli sublime repl has it's own thing
        return False

    syntax_file = view.settings().get('syntax')
    if syntax_file:
        return 'sql' in syntax_file.lower()
    else:
        return False


def check_pgcli(view):
    """Check if a pgcli connection for the view exists, or request one"""

    if not is_sql(view):
        refresh_status(view, '')
        return

    error = None
    with executor_lock:
        view_id = view.id()
        if view_id not in executors:
            url = get(view, 'pgcli_url')

            if not url:
                refresh_status(view)
                logger.debug('Empty pgcli url %r', url)
            else:
                # Make a new executor connection
                refresh_status(view, 'Connecting: ' + url)
                logger.debug('Connecting to %r', url)

                try:
                    executor = new_executor(url)
                    executors[view_id] = executor
                    refresh_status(view)
                except Exception as e:
                    error = e
                    logger.error('Error connecting to pgcli')
                    logger.error('traceback: %s', traceback.format_exc())
                    executor = None
                    status = 'ERROR CONNECTING TO {}'.format(url)
                    refresh_status(view, status)

                # Make sure we have a completer for the corresponding url
                with completer_lock:
                    need_new_completer = executor and url not in completers
                    if need_new_completer:
                        completers[url] = PGCompleter()  # Empty placeholder

                if need_new_completer:
                    refresher = CompletionRefresher()
                    refresher.refresh(executor, special=special, callbacks=(
                        lambda c: swap_completer(c, url)))
    return error


def refresh_status(view, status=None):
    if status is None:
        url = get(view, 'pgcli_url')
        if not url:
            status = ''
        else:
            user, _, host, _, dbname = parse_url(url)
            status = f'{user}@{host}/{dbname}'
            if view.id() not in executors:
                status += ' (closed)'
    view.set_status('pgcli', status)


def swap_completer(new_completer, url):
    with completer_lock:
        completers[url] = new_completer


def get(view, key):
    # Views may belong to projects which have project specific overrides
    # This method returns view settings, and falls back to base plugin settings
    val = view.settings().get(key)
    return val if val else settings.get(key)


def get_entire_view_text(view):
    return view.substr(sublime.Region(0, view.size()))


def output_panel_name(view):
    return '__pgcli__' + str(view.id())


def get_output_panel(view):
    return view.window().create_output_panel(output_panel_name(view))


def format_results(results, table_format):
    out = []

    for title, cur, headers, status, _, _ in results:
        fmt = format_output(title, cur, headers, status, table_format)
        out.append('\n'.join(fmt))

    return '\n\n'.join(out)


def parse_url(url):
    uri = urlparse(url)
    database = uri.path[1:]  # ignore the leading fwd slash
    return uri.username, uri.password, uri.hostname, uri.port, database


def new_executor(url):
    user, password, host, port, dbname = parse_url(url)
    dsn = None  # todo: what is this for again
    executor = PGExecute(dbname, user, password, host, port, dsn, connect_timeout=10)
    executor.last_use = time.time()
    return executor


def run_sqls_async(view, sqls):
    panel = get_output_panel(view)
    for sql in sqls:
        run_sql_async(view, sql, panel)


def run_sql_async(view, sql, panel):
    # Make sure the output panel is visible
    sublime.active_window().run_command('pgcli_show_output_panel')
    if view.id() not in executors:
        out = 'connection closed, trying reconnect ... '
        panel.run_command('append', {'characters': out, 'pos': 0})
        error = check_pgcli(view)
        if error:
            out = '%s: %s' % (error.__class__.__name__, error)
            panel.run_command('append', {'characters': out, 'pos': 0})
            return
    executor = executors[view.id()]
    executor.last_use = time.time()
    logger.debug('Command: PgcliExecute: %r', sql)
    save_mode = get(view, 'pgcli_save_on_run_query_mode')
    start = time.time()
    results = executor.run(sql, pgspecial=special)
    settings = OutputSettings('psql', "", "", "NULL", False, None)
    try:
        for (title, cur, headers, status, _, _, _) in results:
            status = None if status == 'SELECT 1' else status
            out = 'done in {:.6} ms\n'.format((time.time() - start) * 1000)
            panel.run_command('append', {'characters': out, 'pos': 0})
            if headers and len(headers) == 1:
                out = '\n' + '\n'.join(str(r[0]) for r in cur) + '\n\n'
            else:
                fmt = format_output(title, cur, headers, status, settings)
                out = '\n'.join(fmt) + '\n\n'
            panel.run_command('append', {'characters': out})
            start = time.time()
    except psycopg2.DatabaseError as e:
        success = False
        out = 'DatabaseError: ' + str(e) + '\n\n' + str(datetime.datetime.now())
        panel.run_command('append', {'characters': out})
    except psycopg2.InterfaceError as e:
        success = False
        out = 'InterfaceError: ' + str(e) + '\n\n' + str(datetime.datetime.now())
        panel.run_command('append', {'characters': out})
        del executors[view.id()]
    else:
        success = True

    if (view.file_name()
            and ((save_mode == 'always')
                 or (save_mode == 'success' and success))):
        view.run_command('save')

    # Refresh the table names and column names if necessary.
    if has_meta_cmd(sql):
        logger.debug('Need completions refresh')
        url = get(view, 'pgcli_url')
        refresher = CompletionRefresher()
        refresher.refresh(executor, special=special, callbacks=(
                          lambda c: swap_completer(c, url)))

    # Refresh search_path to set default schema.
    if has_change_path_cmd(sql):
        logger.debug('Refreshing search path')
        url = get(view, 'pgcli_url')

        with completer_lock:
            completers[url].set_search_path(executor.search_path())
            logger.debug('Search path: %r', completers[url].search_path)
