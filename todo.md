# TODO

regarder https://dharmalekha.info/errors/DHARMA_INSSIIv04p0i0433, qui n'a pas d'erreur.

===

INSTamilOutsideTN10002: supprimer distinction entre langue source/traduction;
	il faut ignorer au moins "head" et "note" pour la distribution des
	langues.

mettre en gras tous les @rendition=grantha

pour e.g. INSIIv04p0i0433; ne pas mettre en gras les parenthèses, les chevrons,
les accolades, etc., les points d'interrogation et d'exclamation, bref tous les
caractères qu'on ajoute.

arie: fichiers publics
arie-corpus: fichiers privés
tout mettre dans le même dépot et tout afficher

pour bestow, pour chaque traduction, ajouter l'auteur de la traduction (support
<div type="translation" source="bib:Hultzsch1895_01">).

support assignment of languages in DHARMA_CritEd* et DHARMA_DiplEd*.

---

need to deal properly with creation/deletion of repos. the only input parameter
should be the repos file. add a routine for this in change.py

should add extra commands to change.py to do more granular updates. because, at
startup, we start with project-documentation and thus reindex the whole catalog only to then update each repo again. we should skip the whole catalog reindexing at startup (and only in this circumstance.)

---

Il faut couvrir tous les sections principales avec des div, pour éviter qu'il y ait un mix de para et de div a un même niveau, et idem recursivement. On devrait avoir des div phantom pour toutes les div type édition, translation, etc., de telle sorte que toutes ces sections principales contiennent au moins une div (ainsi on pourra plus facilement calculer la taille d'une div, etc.)

Dans la repr interne, Il faudrait éviter de hardcoder les noms des div (édition, translation, etc.), plus encore si on n'a pas besoin de savoir ce qu'elles contiennent. Parce que c'est chiant dans le code qui les parse, et parce qu'on doit prendre en charge d'autres types de div pour également bestow. il vaudrait. Mieux avoir seulement div comme élément.



Ajuster dispositif n des milesyones en fonction de remplissage par para et verse-line éléments.

Permettre les div imbriquées, et vérifier que les résultats est le bon. Autoriser tous types de div, pas seulement text part.

On devrait avoir des lignes fantômes pour le physical aussi, dans la recherche.



---

XXX do commit several times (or maybe savepoint+release) when rebuilding the
catalog.

abrévier le summary dans tableau résultat à un seul <p> (ajouter [...] à la place des restants)

## internal repr

must allow (at least) <verse> within a <quote>. but note that for milestones we
assume there is no overlap.

DHARMA_INSCIC00137

<quote>
            <verse>
                <verse-line break="true">āsādya <!--space-->
                    <span class="bold">śaktiṁ</span><!--space--> vivudhopanītāṁ māheśvarīṁ jñānamayīm amoghām</verse-line>
                <verse-line break="true">
                    <span class="bold">kumāra</span>bhāve vijit<span class="bold">āri</span>varggo yo dīpayām āsa mahendralakṣmīm ||</verse-line>
            </verse>After attaining the Power (or: weapon) of Maheśvara (Śiva) that consists in Knowledge, that is never failing (viz. after attaining initiation) [and that has been] transmitted by the gods, being in youth (or: as crown-prince, or: as Kumāra, i.e. Skanda) one whose enemies (or: passions) were conquered, he caused the glory of Mahendravarman to shine.</quote>



## Misc

ultimately, we should remove the bs4 dependency, but for this we need a HTML
parser _and also_ a serialization method that does the appropriate thing for
self-closing tags.

## XML Schema

should do an autoreplace from my code to the xml schema; for at least:

- prosody @met
- people; the "part:xxxx" stuff
- language codes @lang
- script age + maturity @rendition
- and for bib:xxx, we could perform http requests in schematron, but might be too slow

for this we need to access the app's repo. can either do the transform within the app's repo; or within project-documentation.


## Database

Need to have some locking logic when reading from a github repo. For when we
want to do manual maintenance while the app is running.

Need to make sure that all the files we need for display, etc., are stored in
the db. Currently, this is not the case. Not easy to guarantee. unless we have a
reliable access method. Should have a unique mechanism for storing files.

