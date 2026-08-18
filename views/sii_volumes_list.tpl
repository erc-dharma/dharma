% extends "base.tpl"

% block title
South Indian Inscriptions
% endblock

% block body
<ul>
% for vol, part, url in volumes:
<li>
	<a href="/south-indian-inscriptions/{{url}}">
% if part:
	Vol. {{vol}}, part {{part}}
% else:
	Vol. {{vol}}
% endif
	</a>
</li>
% endfor
</ul>
% endblock
