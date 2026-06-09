const floatingUI = window.FloatingUIDOM

// Remove a node from the tree but keep its descendants in-place.
function unwrap(node) {
	node.replaceWith(...node.childNodes)
}

// Remove a node and its descendants.
function decompose(node) {
	node.replaceWith("")
}

function getCSSVar(name) {
	return getComputedStyle(document.documentElement).getPropertyValue(name)
}

let sidebarWidth = localStorage.getItem("sidebar-width") || "23vw"
let style = document.createElement('style')
document.head.appendChild(style)
style.sheet.insertRule(
`#sidebar {
	width: ${sidebarWidth};\
}`)

document.addEventListener("visibilitychange", function () {
	let node = document.querySelector("#sidebar")
	if (!node)
		return
	let width = getComputedStyle(node).getPropertyValue("width")
	localStorage.setItem("sidebar-width", width)
})

// menu

let menu = null
let menuIcon = null
let menuVisible = null
let menuContainer = null

let submenu = null
let submenus = []

class Submenu {

	constructor(node) {
		this.container = node
		this.submenu = node.querySelector("ul")
		this.submenu.style["min-width"] = getComputedStyle(this.container).getPropertyValue("width")
		console.assert(this.submenu.classList.contains("hidden"))
		this.visible = false
		this.button = node.querySelector("a")
		this.icon = this.button.querySelector("i")
		this.button.addEventListener("click", (event) => {
			event.preventDefault()
			this.toggle()
		}, false)
		this.cleanup = null
	}

	updatePosition() {
		floatingUI.computePosition(this.container, this.submenu, {
			placement: "bottom-end",
			middleware: [floatingUI.shift()]
		}).then(({x, y}) => {
			this.submenu.style.top = `${y}px`,
			this.submenu.style.left = `${x}px`
		})
	}

	show() {
		console.assert(!this.visible)
		console.assert(!this.cleanup)
		console.assert(this.submenu.classList.contains("hidden"))
		this.container.append(this.submenu)
		this.submenu.classList.remove("hidden")
		this.cleanup = floatingUI.autoUpdate(this.container,
			this.submenu, () => {this.updatePosition()})
		this.icon.classList.remove("fa-caret-down")
		this.icon.classList.add("fa-caret-up")
		this.visible = true
		submenu = this
	}

	hide() {
		console.assert(this.visible)
		console.assert(this.cleanup)
		console.assert(!this.submenu.classList.contains("hidden"))
		this.submenu.classList.add("hidden")
		this.submenu.remove()
		this.cleanup()
		this.cleanup = null
		this.icon.classList.remove("fa-caret-up")
		this.icon.classList.add("fa-caret-down")
		this.visible = false
		submenu = null
	}

	toggle() {
		if (submenu && submenu !== this) {
			submenu.hide()
		}
		if (this.visible)
			this.hide()
		else
			this.show()
	}
}

function initMenu() {
	menu = document.querySelector("#menu")
	menuVisible = !menu.classList.contains("hidden")
	menuIcon = document.querySelector("#menu-toggle i")
	menuContainer = document.querySelector("#menu-bar")
	for (let node of menu.querySelectorAll(".submenu"))
		submenus.push(new Submenu(node))
	document.querySelector("#menu-toggle").addEventListener("click", toggleMenu, false)
}

function showMenu() {
	console.assert(!menuVisible)
	console.assert(menu.classList.contains("hidden"))
	menu.classList.remove("hidden")
	menuIcon.classList.remove("fa-caret-down")
	menuIcon.classList.add("fa-caret-up")
	menuVisible = true
}

function hideMenu() {
	console.assert(menuVisible)
	console.assert(!menu.classList.contains("hidden"))
	menu.classList.add("hidden")
	menuIcon.classList.remove("fa-caret-up")
	menuIcon.classList.add("fa-caret-down")
	menuVisible = false
}

function toggleMenu() {
	if (menuVisible)
		hideMenu()
	else
		showMenu()
}

window.addEventListener("load", function () {
	// Hide the submenu if the user clicks anywhere on the page.
	document.addEventListener("click", function (event) {
		if (menuVisible && !menuContainer.contains(event.target))
			hideMenu()
		if (submenu && !submenu.container.contains(event.target)) {
			submenu.hide()
			submenu = null
		}
	})
	initMenu()
})

// end menu

// Start tooltips

let tipped = null
let tipBox = null
let tipContents = null
let tipCleanup = null
let tipArrow = null