[after we're done with the catalog]. in the db, stop using "und" as default for languages that don't have one, we should have an empty array in such cases. the "empty" value for everything should be null. and also hide "Language: Undetermined" when no language found in div type edition. be careful that we are using languages in search.

¶ need a protocol for bootstrapping the db.

¶ support adding/deleting/renaming repos; should have a single entry point for
this. and should document it somewhere.

	delete from repos where repo='repo-test';
	delete from files where repo='repo-test';
	delete from documents where repo='repo-test';
	delete from documents_index where repo='repo-test'; **but lowercasing!**

should probably use triggers for dealing with this. need to remove all files related to a repo.

find a way to merge the parallels db with the main one; it should be updated
every week or so


## Arlo

transfo des éditions critiques


## Manu

Pour les unités dans la bibliographie, utiliser explicitement le singulier et le pluriel ? `<citedRange unit="page|pages">`. Manu et moi sommes pour, Arlo et Daniel pas vraiment.

Pour le display des metadata, Manu voudrait ceci. metadata: short display: langue, écriture, date, summary; long display: avoir un bouton pour afficher les métadonnées au complet.

Bouton de translittération à ajouter pour le tamoul

Pour le copier/coller sous Word, fonctionne pas très bien pour Manu (plutôt que d'utiliser des classes, il faut employer des éléments `<b>`, etc.)

in biblio, move sharedocs links to notes; requires to have
* a mechanism for updating the biblio
* a mechanism for adding notes and linking them to an existing entry

attr to `<p>` for marking up blessings/curses? @ana? find something generic for
all custom stuff (additions to the egd).

prosodic patterns; be careful about placemenbt of guillemets and footnote nums.

manu: pour le display des métadonnées, avoir un bouton expand/unexpand comme pour l'apparat
commencer à réfléchir à la faceted search.


## ODD schema

need to fix the datatype mess in rng schema; distinguish between attrs that
accept a single value and the others.

deal with div with @rendition class:grantha, should be put in bold. need first
to deal with

=================

elements that can be ignored and should be removed eventually:

prefixDef, listPrefixDef, schemaRef
but first verify that nothing depends on them in xslt files
and also make sure they do not appear in templates

//TEI/teiHeader/fileDesc/publicationStmt
//TEI/teiHeader/fileDesc/sourceDesc/msDesc/msIdentifier
//TEI/teiHeader/encodingDesc
//TEI/teiHeader/revisionDesc

revisionDesc can always be ignored

=================

pour languages dans display, tous ceux de div type=edition + écrfiture
écritures à gérer
"Tamil in Tamil Script; Sanskrit in Grnatha script":


## Parsing

We must do NFC normalization at some point; when? not before storing the
file in the db (might need the original later on for e.g. hashing); simplest
would be to do that just before parsing the file, but this will mess up
columns numbers. still should do it, because we don't refer to columns for
now and because all string comparisons will be messed up. do the final
normalization step (new lines, etc.) when outputting documents.

OTOH, we shouldn't do anything with column numbers. This is too inconvenient.
Idem for byte offsets.


## Refactoring

shouldn't store separately the app from all the data files, because we need the
data files to be present to do anything with the db. the app code is useless
on its own. add projdoc as a submodule? can we still do a git pull in the app
repo without having git complain that the repo has been modified?
everything should be in the same repo. maybe use a reload command that reloads
data files _but not the code_?

in fact we have 2 build levels: fetch files from the fs, and parse the
documents. should do the minimum whenever possible.


## Validation

Script maturity is for use only with the class "Brahmi and derivatives" (and
its subcategories); for any other script classes it is not optional but
"forbidden". For Brahmi, it is mandatory. Amend rules accordingly.

deal with uniqueness of phys elements:
* pb and pagelike milestones must have unique @n in the whole div/edition

Check for multiple uses of the same bib entry as in https://dharman.in/display/DHARMA_INSBengalCharters00050#bibliography (disallow?)

actually use dharma.rng, only in /texts for now, afterwards distribute it;


## Display

Parse urls and make them clickable.

Some stuff to implement in the display of the apparatus: https://github.com/erc-dharma/project-documentation/issues/282#issuecomment-2444650894

for invalid inscriptions, show the xml, but without formatting tags, etc.
need to convert the error (line,column) to an offset
use xmlparser.ErrorByteIndex instead of donig a manual conversion
https://docs.python.org/3/library/pyexpat.html

deal with rendition and xml:lang, which must cover the whole text in div type edition.
must be dealt with in tree.py

manu: In physical display, do not display editorial hyphens, but do show them
in logical display. For this to work, need to tag languages. XXX
hyphens between words? or at the end fo a line?

manu: grantha translit with button several states translit methods

* Sort out languages tagging; assign language categories (lang of
	the ed. or of the rest, main or secondary lang; probably not
	useful to keep track of `<foreign>`)

add tooltip for expan in `<abbr><expan>` in phys disp; but need to know how to do
that

div rendition="class:38768 maturity:83213" (grantha) à mettre en gras pas seulement hi rend=grantha ; pour SII0501358
idem pour `<lg rendition=...>` dans Tiruvavatuturai01

don't think we are formarring abbr/expan as supposed

should use the lang attribute in html to tag appropriately xml elements
with an @xml:lang.


## Problems with @n.

The repetitive scheme is not clear and unpredictable. Should have a clearer
convention.


## XML source display

Put the tab button in the sidebar, call it "view source". Should allow resizing
the sidebar, too. when it is completemy closed, what to display?

* when displaying the sidebar, add toc headings for navigating the xml: header,
	edition, translation, etc.
* Need to have a pretty-print func that preserves space and
	doesn't add unnecessary space.
* Also add line numbers
* Style the thing with a color for comments and tags, maybe different colors
	for milestones and logical elements.
* Add error messages with popups in the XML.


## Website

in the "texts errors" page, have a column with the severity level

for https://github.com/erc-dharma/project-documentation/issues/266#issue-2207593274
don't use href in in-page links, it's confusing; use data-href instead; and this
would allow us to distinguish page-internal links from the others.

when a file is completely invalid, show the raw xml in the displqay (not pretty-printed).

do a redirect /foo/ -> /foo in nginx _but_ watch out with the /zotero-proxy
stuff.

deal with elem flashing:
cumulative timeout for flashing https://developer.mozilla.org/fr/docs/Web/API/setTimeout
repr here https://stackoverflow.com/questions/29017379/how-to-make-fadeout-effect-with-pure-javascript

Make the top menu sticky on pc? no. Add a button to show/hide the left sidebar (on
pc); where? left of the top menu downward-pointing > thing. The left sidebar
shouldn't pop when we arrive to the page footer, how? The left sidebard should
be resizable, but then dimensions need to be saved as a cookie because reloading
the page will mess up the size.

Generate a site map (wget?).

Use the w3c validator API https://validator.w3.org/docs/api.html with random
urls to detect issues; submit URLs like so:

	https://validator.w3.org/nu/?out=json&doc=$URL

Add a "status" search field to catalog to filter by error status.

add global table of gaiji symbols actually found in inscriptions.
we will add links to inscriptions within this table so that we can find which
inscriptions, etc. contain which symbols.


## Parallels

Allow quoting part of the input with "..." to force an exact substring match.
Still keep using the same similarity measure. When there are several quoted
passages, allow overlaps viz. "foo"f"fo" match "foo". Or not? require the
matched strings to occur in the same order? In fact having a second field for
filtering seems better.

This should be linked to the catalog search features, but we must first
integrate with the main db.


## Duplicate file idents and zotero idents

would be convenient to have position-independent files, viz. assume file
basenames are unique AND also extension-independent files, to allow people to
move files around.

find some way to report non unique files ; could use an intermediate table that
stores duplicates, like for zotero; for duplicate files in the same repo, we are
sure there is a problem and we can complain early on while processing the repo
itself (to whom, however?), but we don't need to do it early; but if the files
are in distinct repos, we cannot tell whether the file is being moved or
anything, because there is no global commit across all repos and the order of
operations is not guaranteed.

in any case, we must preserve the fact that a given ident always corresponds to
exactly one elem; so if we have a duplicate ident, do not use this
duplicate ident, instead generate new ones and delete these when appropriate.

