============================
Marking up PowerPoint Slides
============================

Map generation is performed by a Python script which processes the shapes in a Powerpoint slide to first create GeoJSON features and then Mapbox vector tiles. The name of a shape is used for mark-up a shape which, together with a separate ``anatomical mapping`` file, is used to annotate and style features, and to control the generation process.


Shapes
------

Statements about shapes on a Powerpoint slide are made using the ``name`` field, accessible from PowerPoint's ``Selection Pane``. Statements are used to specify properties of a feature for map generation, for specifying RDF annotation, and for constructing additional features based on the geometry of a group of shapes.

Statements are identified by the name field having a period (``.``) as the first character, and consist of a white-space separated list of ``directives``.

Directives either have the form ``DIRECTIVE_NAME`` or ``DIRECTIVE_NAME(PARAMETER)``. Valid directives are:

* ``boundary`` -- signifies that the shape will be divided into feature regions by sibling shapes that do not have ``class`` or ``id`` specified. Unless marked as ``invisible`` the sibling shapes will appear in the generated map.
* ``class(CLASS)`` -- the class of the shape, used to find the anatomical style of the generated feature.
* ``id(ID)`` -- a unique identifier for the shape. These are mainly for connection routing but also allow for more specific annotation than that determined by a shape's class.
* ``invisible`` -- the shape does not show in the generated map when dividing a ``boundary`` element into regions.
* ``region`` -- the shape is not shown but instead its properties are applied to the enclosing geometric region obtained by sub-dividing a ``boundary`` shape.
* ``siblings`` -- the shape's ``class`` property is applied to all siblings within the parent group that do not have ``class`` specified.
* ``style(STYLE)`` -- a property that can be used to modify the style of the feature.

.. * ``group`` -- the shape is not shown as a feature but instead a new feature is constructed that is the unary union of all of the parent group's descendant shapes.
.. * ``label(TEXT)`` -- override any label defined for the feature's anatomical entity.
.. * ``layer(ANATOMICAL_ID)`` -- the map source layer the feature is part of. If a layer hasn't been specified then the feature is assigned to a layer called ``composite``.
.. * ``node(N)`` specifies the object to be a ``pointmap``, with ``N`` (``1``, ``2`` or ``3``) giving the node's class.
.. * ``edge(SOURCE_ID, TARGET_ID)`` specifies the object to be an ``edgemap``, with ``SOURCE_ID`` and ``TARGET_ID`` giving the identifiers of the respective source and target nodes.


Groups
------

A PowerPoint slide supports hierarchical grouping of shapes and groups. The group hierarchy as such is ignored when generating a map -- the resulting map's features are a flattened view of the slide's shapes. A group of shapes is only significant for:

* constructing features from a shape and its siblings, using the ``boundary``, ``invisible`` and ``region`` directives.
* assigning a common class using to siblings using the ``sibling`` directive.



.. source/target/via

.. These identifiers may refer to nodes in other map layers, by prefixing them with ``LAYER_ID/``.

.. Do we allow a slide notes field to specify ``layer()``??


.. Or layers from UBERON --> layer map?? ``layers.json``:





Anatomical mapping file
-----------------------

* A JSON file:

.. code-block:: json

    {
        "classes": [
            {
                "class": "CLASS",
                "entity": "ANATOMICAL_ID",
                "label": "FALLBACK_LAYER_TEXT",
                "layer": "LAYER_ID"
            },
            {
                "class": "spinal_1",
                "entity": "UBERON:999"
            }
        ],
        "features": [
            {
                "id": "ID",
                "entity": "ANATOMICAL_ID",
                "label": "FALLBACK_LAYER_TEXT"
            }
        ]
    }


.. note:: An ``ANATOMICAL_ID`` has the form ``PREFIX:SUFFIX`` where ``PREFIX`` specifies an
 ontology and ``SUFFIX`` is specific to the ontology. Valid values for ``PREFIX``
 are ``FMA``, ``ILX``, ``MA``, and ``UBERON``.


.. Parser
.. ------

.. .. automodule:: mapmaker.parser
..    :members: