```{=html}
% extends "base.tpl"

% block title
Search Help
% endblock

% block body
```

The query syntax is similar to most search engine's.

For searching in all fields:

```
temple
```

For searching a phrase:

```
"Aihole temple"
```

Quotation marks are necessary, otherwise the query would be treated as:

```
Aihole AND temple
```

For searching in a specific field:

```
title:temple
title:"Aihole temple"
title:(Aihole AND temple)
```

Available boolean operators are `AND`, `OR`, and `NOT`. Examples:

```
Aihole AND temple
Aihole OR temple
temple NOT Aihole
```

In our system, `NOT` is a unary operator, not a binary one. The following is thus valid:

```
NOT Aihole
```

```{=html}
% endblock
```
