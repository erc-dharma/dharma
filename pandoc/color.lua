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
		elseif FORMAT:match('docx') or FORMAT:match('odt') then
			-- Format the color string to construct the style name
			local formatted_color = color:gsub("^%l", string.upper)
			-- Apply the custom-style attribute for Word processing
			el.attributes['custom-style'] = 'Color' .. formatted_color
			el.attributes['color'] = nil
		end
	end
	return el
end
