"Stuff for enumerating texts (inscriptions, etc.) in a repository."

import os, os.path, unicodedata, typing
from dharma import common, validate

_valid_prefixes = {"DHARMA_INS", "DHARMA_DiplEd", "DHARMA_CritEd"}
"""Files that start with these prefixes are assumed to be TEI editions (but
there are other additional criteria, see the code)."""

_ignore_dirs = {"sii-corpus"}

# XXX need to have static methods for creating files: from a real file on disk;
# from the db (in-memory file maskerading as a real one, see save_file()); and for creating an
# anonymous in-memory file (for editorial, maybe somewhere else too).
# .from_string(data, path=':memory:') for the /convert endpoint
# .from_db(ident) for the catalog rebuild stuff
# .from_disk(repo, path) for normal operations

class File:

	def __init__(self, repo="", path="", data=None,
		mtime=None, last_modified=None, owners=None, status=None):
		"""`repo` is the repo name (e.g. `tfa-pallava-epigraphy`).
		`path` is the file path relative to the repository directory
		e.g. `texts/xml/DHARMA_INSPallava00002.xml`.
		"""
		self.repo: str = repo
		"Name of the repository (e.g. `tfa-pallava-epigraphy`)."
		self.path: str = path
		"""Path of the file relative to the repository directory
		(e.g. `texts/xml/DHARMA_INSPallava00002.xml`)."""
		self._status = kwargs.get("status")
		self._mtime = kwargs.get("mtime")
		self._data = kwargs.get("data")
		if isinstance(self._data, str):
			self._data = self._data.encode("utf-8")
		self._owners = kwargs.get("owners")
		self._last_modified = kwargs.get("last_modified")
		self.virtual: bool = self._data is not None
		"""Whether this file was constructed from a real file or from
		memory. A file created from memory might correspond to a real
		file on the disk, but we don't attempt to examine the disk if
		this is the case."""

	def __repr__(self):
		return f"File({self.repo!r}, {self.path!r})"

	@property
	def status(self) -> int:
		"""Validation status. See the enum in `validate.py`. This is
		currently only relevant for TEI editions."""
		if self._status is None:
			self._status = validate.status(self)
		return self._status

	@property
	def name(self) -> str:
		"""File basename without the extension e.g.
		`DHARMA_INSPallava00002`."""
		return os.path.splitext(os.path.basename(self.path))[0]

	@property
	def mtime(self) -> int:
		"""Value of `st_mtime`. We use this to figure out which files have
		been updated after we do a pull. We do not rely on git both
		because this is unnecessary and because at a later point we will
		want to be able to track other sources than git repos, like e.g.
		local directories, maybe with inotify or friends."""
		if self._mtime is None:
			if self.virtual:
				return 0
			self._mtime = int(os.stat(self.full_path).st_mtime)
		return self._mtime

	@property
	def data(self) -> bytes:
		"""File contents, as a byte string."""
		if self._data is None:
			if self.virtual:
				raise Exception(f"virtual file {self.path} has no data")
			with open(self.full_path, "rb") as f:
				self._data = f.read()
		return self._data

	@property
	def text(self) -> str:
		"""File contents, as a NFC-normalized Unicode string"""
		return unicodedata.normalize("NFC", self.data.decode())

	@property
	def owners(self) -> list[str]:
		"""Git names of the people who modified this file, as a sorted
		set. This is used in the debugging page so that people can
		filter by their name.
		"""
		if self._owners is None:
			if self.virtual:
				return []
			out = common.command("git",
				"-C", common.path_of("repos", self.repo),
				"log", "--follow", "--format=%aN", "--", self.path)
			ret = sorted(set(out.stdout.splitlines()))
			assert len(ret) > 0
			self._owners = ret
		return self._owners

	@property
	def last_modified(self) -> tuple[str, int]:
		"""When the file was last modified according to git. Returns a
		tuple (commit_hash, commit_timestamp). This is only for display,
		for convenience. We do not use this for other purposes.
		"""
		if self._last_modified is None:
			if self.virtual:
				return ("", 0)
			out = common.command("git",
				"-C", common.path_of("repos", self.repo),
				"log", "-1", "--format=%H %at", "--", self.path)
			commit, date = out.stdout.strip().split()
			date = int(date)
			self._last_modified = (commit, date)
		return self._last_modified

	@property
	def full_path(self) -> str:
		"""Full absolute path of the file in the file system, e.g.
		`/home/michael/dharma/repos/tfa-pallava-epigraphy/texts/xml/DHARMA_INSPallava00002.xml`.
		"""
		return common.path_of("repos", self.repo, self.path)

def iter_files_in_repo(repo: str) -> typing.Generator[File, None, None]:
	"""Iterates over all files in a given repository (but ignores hidden
	directories). `repo` is the name of the repository (e.g.
	`tfa-pallava-epigraphy`).
	"""
	repo_path = common.path_of("repos", repo)
	for root, dirs, files in os.walk(repo_path):
		# Ignore hidden directories.
		for dir in list(dirs):
			if dir.startswith("."):
				dirs.remove(dir)
		for file in files:
			full_path = os.path.join(root, file)
			rel_path = os.path.relpath(full_path, repo_path)
			yield File(repo, rel_path)

def iter_texts_in_repo(repo: str) -> typing.Generator[File, None, None]:
	"""Iterates over TEI editions in a repository. `repo` is the name of the
	repository (e.g. `tfa-pallava-epigraphy`).
	"""
	repo_path = common.path_of("repos", repo)
	for root, dirs, files in os.walk(repo_path):
		# Ignore hidden directories.
		for dir in list(dirs):
			if dir.startswith("."):
				dirs.remove(dir)
			if dir in _ignore_dirs:
				dirs.remove(dir)
		for file in files:
			_, ext = os.path.splitext(file)
			# Ignore non-XML files.
			if ext.lower() != ".xml":
				continue
			# Ignore files whose name does not match an edition
			# prefix.
			if not any(file.startswith(p) for p in _valid_prefixes):
				continue
			# Ignore "template" files. This should be removed
			# eventually, too ad hoc.
			if "template" in file.lower():
				continue
			full_path = os.path.join(root, file)
			rel_path = os.path.relpath(full_path, repo_path)
			yield File(repo, rel_path)

def save(repo: str, path: str):
	"Save a file in the database and returns it as well."
	file = File(repo, path)
	db = common.db("texts")
	db.save_file(file)
	return file
