function Span(el)
	local color = el.attributes['color']
	if color then
		if FORMAT:match('latex') then
			-- Wrap content in LaTeX textcolor command
			local start_cmd = {pandoc.RawInline('latex', '\\textcolor{' .. color .. '}{')}
			local end_cmd = {pandoc.RawInline('latex', '}')}
			table.insert(el.content, 1, start_cmd[1])
			table.insert(el.content, end_cmd[1])
			el.attributes['color'] = nil
		elseif FORMAT:match('html') then
			-- Convert to CSS style for HTML
			el.attributes['style'] = 'color: ' .. color .. ';'
			el.attributes['color'] = nil
		elseif FORMAT:match('docx') or FORMAT:match('odt') then
			-- Use inline CSS-like style which Pandoc writers for docx/odt can interpret
			el.attributes['style'] = 'color: ' .. color
			-- We keep the color attribute if specific writers need it as fallback
		end
	end
	return el
end