function addTooltip() {
	let node = this
	let tip = node.dataset.tip
	if (tipped) {
		let have = tipContents.innerHTML
		tipContents.innerHTML = tip + " | " + have
		return
	}
	tipped = node
	tipContents.innerHTML = tip
	node.classList.add("tipped")
	tipBox.classList.remove("hidden")
	document.body.append(tipBox)
	tipCleanup = floatingUI.autoUpdate(tipped, tipBox, updateTooltipPosition)
}

function setTooltip(node, tip) {
	node.dataset.tip = tip
	if (tipped == node)
		tipContents.innerHTML = tip
}

function updateTooltipPosition() {
	floatingUI.computePosition(tipped, tipBox, {
		placement: "bottom",
		middleware: [
			floatingUI.offset(10),
			floatingUI.flip(),
			floatingUI.shift({padding: 10}),
			floatingUI.arrow({element: tipArrow})
		],
	}).then(({x, y, placement, middlewareData}) => {
		Object.assign(tipBox.style, {
			left: `${x}px`,
			top: `${y}px`,
		})
		const {x: arrowX, y: arrowY} = middlewareData.arrow;
		const staticSide = {
			top: ["bottom", "border-bottom-width", "border-right-width"],
			right: ["left", "border-bottom-width", "border-left-width"],
			bottom: ["top", "border-top-width", "border-left-width"],
			left: ["right", "border-top-width", "border-right-width"],
		}[placement.split("-")[0]]
		Object.assign(tipArrow.style, {
			left: arrowX != null ? `${arrowX}px` : "",
			top: arrowY != null ? `${arrowY}px` : "",
			right: "",
			bottom: "",
			[staticSide[0]]: "-6px",
			["border-width"]: "",
			[staticSide[1]]: "2px",
			[staticSide[2]]: "2px",
		})
	})
}

function removeTooltip() {
	let node = this
	if (node !== tipped)
		return
	tipped.classList.remove("tipped")
	tipBox.classList.add("hidden")
	tipContents.innerHTML = ""
	tipped = null
	tipBox.remove()
	tipCleanup()
	tipCleanup = null
}

function prepareTips() {
	tipBox = document.querySelector("#tip-box")
	tipContents = document.querySelector("#tip-contents")
	tipArrow = document.querySelector("#tip-arrow")
	tipBox.remove()
	for (let node of document.querySelectorAll("[data-tip]")) {
		node.addEventListener("mouseover", addTooltip)
		node.addEventListener("mouseout", removeTooltip)
	}
}

let flashDuration = null

function highlightFragment(node) {
	node.classList.add("flash")
	setTimeout(function () {
		node.classList.remove("flash")
	}, flashDuration)
}

function handleClick(event) {
	// Don't do anything special if the URL points to a different page.
	// We only care about fragments here.
	if (!this.href)
		return
	let url = new URL(this.href)
	if (url.hash.length == 0)
		return
	if (url.origin != window.location.origin)
		return
	if (url.path != window.location.path)
		return
	let target = document.querySelector(url.hash)
	if (!target)
		return
	// If the thing is hidden, make it visible.
	// XXX BUG when making visible collapsible stuff like the apparatus, need to toggle the button accordingly
	let node = target
	while (!node.checkVisibility()) {
		node = node.parentElement
		if (!node)
			break
		node.classList.remove("hidden")
	}
	event.preventDefault()
	target.scrollIntoView()
	highlightFragment(target)
}

function initFlashing() {
	let t = getCSSVar("--flash-duration")
	flashDuration = parseInt(t)
	if (!t.endsWith("ms")) {
		// Assume in seconds
		flashDuration *= 1000
	}
	// Annotate invalid links viz. links that don't have a target. Only do
	// this in the sidebar and in the menu (we use links without href in the
	// menu)
	for (let node of document.querySelectorAll("main a, #sidebar a")) {
		node.addEventListener("click", handleClick)
		if (!node.getAttribute("href"))
			node.classList.add("invalid")
	}
	let frag = window.location.hash
	if (!frag)
		return
	let target = document.querySelector(frag)
	if (!target)
		return
	target.scrollIntoView()
	highlightFragment(target)
}

function popTOCStack(stack, level) {
	while (stack.length >= level) {
		let child = stack.pop()
		let parent = stack[stack.length - 1]
		if (!parent.children)
			parent.children = []
		parent.children.push(child)
	}
}

function makeTOC() {
	let headings = document.body.querySelectorAll("h2, h3, h4, h5, h6")
	let stack = [{"children": []}]
	for (let heading of headings) {
		if (heading.classList.contains("skip-toc"))
			continue
		let level = parseInt(heading.tagName.substring(1))
		popTOCStack(stack, level)
		while (stack.length < level - 1)
			stack.push({})
		stack.push({"heading": heading})
	}
	popTOCStack(stack, 2)
	return stack[0]
}

let idGenerator = 0

