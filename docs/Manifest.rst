.. _manifest-files:

Manifest Files
--------------

The sources of a flatmap are specified using a JSON file, usually called ``manifest.json``.

The manifest is a JSON dictionary that MUST specify:

* an ``id`` for the flatmap.
* a list of ``sources``.

It MAY optionally specify:

* a taxon identifier specifying what the flatmap ``models``.
* a ``properties`` JSON file specifying properties of features.
* a ``description`` JSON file specifying a description of the map as a SPARC dataset.
* an ``anatomicalMap`` JSON file assigning anatomical identifiers to features.
* The map's ``neuronConnectivity`` as a list of URLs, each specifying a SCKAN connectivity model.

A source is a JSON dictionary that MUST specify:

* the ``id`` of the source.
* the source ``kind``.
* an ``href`` giving the location of the source. If the href is relative then it is with respect to the location of the manifest file.

Valid source kinds are:

* ``slides`` -- a set of Powerpoint slides, with the first slide being the base map and subsequent slides providing details for features.
* ``base`` -- a SVG file defining a base map.
* ``details`` -- a SVG file providing details for a feature.
* ``image`` -- a segmented MBF Biosciences image file providing details for a feature

An image source MUST also specify:

* ``boundary`` -- the id of an image feature that defines the image's boundary.

For example:

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

.. note::
    Extend to include latest updates to manifest.

