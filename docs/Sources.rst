Flatmap Source Diagrams
=======================

Powerpoint slides
-----------------

* `"kind": "slides"`

SVG diagrams
------------

* `"kind": "base"`
* `"kind": "details"`

Authoring
~~~~~~~~~


A generic SVG editor, such as `Boxy SVG <https://boxy-svg.com/>`_ or `Inkscape <https://inkscape.org/>`_ is the recommended way to create SVG files suitable for use with ``mapmaker``. Adobe Illustrator may be used (see below) although through experience, it has been found to corrupt SVG sources after repeated file saves.


Adobe Illustrator
.................

*   Although native AI format can be used to save files during initial development, ``mapmaker`` is unable to process them because of their proprietary format, and so they must be saved as ``SVG`` before map making.

*   Once in SVG format the diagram should only be opened and saved as SVG, as converting it back to AI format and then resaving as SVG may result in the loss of image fills used in features.

*   The following options should be set when exporting and saving as an SVG::

        Image Location: Embed

        More Options:

            CSS Properties: Presentation Attributes

            Decimal Places: 3

*   To assist with this `scripts/adobe/SaveFlatmap.jsx <https://raw.githubusercontent.com/AnatomicMaps/flatmap-maker/main/scripts/adobe/SaveFlatmap.jsx>`_ can be used (**AI Menu option**). This script can be added to AI's ``File/Scripts`` menu by placing it in .... (**link to AI docs??**).

*   The initial export to SVG may result in additional group elements being added to the diagram, which could then result in ``mapmaker`` processing errors. It's advisable that these be found and fixed before any subsequent work on the diagram. In particular, ``.boundary`` markup on a shape with an image fill will be transferred to a path within a new group element and this path needs to manually moved outside of the new group. A newly exported file in Illustrator will need closing and reopening in order to see these changes.


CellDL diagrams
---------------

* `"kind": "celldl"`

Annotated images
----------------

* `"kind": "image"`
