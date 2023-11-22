.. _manifest-files:

Manifest Files
--------------

The sources of a flatmap are specified using a JSON file, usually called ``manifest.json``.

The manifest is a JSON dictionary that MUST specify:

*   an ``"id"`` for the flatmap.
*   ``"sources"``, giving a list of :ref:`sources <sources>` for the drawings that make up the flatmap.

It MAY optionally have:

*   a taxon identifier for what the flatmap ``"models"``.
*   the ``"biological-sex"`` of what the flatmap represents.
*   a ``"description"`` JSON file specifying a description of the map as a SPARC dataset.
*   the ``"kind"`` of map to generate. Allowable values are ``"anatomical"`` (the default) or
    ``"functional"``.
*   a ``"properties"`` JSON file specifying properties of features.
*   ``"neuronConnectivity"`` specifying SCKAN/NPO :ref:`neuron connectivity models <neuron-connectivity>`
    to render on the flatmap.
*   ``"sckan-version"`` specifying the SCKAN endpoint to get connectivity models from. Allowable
    values are ``"production"`` (the default) or ``"staging"``.
*   for anatomical connectivity maps, an ``"anatomicalMap"`` JSON file assigning anatomical
    identifiers to features. These are additional to any assigned by the ``properties`` file.
*   for functional connectivity maps, an ``"annotation"`` JSON file assigning anatomical terms to
    features based on their label and anatomical type (System, Organ, FTU).
*   a ``"connectivityTerms"`` JSON file specifying equvalences between historical anatomical terms
    used in SCKAN to standard terms (e.g. between FMA and ILX identifiers). **DEPRECATED**
*   a ``"connectivity"`` JSON file specifying manually defined neuron paths. **DEPRECATED**


.. _sources:
Sources
~~~~~~~

Sources are specified as a list of JSON dictionaries. Each ``source`` dictionary that MUST specify:

*   the ``"id"`` of the source.
*   the source ``"kind"``.
*   an ``"href"`` giving the location of the source. If the href is relative then it is with respect to the location of the manifest file.

For anatomical connectivity maps valid source kinds are:

*   ``"slides"`` -- a set of Powerpoint slides, with the first slide being the base map and subsequent slides providing details for features.
*   ``"base"`` -- a SVG file defining a base map.
*   ``"details"`` -- a SVG file providing details for a feature.
*   ``"image"`` -- a segmented MBF Biosciences image file providing details for a feature

An image source MUST also specify:

*   ``"boundary"`` -- the id of an image feature that defines the image's boundary.

For functional connectivity maps valid source kinds are:

*   ``"base"`` -- a Powerpoint file defining a base map.
*   ``"layer"`` -- a Powerpoint file providing a layer over the base map.


.. _neuron-connectivity:
Neuron connectivity
~~~~~~~~~~~~~~~~~~~

Neuron connectivity is specified as a list consisting of a mix of:

*   URLs referencing ApiNATOMY models, optained from the SCKAN endpoint.
*   JSON dictionaries specifing individual neuron paths in an ApiNATOMY model from SCKAN.
*   the keyword ``"NPO"`` to include all connectivity paths from the NPO endpoint.

When a JSON dictionary is used to define neuron connectivity:

*   it MUST specify either the ``"uri"`` of an ApiNATOMY model or the keyword ``"NPO"``.
*   it MAY specify a ``"filter"``, as a JSON dictionary containing three optional lists:

    -   ``"exclude"`` giving neuron path URIs, from the ApiNATOMY model or NPO, to exclude from the map.
    -   ``"include"`` giving neuron path URIs to render on the map.
    -   ``"trace"`` giving neuron path URIs to render and also log information about
        their routing when making the map.


An example
~~~~~~~~~~

.. code-block:: json

    {
        "id": "whole-rat",
        "models": "NCBITaxon:10114",
        "description": "description.json",
        "anatomicalMap": "anatomical_map.json",
        "properties": "properties.json",
        "neuronConnectivity": [
            "https://apinatomy.org/uris/models/keast-bladder",
            "https://apinatomy.org/uris/models/ard-arm-cardiac"
        ],
        "sources": [
            {
                "id": "whole-rat",
                "href": "whole-rat.svg",
                "kind": "base"
            },
            {
                "id": "tissue-slide",
                "href": "tissue-slide.svg",
                "kind": "details"
            },
            {
                "id": "vagus",
                "href": "https://api.sparc.science/s3-resource/64/4/files/derivative/sub-10/sam-1/sub-10_sam-1_P10-1MergeMask.xml",
                "kind": "image",
                "boundary": "http://purl.org/sig/ont/fma/fma5731"
            }
        ]
    }