function TOCEntryToHTML(entry, root) {
	let li = root || document.createElement("li")
	let heading = entry.heading
	if (heading) {
		let link = document.createElement("a")
		link.classList.add("nav-link")
		let target = heading.getAttribute("id")
		if (!target) {
			idGenerator++
			target = "toc" + idGenerator
			heading.setAttribute("id", target)
		}
		link.setAttribute("href", "#" + target)
		link.innerHTML = heading.innerHTML
		// Prevent the button for collapsing the apparatus from
		// appearing in the TOC in the sidebar.
		icon = link.querySelector("i")
		if (icon)
			icon.remove()
		// Remove footnote markers
		for (let note of link.querySelectorAll("sup > a.nav-link"))
			decompose(note)
		// Remove inner links
		for (let a of link.querySelectorAll("a[href]"))
			unwrap(a)
		li.appendChild(link)
		// TODO do something less stupid
		for (let display of displays) {
			let tmp = document.querySelector("#" + display)
			if (tmp && tmp.contains(heading)) {
				li.dataset.display = display
				if (display == currentDisplay) {
					li.classList.remove("hidden")
				} else {
					li.classList.add("hidden")
				}
			}
		}
	}
	let children = entry.children
	if (children) {
		let ul = document.createElement("ul")
		for (let child of children)
			ul.appendChild(TOCEntryToHTML(child))
		li.appendChild(ul)
	}
	return li
}

function displayTOC() {
	let toc = document.querySelector("#toc-contents")
	if (!toc)
		return
	let root = makeTOC()
	if (root.children.length == 0)
		return
	document.querySelector("#toc-heading").classList.remove("hidden")
	TOCEntryToHTML(root, toc)
}

let displays = ["physical", "logical", "full"]
let currentDisplay = "physical"

function displayButton(name) {
	return document.querySelector("#" + name + "-btn")
}

function switchDisplayTo(name) {
	for (let display of displays) {
		if (display == name) {
			displayButton(display).classList.add("active")
		} else {
			displayButton(display).classList.remove("active")
		}
	}
	for (let node of document.querySelectorAll("[data-display]")) {
		if (node.dataset.display == name) {
			node.classList.remove("hidden")
		} else {
			node.classList.add("hidden")
		}
	}
	currentDisplay = name
}

// Handle clicks on a footnote number in the footnote area at the bottom of the
// page. They should scroll up the page to the footnote mark.
//
// We modify the @href dynamically because, since we have three displays, each
// footnote mark in the edition appears three times. Footnote marks outside of
// the edition have an @id of the form "note-ref-$n", where $n is the footnote
// number; footnote marks within the edition have the form
// "note-ref-$n-$display", where $display is one of "physical", "logical",
// "full".
function handleNoteBackLink(event) {
	let n = this.getAttribute("data-note-n")
	let anchor = "#note-ref-" + n
	let target = document.querySelector(anchor)
	if (!target) {
		anchor += "-" + currentDisplay
		target = document.querySelector(anchor)
		if (!target)
			return
	}
	this.href = anchor
	// And let the next handler deal with scrolling.
}

function initDisplays() {
	for (let name of displays) {
		let button = displayButton(name)
		if (!button)
			continue
		button.addEventListener("click", function (event) {
			switchDisplayTo(name)
			event.preventDefault()
		})
	}
	// And prepare to patch notes backlinks (from the footnote to the
	// text body)
	for (let node of document.querySelectorAll(".note-ref"))
		node.addEventListener("click", handleNoteBackLink)
}

// Localize <time> nodes. The node initially contains the date in the server's
// time zone. We use the same format everywhere, on purpose, for simplicity,
// but we do use the user's local time zone when possible.
function localizeDate(node) {
	console.assert(node.localName == "time" && node.dateTime)
	let when = new Date(node.dateTime)
	let year = when.getFullYear()
	let month = new String(when.getMonth() + 1).padStart(2, "0")
	let day = new String(when.getDate()).padStart(2, "0")
	let hour = new String(when.getHours()).padStart(2, "0")
	let minute = new String(when.getMinutes()).padStart(2, "0")
	node.innerText = `${year}-${month}-${day} ${hour}:${minute}`
}

function localizeDates() {
	for (let node of document.querySelectorAll("time"))
		localizeDate(node)
}

function prepareCollapsible() {
	for (let head of document.querySelectorAll(".collapsible")) {
		// The next sibling should be a div and contain the stuff to
		// make visible or not.
		let content = head.nextElementSibling
		// Add a button after the heading for folding up/down.
		let icon = document.createElement("i")
		icon.classList.add("fa-solid", "fa-angles-down")
		setTooltip(icon, "Fold up")
		head.append(" ", icon)
		// And handle clicks.
		icon.addEventListener("click", function () {
			if (content.classList.toggle("hidden")) {
				icon.classList.remove("fa-angles-down")
				icon.classList.add("fa-angles-up")
				setTooltip(icon, "Fold down")
			} else {
				icon.classList.remove("fa-angles-up")
				icon.classList.add("fa-angles-down")
				setTooltip(icon, "Fold up")
			}
		});
	}
}

