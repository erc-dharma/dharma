% extends "base.tpl"

% block title
Search Help
% endblock

% block body
<p>The query syntax is similar to most search engine’s.</p>
<p>For searching in all fields:</p>
<pre><code>temple</code></pre>
<p>For searching a phrase:</p>
<pre><code>&quot;Aihole temple&quot;</code></pre>
<p>Quotation marks are necessary, otherwise the query would be treated
as:</p>
<pre><code>Aihole AND temple</code></pre>
<p>For searching in a specific field:</p>
<pre><code>title:temple
title:&quot;Aihole temple&quot;
title:(Aihole AND temple)</code></pre>
<p>Available boolean operators are <code>AND</code>, <code>OR</code>,
and <code>NOT</code>. Examples:</p>
<pre><code>Aihole AND temple
Aihole OR temple
temple NOT Aihole</code></pre>
<p>In our system, <code>NOT</code> is a unary operator, not a binary
one. The following is thus valid:</p>
<pre><code>NOT Aihole</code></pre>
% endblock
