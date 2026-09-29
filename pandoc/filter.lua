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

function Pandoc(doc)
	-- Check if the output format matches plain text
	if FORMAT:match('plain') then
		local blocks = doc.blocks
		-- Insert title and author paragraphs at the beginning if present
		if doc.meta.title then
			table.insert(blocks, 1, pandoc.Header(1, doc.meta.title))
		end
		if doc.meta.author then
			table.insert(blocks, 2, pandoc.Para(doc.meta.author))
		end
		return pandoc.Pandoc(blocks, doc.meta)
	end
	-- Return unchanged for other formats
	return doc
end
