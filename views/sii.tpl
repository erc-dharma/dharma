% extends "base.tpl"

% block title
{{title.html() | safe}}
% endblock

% block body
{{body.html() | safe}}
% endblock

% block sidebar
<div class="toc-heading">Contents</div>
<nav>
<ul>
% for ident in bookmarks:
<li><a href="#{{ident}}">{{ident}}</a></li>
% endfor
</ul>
</nav>
% endblock
