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

function Header(el)
	-- Reformat headings to look like Markdown when the output is plain text
	if FORMAT:match('plain') then
		-- Generate a string of hashes matching the heading level + 1 followed by a space
		local prefix = string.rep("#", el.level + 1) .. " "
		table.insert(el.content, 1, pandoc.Str(prefix))
		-- Return as a regular paragraph so the plain writer does not alter our text formatting
		return pandoc.Para(el.content)
	end
	return el
end

function Pandoc(doc)
	-- Check if the output format matches plain text
	if FORMAT:match('plain') then
		local blocks = doc.blocks
		-- Construct the title paragraph with a single hash prefix to ensure it remains level 1
		if doc.meta.title then
			local title_content = { pandoc.Str("# ") }
			for _, inline in ipairs(doc.meta.title) do
				table.insert(title_content, inline)
			end
			table.insert(blocks, 1, pandoc.Para(title_content))
		end
		-- Insert the author metadata as the second paragraph
		if doc.meta.author then
			table.insert(blocks, 2, pandoc.Para(doc.meta.author))
		end
		return pandoc.Pandoc(blocks, doc.meta)
	end
	-- Return unchanged for other formats
	return doc
end
