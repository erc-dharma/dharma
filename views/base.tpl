<!doctype html>
<html lang="en">
<head>
   <meta charset="utf-8">
   <meta name="viewport" content="width=device-width, initial-scale=1">
   <title>{{self.title() | striptags}} - DHARMA</title>
   <!-- We have ?v={{code_hash}} in links below to force assets to be
   reloaded by web browsers. -->
   <link rel="stylesheet" href="/fonts.css?v={{code_hash}}">
   <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
   <link rel="stylesheet" href="/base.css?v={{code_hash}}">
   <link rel="icon" href="/favicon.svg">
   <script src="https://cdn.jsdelivr.net/npm/@floating-ui/core@1.6.0"></script>
   <script src="https://cdn.jsdelivr.net/npm/@floating-ui/dom@1.6.3"></script>
   <script src="/base.js?v={{code_hash}}"></script>
</head>
<body>
% if no_sidebar:
<div id="contents" class="no-sidebar">
% else:
<div id="contents">
% endif
<header>
   <div id="menu-bar">
<a id="dharma-logo" href="/"><img alt="DHARMA Logo" src="/dharma_bar_logo.svg"></a>
<a id="menu-toggle"><i class="fa-solid fa-caret-down fa-fw"></i></a>
<ul id="menu" class="hidden">
   <li class="submenu">
      <a href="#">About <i class="fa-solid fa-caret-down"></i></a>
      <ul class="hidden">
         <li><a href="/about">About this resource and the DHARMA project</a></li>
         <li><a href="/documentation">Documentation</a></li>
         <li><a href="/contributors">Contributors</a></li>
         <li><a href="/repositories">Repositories</a></li>
         <li><a href="/languages">Languages</a></li>
         <li><a href="/scripts">Scripts</a></li>
      </ul>
   </li>

   <li>
      <a href="/search">Search</a>
   </li>

   <li class="submenu">
      <a href="#">Conventions <i class="fa-solid fa-caret-down"></i></a>
      <ul class="hidden">
         <li><a href="/editorial-conventions">Editorial Conventions</a></li>
         <li><a href="/prosody">Prosodic Patterns</a></li>
         <li><a href="/glyphs">Glyph Taxonomy</a></li>
      </ul>
   </li>

   <li class="submenu">
      <a href="#">Resources <i class="fa-solid fa-caret-down"></i></a>
      <ul class="hidden">
         <li><a href="/bestow">Benedictory and Exhortative Sanskrit Stanzas</a></li>
         <li><a href="https://erc-dharma.github.io/arie">Annual Reports on Indian Epigraphy</a></li>
         <li><a href="https://erc-dharma.github.io/tfb-ec-epigraphy/">Epigraphia Carnatica</a></li>
         <li><a href="https://erc-dharma.github.io/output-roej/display-roej.html">Répertoire onomastique Java</a></li>
         <li><a href="https://erc-dharma.github.io/tfa-sii-epigraphy/index-sii.html">South Indian Inscriptions</a></li>
         <li><a href="/development-of-tamil-fractions">Development of Tamil Fractions</a></li>
         <li><a href="/chola-fractional-calculations">Chola Fractional Calculations</a></li>
      </ul>
   </li>

   <li class="submenu">
      <a href="#">Internal <i class="fa-solid fa-caret-down"></i></a>
      <ul class="hidden">
         <li><a href="/bibliography-errors">Bibliography errors</a></li>
         <li><a href="/texts-errors">Texts errors</a></li>
         <li><a href="/parallels">Parallels</a></li>
      </ul>
   </li>
</ul>
   </div>
</header>
<div id="sidebar">
   <button id="mobile-close-filter-btn" class="mobile-only">
      <i class="fa-solid fa-xmark"></i> <i class="fa-solid fa-filter"></i> Filter
   </button>
   <div id="toc">
      <div id="toc-heading" class="toc-heading hidden">Contents</div>
      <nav id="toc-contents"></nav>
   </div>
   % block sidebar
   % endblock
</div>
<main>
<h1>
% block title
Untitled
% endblock
</h1>
% block body
% endblock
</main>
</div>
<div id="tip-box" class="hidden">
   <div id="tip-contents"></div>
   <div id="tip-arrow"></div>
</div>
</body>
</html>
