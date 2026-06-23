@subheader'''
import json
import copy
from dharma import common

# Load the search schema to resolve virtual fields during syntactic parsing
with open(common.path_of("search.json"), "r") as f:
	SEARCH_SCHEMA = json.load(f)

class Node:

	pass

class And(Node):

	def __init__(self, *children):
		self.children = list(children)

	def __repr__(self):
		buf = "(and "
		sep = ""
		for child in self.children:
			buf += sep + repr(child)
			sep = " "
		buf += ")"
		return buf

	def _complete_fields(self, name, mode=None):
		for i, child in enumerate(self.children):
			self.children[i] = child._complete_fields(name, mode)
		return self

	def serialize(self):
		return {
			"op": "and",
			"args": [c.serialize() for c in self.children],
		}

class Or(Node):

	def __init__(self, *children):
		self.children = list(children)

	def __repr__(self):
		buf = "(or "
		sep = ""
		for child in self.children:
			buf += sep + repr(child)
			sep = " "
		buf += ")"
		return buf

	def _complete_fields(self, name, mode=None):
		for i, child in enumerate(self.children):
			self.children[i] = child._complete_fields(name, mode)
		return self

	def serialize(self):
		return {
			"op": "or",
			"args": [c.serialize() for c in self.children],
		}

class Not(Node):

	def __init__(self, child=None):
		self.child = child

	def __repr__(self):
		buf = "(not "
		buf += repr(self.child)
		buf += ")"
		return buf

	def _complete_fields(self, name, mode=None):
		self.child = self.child._complete_fields(name, mode)
		return self

	def serialize(self):
		return {"op": "not", "arg": self.child.serialize()}

class Field(Node):

	def __init__(self, name, child=None, mode=None):
		self.name = name
		self.mode = mode
		self.child = child

	def __repr__(self):
		mode_str = f"[{self.mode}]" if self.mode else ""
		return f"{self.name or '<null>'}{mode_str}:{self.child!r}"

	def _resolve_name_mode(self, name, mode):
		# Extract field metadata to determine implicit text normalization behaviors
		final_name = self.name if self.name is not None else name
		final_mode = self.mode or mode
		if final_name:
			parts = final_name.split('.')
			if len(parts) > 1 and parts[-1] in SEARCH_SCHEMA.get("modes", []):
				final_mode = parts.pop()
				final_name = ".".join(parts)
			field_meta = SEARCH_SCHEMA["fields"].get(final_name, {})
			if not final_mode:
				final_mode = field_meta.get("default_mode", "normal")
		return final_name, final_mode

	def _expand_virtual(self, name, mode):
		# Convert virtual fieldsets into logical disjunctions using deep copies to avoid shared state mutations
		meta = SEARCH_SCHEMA["fields"].get(name, {})
		if meta.get("type") == "fieldset" and "expand_to" in meta:
			children = [Field(sub, copy.deepcopy(self.child), mode) for sub in meta["expand_to"]]
			return Or(*children)
		return None

	def _complete_fields(self, name, mode=None):
		# Resolve aliases and expand virtual nodes structurally
		final_name, final_mode = self._resolve_name_mode(name, mode)
		for k, v in SEARCH_SCHEMA["fields"].items():
			if final_name in v.get("aliases", []):
				final_name = k
				break
		virtual_node = self._expand_virtual(final_name, final_mode)
		if virtual_node:
			return virtual_node._complete_fields("", None)
		self.name = final_name
		self.mode = final_mode
		if not isinstance(self.child, str):
			self.child = self.child._complete_fields(self.name, final_mode)
		return self

	def serialize(self):
		res = {
			"op": "field",
			"field": self.name,
		}
		if isinstance(self.child, Node):
			res["arg"] = self.child.serialize()
		else:
			res["value"] = self.child
		if self.mode:
			res["mode"] = self.mode
		return res

class _Null(Node):

	def __repr__(self):
		return "<null>"

	def _complete_fields(self, name, mode=None):
		return self

	def serialize(self):
		return {"op": "null"}

Null = _Null()

def mkbinop(klass, l, r):
	if isinstance(l, klass):
		l.children.append(r)
		return l
	return klass(l, r)

def mkand(*elems):
	return mkbinop(And, *elems)

def mkor(*elems):
	return mkbinop(Or, *elems)

def mkmerge(*elems):
	match len(elems):
		case 0:
			return Null
		case 1:
			return elems[0]
		case 2:
			return mkand(*elems)
		case _:
			return And(*elems)
'''

start: r=Exprs $ { r._complete_fields("", None) }

Exprs: r=Expr* { mkmerge(*r) }

Expr: OrExpr

FieldExpr:
	| name=FieldName (':' | '=') r=PrimaryExpr { Field(name, r) }
	| PrimaryExpr

PrimaryExpr:
	| '(' r=Exprs ')' { r }
	| r=Text { Field(None, r) }

OrExpr:
	| r=OrExpr 'OR' s=AndExpr { mkor(r, s) }
	| AndExpr

AndExpr:
	| r=AndExpr 'AND' s=NotExpr { mkand(r, s) }
	| NotExpr

NotExpr:
	| 'NOT' r=NotExpr { Not(r) }
	| FieldExpr

Text: r=DottedName { r }

FieldName:
	| '.' r=DottedName { "." + r }
	| DottedName

DottedName:
	| r=NAME '.' s=DottedName { r.string + "." + s }
	| r=NAME { r.string }