function initDisplayOptions() {
	for (let node of document.querySelectorAll(".display-option")) {
		node.addEventListener("change", function () {
			document.querySelector("#xml").classList.toggle(node.name)
		})
	}
	let node = document.querySelector("#toggle-xml-display")
	if (!node)
		return
	node.addEventListener("change", function () {
		let display = document.querySelector("#inscription-display")
		let source = document.querySelector("#inscription-source")
		let toc = document.querySelector("#toc")
		if (display)
			display.classList.toggle("hidden")
		if (source)
			source.classList.toggle("hidden")
		if (toc)
			toc.classList.toggle("hidden")
	})
}

function getConfigInt(key, dflt) {
	let val = localStorage.getItem(key)
	if (!val) {
		val = parseInt(val)
		if (!isNaN(val))
			return val
	}
	return dflt
}

function initNumberedVerses() {
	let minLines = getConfigInt("verses-numbered-min-lines", 5)
	let step = getConfigInt("verses-numbered-step", 5)
	for (let node of document.querySelectorAll(".verse-lines")) {
		let children = node.querySelectorAll(":scope > .verse-line")
		if (children.length < minLines)
			continue
		node.classList.add("verse-lines-numbered")
		for (let i = 1; i <= children.length; i++)
			if (i == 1 || i % step == 0)
				children[i - 1].classList.add("verse-line-numbered")
	}
}

// Initialize event listeners for internal links to prevent conflicts with parent tags.
// This allows specific span elements to behave as links without violating HTML nesting rules.
function initInternalLinks() {
	const internalLinks = document.querySelectorAll('.link')
	internalLinks.forEach(link => {
		link.addEventListener('click', handleInternalLinkClick)
	})
}

// Process the internal link click by stopping event bubbling and redirecting.
// This intercepts the click before the parent anchor tag can trigger its own redirection.
function handleInternalLinkClick(event) {
	event.preventDefault()
	event.stopPropagation()
	const targetUrl = this.getAttribute('data-target')
	if (targetUrl)
		window.location.href = targetUrl
}

window.addEventListener("load", function () {
	localizeDates()
	initNumberedVerses()
	prepareCollapsible()
	prepareTips()
	displayTOC()
	initDisplays()
	initFlashing()
	initDisplayOptions()
	initInternalLinks()
})

document.addEventListener('DOMContentLoaded', function() {
	const facetsForm = document.getElementById('facets-form');
	if (facetsForm) {
		facetsForm.addEventListener('change', function(event) {
			if (event.target.type === 'checkbox') {
				updateSearchResults(facetsForm);
			}
		});
	}
	// Intercept pagination clicks globally using event delegation
	document.addEventListener('click', function(event) {
		if (event.target.classList.contains('pagination-link')) {
			event.preventDefault();
			loadSearchUrl(event.target.href);
		}
	});
});

function loadSearchUrl(url) {
	// Update browser state and trigger the asynchronous DOM replacement
	window.history.replaceState(null, '', url);
	const mainContainer = document.getElementById('search-body');
	mainContainer.style.opacity = '0.5';
	fetch(url)
		.then(response => response.text())
		.then(html => replaceDOMContents(html, mainContainer))
		.catch(err => {
			console.error('Search request failed:', err);
			mainContainer.style.opacity = '1';
		});
}

function updateSearchResults(form) {
	// Gather checked facets and build the complete query string
	const urlParams = new URLSearchParams(window.location.search);
	const facetCategories = ['lang', 'script', 'editor', 'repo'];
	facetCategories.forEach(cat => urlParams.delete(cat));
	urlParams.delete('p');
	const formData = new FormData(form);
	for (const [key, value] of formData.entries()) {
		urlParams.append(key, value);
	}
	loadSearchUrl(window.location.pathname + '?' + urlParams.toString());
}

function replaceDOMContents(html, container) {
	// Extract the main body from the response and inject it into the page
	const parser = new DOMParser();
	const newDoc = parser.parseFromString(html, 'text/html');
	const newBody = newDoc.getElementById('search-body');
	if (newBody) {
		container.innerHTML = newBody.innerHTML;
	}
	container.style.opacity = '1';
	const mainElement = document.querySelector('main');
	if (mainElement) {
		mainElement.scrollTop = 0;
	}
}
