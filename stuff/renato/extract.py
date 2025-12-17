import sys, os, itertools
from dharma import tree

"""
Dataset of Early Tamil Epigraphical Evidence for Fractional Terminology in Land Measurement ---------"Development of Tamil Fractions

Dataset of Fractions in the Chola Thanjavur Village Grants (SII 2.4-2.5) -------- "Chola Fractional Calculations"
"""

p = sys.stdout.write

# for development-tamil-fractions.fods
def translate_span1(span):
	name = span["style-name"]
	match name:
		case "T1" | "T7":
			span.name = "i"
			span.attrs.clear()
		case "T2" | "T4" | "T6":
			span.unwrap()
		case "T3" | "T5":
			span.name = "b"
			span.attrs.clear()
		case _:
			assert 0

# for chola-fractional-calculations.fods
def translate_span2(span):
	name = span["style-name"]
	match name:
		case "T1" | "T4":
			span.name = "b"
			span.attrs.clear()
		case "T2" | "T3" | "T6":
			span.unwrap()
		case "T5":
			span.name = "i"
			span.attrs.clear()

translate_span = {
	"development-of-tamil-fractions.fods": translate_span1,
	"chola-fractional-calculations.fods": translate_span2,
}

def print_card(cells):
	print('<div class="card">')
	print('\t<div class="card-data">')
	for field, cell in itertools.zip_longest(fields[:8], cells[:8], fillvalue=tree.Tag("p")):
		p("\t<div>")
		for stuff in field:
			if isinstance(stuff, tree.String) and len(stuff.strip()) == 0:
				continue
			assert isinstance(stuff, tree.Tag) and stuff.name == "p"
			p(stuff.xml())
		p("</div>\n")
		p("\t<div>")
		first = True
		indent = False
		for stuff in cell:
			if isinstance(stuff, tree.String) and len(stuff.strip()) == 0:
				continue
			assert isinstance(stuff, tree.Tag)
			if stuff.name == "p":
				p(stuff.xml())
				continue
			assert stuff.name == "div", stuff.xml()
			indent = True
			if first:
				first = False
				p("\n")
			p("\t\t" + stuff.xml() + "\n")
		if indent:
			p("\t")
		p("</div>\n")
	print("\t</div>")
	print("</div>")

fields = []

path = sys.argv[1]
t = tree.parse(path)
table = t.first("//table")
assert table

prev = None
just_print = False
print('<div class="card-list">')
for row in table.find("table-row"):
	cells = row.find("table-cell")
	for cell in cells:
		for span in cell.find(".//span"):
			assert isinstance(span, tree.Tag)
			translate_span[os.path.basename(path)](span)
		for s in cell.find(".//s"):
			s.unwrap()
	if not fields:
		fields = cells
		continue
	if os.path.basename(path) != "chola-fractional-calculations.fods":
		print_card(cells)
		continue
	if just_print:
		print_card(cells)
		continue
	if len(cells) == 10:
		print_card(prev)
		just_print = True
		print_card(cells)
		continue
	if len(cells) == 9:
		if prev:
			print_card(prev)
		for i in 3, 4, 6:
			tmp = tree.Tag("div")
			for stuff in cells[i]:
				if isinstance(stuff, tree.String):
					assert len(stuff.strip()) == 0
					continue
				tmp.append(stuff.copy())
			div = tree.Tag("div")
			div.append(tmp)
			cells[i].replace_with(div)
			cells[i] = div
		prev = cells
		continue
	assert len(cells) <= 4, cells
	tmp = tree.Tag("div")
	for stuff in cells[0]:
		if isinstance(stuff, tree.String):
			assert len(stuff.strip()) == 0
			continue
		tmp.append(stuff.copy())
	prev[3].append(tmp)
	tmp = tree.Tag("div")
	for stuff in cells[1]:
		if isinstance(stuff, tree.String):
			assert len(stuff.strip()) == 0
			continue
		tmp.append(stuff.copy())
	prev[4].append(tmp)
	tmp = tree.Tag("div")
	for stuff in cells[2]:
		if isinstance(stuff, tree.String):
			assert len(stuff.strip()) == 0
			continue
		tmp.append(stuff.copy())
	prev[6].append(tmp)
print("</div>")
