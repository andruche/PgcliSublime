# PgcliSublime
A plugin for [Sublime Text 4](http://www.sublimetext.com/4) supporting
database-aware smart autocompletion via [pgcli](http://pgcli.com)

## Requirements
pgcli running in Python 3.8. (This is the version of python shipped with
Sublime Text 4). I recommend installing pgcli in a virtual environment.

## Installation
### Plugin
```
$ git clone https://github.com/andruche/PgcliSublime.git
$ cd PgcliSublime
$ python3 package_builder.py
$ mv PgcliSublime.sublime-package "<path to Installed Packages>/"
```
### Pgcli python module
```
$ python3.8 -m venv /Users/andrey/Library/ve_pgcli_sublime/
$ source /Users/andrey/Library/ve_pgcli_sublime/bin/activate
$ pip install pgcli==3.1.0
```
Add directory path into "Preferences | Package Settings | PgcliSublime | Settings - User"
```
{
  "pgcli_dirs": ["/Users/andrey/Library/ve_pgcli_sublime/lib/python3.8/site-packages/"],
}
```

### Optional
  -  If you want to run a pgcli postgresql command line prompt directly in Sublime Text,
    install the very cool [SublimeREPL](https://github.com/wuub/SublimeREPL) via
    Package Control: ```Preferences | Package Control | Install Package | SublimeREPL```

## Configuration

### Settings
Open the default settings file:
```Preferences | Package Settings | PgcliSublime | Settings - Default```
and the user settings file:
```Preferences | Package Settings | PgcliSublime | Settings - User```.
Copy and paste the contents of the defaults file into the user file. You
*could* edit the default settings file directly, but your changes would be
overwritten every time you update PgcliSublime.

The most important configuration is setting up the path correctly, so the
Sublime Text 4 python interpreter can import pgcli. If you run python 3.8 as
your system-wide interpreter, and pgcli is installed in your global
site-packages, you don't need to do anything. If on the other hand you have
pgcli installed in a virtual environment, the easiest thing to do is add that
virtual environment's site-packages directory to the ```pgcli_site_dirs```
setting. Note that path strings need to be "double-quoted" and backslashes need
to be escaped. See below for an example configuration. NOTE: You will have to
restart Sublime Text for changes to the pgcli paths to take effect.

Next, specify your default database url in the ```pgcli_url``` setting. You can
leave this as ```postgresql://``` to default to your PGHOSTNAME, PGDATABASE,
and PGUSER values.

Finally, if you wish to enable a shortcut to open a pgcli command prompt,
fill in the "pgcli_system_cmd". This will be OS-specific.

### Example configuration
Here is the configuration I use in windows. I have one pgcli python 3.8 virtual
environment called pgcli3. Because there's currently issues with
python-prompt-toolkit in windows with python 3, I have a second pgcli python
2.7 virtual environment called pgcli2 that I use to run the command prompt.

 ```
{
   // Use pgcli to for autocomplete? If false, standard sublime autocompletion is used
   "pgcli_autocomplete": 			true,

   // List of python directories to add to python path so pgcli can be imported
   "pgcli_dirs": 					[
      // path to python3.8 site-packages, examples:
      // Windows:
      "C:\\Users\\<username>\\AppData\\Local\\Programs\\Python\\Python39\\lib\\site-packages",
      // Linux:
      "/usr/local/lib64/python3.8/site-packages/"
      // macOS:
      "/Library/Frameworks/Python.framework/Versions/3.8/lib/python3.8/site-packages/"
      // or if you use venv (recomended):
      "<venv_path>/lib/python3.8/site-packages/"
   ],

   // List of python site directories to add to python path so pgcli can be imported
   "pgcli_site_dirs": 				[],

   // The path to the postgresql database. This may also be overridden in project-specific settings
   "pgcli_url": 					"postgresql://postgres@localhost/test",

   // The command to send to os.system to open a pgcli command prompt
   // {url} is automatically formatted with the appropriate database url
   "pgcli_system_cmd":             "start cmd.exe /k \"activate pgcli2 && pgcli {url}\"",
}
```

### Keyboard shortcuts
You can view the default keyboard shortcuts with
`Preferences | Package Settings | PgcliSublime | Key Bindings - Default`
and the user override file:
`Preferences | Package Settings | PgcliSublime | Key Bindings - User`.
Again, you can copy and paste the contents of the defaults file into the user
file.

Default settings:
```
[
    {
        "keys":    ["alt+enter"],
        "command": "pgcli_run_all",
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        "keys":    ["ctrl+alt+enter"],
        "command": "pgcli_run_current",
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        "keys":    ["ctrl+shift+c"],
        "command": "pgcli_cancel_execute",
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        "keys":    ["alt+`"],
        "command": "pgcli_show_output_panel"
    },
    {
        "keys":    ["ctrl+f12"],
        "command": "pgcli_open_cli"
    },
    {
        "keys":    ["alt+f12"],
        "command": "pgcli_new_sublime_repl"
    },
    {
        "keys":    ["ctrl+alt+shift+n"],
        "command": "pgcli_new_sql_file"
    },
    {
        "keys":    ["ctrl+alt+shift+c"],
        "command": "pgcli_switch_connection_string"
    },
    {
        "keys":    ["f1"],
        "command": "pgcli_describe_table",
        "context": [{"key": "selector", "operand": "source.sql"}]
    }
]
```
Example for client settings:
```
[
    {
        "keys":    ["f5"],
        "command": "pgcli_run_current",
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        "keys":    ["f7"],
        "command": "pgcli_explain_current",
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        "keys":    ["ctrl+1"],
        "command": "pgcli_run_current_on",
        "args":    {"url": "postgresql://postgres@127.0.0.1:5432/test_db1"},
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        "keys":    ["ctrl+2"],
        "command": "pgcli_run_current_on",
        "args":    {"url": "postgresql://postgres@127.0.0.1:5432/test_db2"},
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        //get last 100 rows from <selected> table
        "keys":    ["alt+f1"],
        "command": "pgcli_run_macros",
        "args":    {"macros": "select * from %s order by 1 desc limit 100"},
        "context": [{"key": "selector", "operand": "source.sql"}]
    },
    {
        //build insert sql for <selected> table
        "keys":    ["alt+f2"],
        "command": "pgcli_run_macros",
        "args": {"macros": [
            "select format(e'INSERT INTO %%s(%%s)\n  VALUES (%%s);',   ",
            "                           attrelid::regclass::text,      ",
            "               string_agg(attname, ', ' order by attnum), ",
            "               string_agg(atttypid::regtype::text,        ",
            "                                   ', ' order by attnum)) ",
            "  from pg_attribute                                       ",
            " where attrelid = '%s'::regclass and                      ",
            "       attnum > 0 and                                     ",
            "       not attisdropped                                   ",
            " group by attrelid                                        "] },
        "context": [{"key": "selector", "operand": "source.sql"}]
    }
]
```

## Usage

### Auto-complete
PgcliSublime auto-complete runs in files with a SQL syntax. Create a new file
and manually set the syntax via the menu ```View | Syntax | SQL```, or save
a file with a .sql extension, or use the PgcliSublime shortcut
```<ctrl-alt-shift-N>``` to open a new file and automatically set the syntax to
SQL. While typing a query in an SQL file, either ```<tab>``` or
```<ctrl-space>``` should trigger an autocomplete menu.

### Run query
Run the contents of the current view as a pgcli query with either the shortcut
```<alt-enter>``` or via the menu  ```Tools | PgcliSublime | Run query```.
Output from the query will be printed to the sublime text console -- Hit
```ctrl-~``` to toggle it, or the menu ```View - Show console```.

### Open pgcli command prompt
If you've configured the ```pgcli_system_cmd``` setting, you can open a pgcli
REPL with the shortcut ```<ctrl-F12>```, or via the menu
```Tools | PgcliSublime | Open command prompt```

### Open pgcli SublimeREPL
If you have [SublimeREPL](https://github.com/wuub/SublimeREPL) installed,
```<alt-F12``` or the menu option ```Open a new pgcli REPL in SublimeREPL```
should open a new tab with a pgcli instance connected to the current database.
See [SublimeREPL documentation](http://sublimerepl.readthedocs.org/en/latest/)
for further shortcuts and features.


## Trouble-shooting
I've only tested this in Windows so bug reports are appreciated. Check the
sublime console (```<ctrl-~>```) for any error messages.
