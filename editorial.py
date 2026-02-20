# TODO the editorial stuff has become complicated enough that we should use a
# TEI file for encoding it instead of a markdown file. Do this and reuse the
# "common" code for parsing TEI files.

from dharma import tree, common, languages, texts, ingest, enrich, render
import bs4, copy

tpl = """
<TEI>
<text><body>
<div type="{context}" xml:lang="eng">{code}</div>
</body></text>
</TEI>
"""

def parse_xml(context, code):
	data = tpl.format(context=context, code=code).encode()
	t = tree.parse_string(data, path="whatever")
	languages.add_lang_info(t)
	html = tree.html_format(t.first(f"//div[@type='{context}']"), skip_root=True)
	file = texts.File("whatever", "whatever")
	setattr(file, "_data", data)
	doc_tree = ingest.process_file(file)
	enrich.process(doc_tree)
	block = render.process(doc_tree).body
	# XXX
	for expr in ["//h2", "//ul[@class='ed-tabs']", "//div[@class='physical' or @class='logical']"]:
		for node in block.find(expr):
			node.delete()
	for node in block.find("//div[@class='full hidden']"):
		node["class"] = "full"
	block = block.html()
	# XXX need some way to delimit the relevant HTML and also only to select the "full" display when we're parsing div[@type='edition']
	return block, html

def is_heading(node):
	if not isinstance(node, bs4.Tag):
		return  False
	tag = node.name
	return len(tag) == 2 and tag[0] == "h" and tag[1] >= "1" and tag[1] <= "6"

def parse_html():
	f = texts.File("project-documentation", "website/editorial-conventions.md")
	html = common.pandoc(f.text)
	soup = bs4.BeautifulSoup(html, "html.parser")
	# Grab the page title.
	title = soup.find("h1")
	if title:
		page_title = "".join(t.get_text() for t in title)
		title.decompose()
	else:
		page_title = "Untitled"
	for title in soup.find_all("h6"):
		title.name = "div"
		title.attrs.clear()
		title.attrs["class"] = ["card-heading"]
		div = soup.new_tag("div", **{"class": "card-body"})
		node = title.next_sibling
		while node is not None and not is_heading(node):
			if isinstance(node, bs4.Tag) and node.name == "pre":
				if "translation" in node.attrs.get("class", []):
					context = "translation"
				else:
					context = "edition"
				display, pretty_xml = parse_xml(context, node.get_text())
				demo = soup.new_tag("div", **{"class": "edition-demo"})
				code = soup.new_tag("div", **{"class": "xml"})
				code.append(bs4.BeautifulSoup(pretty_xml, "html.parser"))
				rendered = soup.new_tag("div", **{"class": ["ed",
					context == "edition" and "full" or "translation"]})
				rendered.append(bs4.BeautifulSoup(display, "html.parser"))
				demo.append(code)
				demo.append(rendered)
				div.append(demo)
			else:
				div.append(copy.copy(node))
			next = node.next_sibling
			if isinstance(node, bs4.Tag):
				node.decompose()
			else:
				node.extract()
			node = next
		title.insert_after(div)
	for code in soup.find_all("code"):
		code.attrs.setdefault("class", []).append("xml")
	contents = str(soup.find("body"))
	return page_title, contents

if __name__ == "__main__":
	@common.transaction("texts")
	def main():
		parse_html()
	main()
