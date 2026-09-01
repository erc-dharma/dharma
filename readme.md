# dharma

This is the code for the DHARMA application.

## Dependencies

The following Python packages need to be installed with `pip`:

	apsw
	bs4
	flask
	PyICU
	requests
	saxonche
	websockets
	pegen

Note that the Python package for [ICU](https://icu.unicode.org/) is `PyICU`, not
`icu`! PyICU does not automatically install the libraries it needs to work, and
it wants all the ICU stuff to be installed, including the build tools, so you
need to install `libicu-devel` or `libicu-dev` (depending on the distribution),
not just `libicu`. You also need to install Python's headers (`python-devel` or
`python-dev`).

You also need to install a Golang environment on each machine you intend to run the application on. See [here](https://go.dev/doc/install) for installation details.

Also needed are [`pandoc`](https://pandoc.org) (we use it at runtime
for rendering Markdown files) and the `sqlite3` command-line tool.

The code's documentation can be browsed with the `pdoc` tool:

	pdoc dharma

## Bootstrapping

You need to clone this repository with its submodules:

	git clone --recursive git@github.com:erc-dharma/dharma.git

The repository's directory must be placed somewhere on `$PYTHONPATH`, so you
need to modify this variable accordingly (or to move the directory in one of the
directories enumerated in `$PYTHONPATH`).

Once done, `cd` to the repository and run:

	python change.py

This will clone all DHARMA repositories and create the main database
(`dbs/texts.sqlite`).

To add a new repository, you need to add an entry the file
`repos/project-documentation/DHARMA_repositories.tsv`. The update process will
pick it up and pull the repository.

There is also a separate, secondary database for searching parallel verses. It
is stored at `dbs/parallels.sqlite`. To build it, run:

	python parallels.py

This latter database is not automatically updated, so rebuilding it manually is
necessary.

##  Entry points

There are five main programs. On our server, they run concurrently and are
managed by `systemd`, but they can also be run manually, independently of
each other.

Firstly, we have a server program. It is used for read-only operations: display,
search, etc. It never writes to the database. The code's entry point is in
`server.py`. We do not use threads for concurrency, thus thread safety is not
tested. It is possible to run several server processes simultaneously, if the
backend supports it.

Secondly, we have an update program. It is used for updating the database when
people push to git repositories or modify our Zotero bibliography. This is the
only program that modifies the database. The code's entry point is in
`change.py`. A single update process should run at a given time, not more. To
update the database, other processes communicate with this process through a
named pipe. Once the `change.py` process is up and running, it is possible to
talk to it by echoing stuff into the named pipe. For instance, the following:

	echo .bib > change.hid

... triggers an update of the bibliography. A full list of update commands is
given in `change.py`. Likewise,

	echo tfa-pallava-epigraphy > change.hid

... triggers an update of the `tfa-pallava-epigraphy` repository.

Thirdly, we have a WebSocket client that is hooked to Zotero and that notifies
the update process whenever someone modifies the project's bibliography. The
code is in `zotero.py`.

Fourthly, we have a program for accessing zotero.org. The code is in
`zotero_proxy.py`. This is a server that is queried by XSLT files when they try
to access the bibliography. They make a lot of calls to the Zotero API, and
Zotero servers are often overloaded, thus we use a proxy that repeats API calls
on error, to prevent our builds from failing all the time. The Zotero proxy also
allows querying the bibliography by short titles (lookup keys), which Zotero's
API does not support.

Finally, we have a search server, written in Go. The generated binary is named
`dharma-search`. You need to start it if you need the python server to talk to
it (for the search page). The code is in the `*.go` files in the `search`
directory. This server is not meant to be accessible from the internet. It is
used internally by the main Python server from `server.py`. The search server
only accesses the disk when the database is updated: it pulls all the data it
needs from the database, loads it into memory, and performs searches on that.

## Configuration

The `config` directory holds configuration files that are deployed on our
server. There is a config file for `nginx`, as well as `systemd` unit files.
`systemd` tasks are scheduled to run at startup, so nothing special needs to
be done after rebooting the server. To install all config files, run (as root):

	make install

This moves configuration files to the proper system directories and reloads both
`nginx` and `systemd`'s configuration manager. Then the app's services can be
started (or restarted) and stopped with:

	make start
	make stop

## Search System

The search system is written partly in Go, partly in Python. We use Go because
it is fast enough to do this kind of stuff while also being simple enough to
read and debug. All the code related to the search system (both the Python code
and the Go code) is written with Gemini.

The search system works by converting both texts and queries to a few simplified
representations, before doing the actual matching. These transformations are
performed with a number of re2c lexers. When documents (more precisely, their
fields) are transformed to a given simplified representation, the result is
cached, because these transformations are rather slow to perform. The cache is
emptied and subsequently rebuilt when we detect a modification to the database.

Now some possible improvements.

Problem with the current approach for search: we need to keep in-memory several
versions of each edition. It might be better (albeit maybe slower) to use a
single representation for the editions, and to transform the user query to a
regular expression that would match what we want (turning e.g. "amṛta" into
"am[rṛ]ta") and that would then be evaluated against the simplified text. But
doing that requires manipulating automata, so we would need to use or write a
library for that.

Currently, in the search system, the Go code is fast enough, but the Python code
is rather slow because of all the XML parsing and generation. The Python code
should thus be reworked.

We could use the TRE library or equivalent to allow fuzzy search (with the
Levenshtein distance). Would be useful for Indic languages that we cannot parse.

We could use the dharmamitra.org parser for processing Sanskrit (but only
Sanskrit). This would allow us to use a traditional search engine architecture
and other useful applications.
