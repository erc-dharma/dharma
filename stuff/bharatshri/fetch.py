import datetime
import os
import re
import requests
from bs4 import BeautifulSoup

# Global variables to maintain session state and credentials.
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
SESSION.cookies.set('JS_OK', '1')
BASE_URL = 'https://bharatshri.asi.gov.in/FrontEndSearch'
LOGIN_URL = 'https://bharatshri.asi.gov.in/UserLogin'
USER_EMAIL = 'michaelnm.meyer@gmail.com'
USER_PASSWORD = 'Foobarbazqux1!'

def extract_form_fields(soup):
	# Extract form inputs while preserving current values and states.
	fields = {}
	for el in soup.find_all(['input', 'select', 'textarea']):
		name = el.get('name')
		if not name or el.get('type', '').lower() in ['submit', 'image', 'button']:
			continue
		fields[name] = el.get('value', '')
	for field in ['__EVENTTARGET', '__EVENTARGUMENT']:
		if field not in fields:
			fields[field] = ''
	return fields

def login():
	# Authenticate global session and handle login workflow.
	resp = SESSION.get(LOGIN_URL)
	soup = BeautifulSoup(resp.text, 'html.parser')
	payload = extract_form_fields(soup)
	payload['ctl00$ContentPlaceHolder1$txtEmail'] = USER_EMAIL
	payload['ctl00$ContentPlaceHolder1$txtPassword'] = USER_PASSWORD
	payload['ctl00$ContentPlaceHolder1$btnLogin'] = 'Log In'
	post_resp = SESSION.post(LOGIN_URL, data=payload)
	if post_resp.url == LOGIN_URL and "alert" not in post_resp.text:
		open("error_login.html", "w", encoding="utf-8").write(post_resp.text)
		raise ConnectionError("Authentication failed.")

def fetch_inscription_detail(row, search_soup):
	# Fetch detail page using base search tokens to avoid state corruption.
	epi = row.find('input', attrs={'name': lambda n: n and 'intEpi' in n})
	btn = row.find('input', type='image')
	if not epi or not btn:
		return None
	payload = extract_form_fields(search_soup)
	payload[epi['name']] = epi['value']
	payload[f"{btn['name']}.x"] = '10'
	payload[f"{btn['name']}.y"] = '10'
	resp = SESSION.post(BASE_URL, data=payload)
	return BeautifulSoup(resp.text, 'html.parser')

def extract_row_ar_number(row):
	# Extract AR Number directly from the second column of the search table row.
	cols = row.find_all('td')
	if len(cols) > 1:
		text = cols[1].text.strip()
		if text.startswith('AR_'):
			return text
	return None

def save_inscription_files(ar_number, detail_soup):
	# Save inscription PDF files and HTML file as completion marker.
	wrappers = detail_soup.find_all('div', class_='image-wrapper')
	type_totals = {}
	for w in wrappers:
		h = w.find('h4')
		if h:
			t = h.text.strip().lower()
			type_totals[t] = type_totals.get(t, 0) + 1
	counts = {}
	for wrapper in wrappers:
		h4 = wrapper.find('h4')
		if not h4:
			continue
		doc_type = h4.text.strip().lower()
		counts[doc_type] = counts.get(doc_type, 0) + 1
		resp = SESSION.get(f"https://bharatshri.asi.gov.in/PdfStream.aspx?doc={doc_type}")
		if resp.status_code == 200 and len(resp.content) > 100:
			suffix = f"_{counts[doc_type]}" if type_totals[doc_type] > 1 else ""
			open(f"{ar_number}_{doc_type}{suffix}.pdf", "wb").write(resp.content)
	open(f"{ar_number}.html", "w", encoding="utf-8").write(str(detail_soup))

def process_page_rows(soup):
	# Process table rows, skip if HTML exists, and return count of newly processed items.
	table = soup.find('table', id='ctl00_ContentPlaceHolder1_grdItemuom')
	if not table:
		return 0
	new_count = 0
	for idx, row in enumerate(table.find_all('tr')[1:], start=1):
		ar_number = extract_row_ar_number(row)
		if not ar_number:
			continue
		if os.path.exists(f"{ar_number}.html"):
			print(f"Skipping {ar_number} (already exists)")
			continue
		print(f"Processing inscription: {ar_number}")
		detail_soup = fetch_inscription_detail(row, soup)
		if not detail_soup:
			continue
		save_inscription_files(ar_number, detail_soup)
		new_count += 1
	return new_count

def get_next_page_token(soup):
	# Find pagination token for the next page or 'Page$Next'.
	for a in soup.find_all('a', href=True):
		href = a['href']
		text = a.text.strip().lower()
		if ('page$next' in href.lower() or text in ['>', 'next', '»']) and '__doPostBack' in href:
			match = re.search(r"__doPostBack\('(.*?)','(.*?)'\)", href)
			if match:
				return match.group(1), match.group(2)
	return None, None

def search_query(query_str):
	# Execute search for a specific year query and paginate dynamically.
	resp = SESSION.get(BASE_URL)
	soup = BeautifulSoup(resp.text, 'html.parser')
	payload = extract_form_fields(soup)
	payload['ctl00$ContentPlaceHolder1$txtsearch'] = query_str
	payload['ctl00$ContentPlaceHolder1$Button1'] = 'Search'
	current = BeautifulSoup(SESSION.post(BASE_URL, data=payload).text, 'html.parser')
	total_new = process_page_rows(current)
	while True:
		target, arg = get_next_page_token(current)
		if not target or not arg:
			break
		payload = extract_form_fields(current)
		payload['__EVENTTARGET'] = target
		payload['__EVENTARGUMENT'] = arg
		current = BeautifulSoup(SESSION.post(BASE_URL, data=payload).text, 'html.parser')
		new_on_page = process_page_rows(current)
		if new_on_page == 0:
			break
		total_new += new_on_page
	return total_new

login()
total_collected = 0
current_year = datetime.datetime.now().year
for year in range(1887, current_year + 1):
	tmp_file = f"{year}.tmp"
	# Skip the year if its completion temporary file already exists
	if os.path.exists(tmp_file):
		print(f"Skipping year {year} (already processed)")
		continue
	print(f"Searching for year: {year}")
	total_collected += search_query(str(year))
	# Create the temporary completion file once the year processing finishes
	open(tmp_file, "w").close()
print(f"Total new inscriptions collected and saved: {total_collected}")
