import os, re, glob, unicodedata
from bs4 import BeautifulSoup

ignore = set("""
AR_B0534_1912-13E
AR_B0530_1913
AR_B0109_1913
AR_C0273_1916
AR_B0011_1945_46
AR_B0075_1945_46
AR_B0087_1945_46
AR_B0219_1945_46
AR_A0061_1900_01
AR_B0235_1945_46
AR_B0206-1940-41
AR_B0220_1892_93
AR_B0218-1940-41
AR_B0233-1940-41
AR_B0201-1940-41
AR_B0094_1891-92-E
AR_C0271_1916
AR_B0213_1945_46
AR_B0086_1902_03
AR_A0449_1901_02
AR_A0249_1900_01
AR_B0236_1945_46
AR_B0040_1945_46
AR_B0211-1940-41
AR_A0066_1900_01
AR_B0228-1940-41
AR_B0038_1945_46
AR_B0184-1924-25
AR_A0268_1900_01
AR_C0272_1916
AR_A0008_1900_01
AR_C0270_1916
AR_B0213-1940-41
AR_B0537_1913
""".strip().split())

rename = {
"AR_B0605 1919-20": "AR_B0605_1919-20",
"AR_E0010-1928-29": "AR_E0010_1928-29",
"AR_B0315_1921–22": "AR_B0315_1921-22",
"AR_C0037_1925-1926": "AR_C0037_1925-26",
"AR_A00061913-1914": "AR_A0006_1913-14",
"AR_C0014_1920–21": "AR_C0014_1920-21",
"AR_C0071-1925-26": "AR_C0071_1925-26",
"AR_C0127­1920-21": "AR_C0127_1920-21",
"AR_C114819451946": "AR_C1148_1945-46",
"AR_B_0499_ 1906-07": "AR_B0499_1906-07",
"AR_B0030_24-1925": "AR_B0030_1924-25",
"AR_C0128­1920–21": "AR_C0128_1920-21",
"AR_C13791945-146": "AR_C1379_1945-46",
"AR_C0126–1920-21": "AR_C0126_1920-21",
"AR_C0268 1927-27": "AR_C0268_1927-27",
"AR_B0405_20-1921": "AR_B0405_1920-21",
"AR_C0309_1925_26": "AR_C0309_1925-26",
"AR_C0221-1925-26": "AR_C0221_1925-26",
"AR_B_0394_ 1906-07": "AR_B0394_1906-07",
"AR_B0420_1920\n21": "AR_B0420_1920-21",
}

def clean_text(text):
	# Remove extra whitespace and newlines from extracted text.
	return " ".join(text.split())

def parse_split_box(box):
    # Extract section title
    h3 = box.find('h3')
    if not h3:
        return None, []

    section_title = clean_text(h3.text)
    pairs = []
    strong_tags = box.find_all('strong')

    # Si on trouve des balises <strong>, on applique la logique clé: valeur habituelle
    if strong_tags:
        for strong in strong_tags:
            key = clean_text(strong.text.replace(':', ''))
            span = strong.find_next('span')
            val = clean_text(span.text) if span else ""
            if val:
                pairs.append((key, val))
    else:
        # S'il n'y a pas de <strong> (cas de la section Remarks), on cherche directement le span
        span = box.find('span')
        if span:
            val = clean_text(span.text)
            if val:
                # On utilise None pour la clé puisqu'il n'y en a pas
                pairs.append((None, val))

    return section_title, pairs

def parse_html_file(filepath):
    # Parse an inscription HTML file and return formatted text lines.
    soup = BeautifulSoup(open(filepath, 'r', encoding='utf-8').read(), 'html.parser')
    lines = []
    for box in soup.find_all('div', class_='split-box'):
        title, pairs = parse_split_box(box)
        if not title or not pairs:
            continue

        lines.append(f"# {title}")
        for k, v in pairs:
            # Si une clé existe on formate "Clé: Valeur", sinon juste la valeur
            if k:
                lines.append(f"{k}: {v}")
            else:
                lines.append(v)
        lines.append("")

    ret = "\n".join(lines).strip() + "\n"
    return unicodedata.normalize("NFC", ret)

all_files = os.listdir()
for file in glob.glob("*.html"):
	file = os.path.splitext(file)[0]
	# The following are empty
	if file.endswith(".pdf"):
		continue
	if file in ignore:
		continue
	orig_file = file
	repl = rename.get(file)
	if repl:
		assert not os.path.exists(f"{repl}.html")
		file = repl
	match = re.fullmatch(r"AR_(.+?)_([0-9]{4}-[0-9]{2})", file)
	assert match
	date = match.group(2)
	# Some dates are invalid:
	# 1889-99
	# 1925-16
	# 1927-27
	# We don't do anything about it.
	try:
		os.mkdir(date)
	except FileExistsError:
		pass
	metadata = parse_html_file(f"{orig_file}.html")
	with open(f"{date}/{file}.txt", "w") as f:
		f.write(metadata)
	for f in all_files:
		if f.startswith(orig_file) and not os.path.splitext(f)[-1] == ".html":
			new_f = file + f.removeprefix(orig_file)
			print(f, "->", new_f)
			os.rename(f, f"{date}/{new_f}")

