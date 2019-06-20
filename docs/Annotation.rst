============================
Annotating Powerpoint Slides
============================


Statements about objects on a slide
-----------------------------------

Statements about objects on a Powerpoint slide are made using the object's ``name`` field, which is set via Powerpoint's ``Selection Pane`` (the Selection Pane can be found in the ``Arrange`` menu of the ``Home`` tab).

Two different types of statements are recognised:

1) The ``name`` starts with a ``.`` (period) character.

    These are ``directive`` statements.

    Only one directive statement is currently recognised, ``.layer-id(ID)``, which if used, must be the name of a text box. This assigns an identifier to the slide (i.e. the map layer). The content of the text box becomes the layer's description. Identifiers must be unique over the entire map. Only a single ``layer-id`` can be set in a slide; if there isn't one then the layer's id is set to ``layer-NN``, where ``NN`` is the slide's number in the presentation.

2) The ``name`` starts with a ``#`` (hash) character.

    These are ``annotation`` statements, used to generate RDF annotation.

    An annotation statement always starts by specifying an identifier for the object, in the form ``#OBJECT_ID``, followed by an optional list of whitespace separated ``commands``. An object's id must be unique within the slide or map layer.

    Each command has the form ``NAME(PARAMETERS)``.

    The following annotation commands are recognised:

    * ``models(UBERON:ID)`` (or ``FMA:ID``)
    * ``node(N)`` specifies the object to be a ``pointmap``, with ``N`` (``1``, ``2`` or ``3``) giving the node's class.
    * ``edge(SOURCE_ID, TARGET_ID)`` specifies the object to be an ``edgemap``, with ``SOURCE_ID`` and ``TARGET_ID`` giving the identifiers of the respective source and target nodes. These identifiers may refer to nodes in other map layers, by prefixing them with ``LAYER_ID/``.
