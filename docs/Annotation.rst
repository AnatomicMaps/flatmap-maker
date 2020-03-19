============================
Marking up PowerPoint Slides
============================

Map generation is performed by a Python script which extracts and processes the shapes in a Powerpoint slide to first create a set of GeoJSON features and then (from the GeoJSON), Mapbox vector tiles. Shapes are marked up with statements which, together with a separate ``anatomical style`` file, are used to annotate and style generated features, as well as to control the generation process.


Shapes
------

Statements about shapes on a Powerpoint slide are made using the shapes's ``name`` field, which can be changed in PowerPoint's ``Selection Pane`` (the Selection Pane can be found under the ``Arrange`` menu of the ``Home`` tab). Statements are used to specify properties of a feature for map generation, for specifying RDF annotation, and for constructing additional features based on the geometry of a group of shapes.

Statements are identified by the name field having a period (``.``) as the first character, and consist of a white-space separated list of ``directives``.

Directives either have the form ``DIRECTIVE_NAME`` or ``DIRECTIVE_NAME(PARAMETER)``. Valid directives are:

* ``class(CLASS)`` -- the class of the shape, used to find the anatomical style of the generated feature.
* ``id(ID)`` -- a unique identifier for the shape. These are mainly for connection routing but also allow for more specific annotation than that determined by a shape's class.
* ``style(STYLE)`` -- a property that can be used to modify the style of a feature.

.. * ``label(TEXT)`` -- use thioverride any label defined for the feature's anatomical entity.
.. * ``layer(ANATOMICAL_ID)`` -- the map source layer the feature is part of. If a layer hasn't been specified then the feature is assigned to a layer called ``composite``.
.. * ``node(N)`` specifies the object to be a ``pointmap``, with ``N`` (``1``, ``2`` or ``3``) giving the node's class.
.. * ``edge(SOURCE_ID, TARGET_ID)`` specifies the object to be an ``edgemap``, with ``SOURCE_ID`` and ``TARGET_ID`` giving the identifiers of the respective source and target nodes.


Commands operate within a Powerpoint group and are for constructing and annotating features based on those contained in the group. Valid commands are:

* ``boundary`` -- signifies that the feature will be divided into regions by its sibling un-annotated shapes.
* ``children`` -- the feature is not shown but instead its properties are applied to its siblings within the parent group, and for ``layer`` for all descendants of the group.
* ``invisible``
* ``group`` -- the feature is not shown but instead a new feature is constructed that is the unary union of all of the parent group's descendant features.
* ``region`` -- the feature is not shown but instead its properties are applied to the enclosing geometric region obtained by sub-dividing a ``boundary`` feature.

.. source/target/via

.. These identifiers may refer to nodes in other map layers, by prefixing them with ``LAYER_ID/``.

.. Do we allow a slide notes field to specify ``layer()``??


Or layers from UBERON --> layer map?? ``layers.json``:

.. code-block:: json

    {
        "layers": ["UBERON:1", "UBERON:99"]
    }



Anatomical style file
---------------------

* JSON

.. code-block:: json

    {
        "classes": [
            {
                "class": "CLASS",
                "entity": "ONTOLOGY_ID",
                "label": "FALLBACK_LAYER_TEXT",
                "layer": "LAYER_ID"
            }
        ],
        "features": [
            {
                "id": "ID",
                "entity": "ONTOLOGY_ID",
                "label": "FALLBACK_LAYER_TEXT"
            }
        ]
    }


.. note:: An ``ANATOMICAL_ID`` has the form ``PREFIX:SUFFIX`` where ``PREFIX`` specifies an
 ontology and ``SUFFIX`` is specific to the ontology. Valid values for ``PREFIX``
 are ``ABI``, ``FMA``, ``ILX``, ``MA``, and ``UBERON``.


Parser
------

.. automodule:: mapmaker.parser
    :members: