.. highlight:: sh

Overview
--------

Mapmaker is a Python application for generating `Mapbox <https://www.mapbox.com/>`_ compatible tilesets from a range of sources, currently Powerpoint slides, SVG diagrams, and segmented image files from MBF Biosciences.

Documentation
-------------

* https://flatmap-maker.readthedocs.io/en/devel/.

Requirements
------------

* Python 3.8.
* `Tippecanoe <https://github.com/mapbox/tippecanoe#installation>`_.
* `COIN-OR CBC solver <https://github.com/coin-or/Cbc#binaries>`_.

Installation
------------

It is recommended to install and run ``mapmaker`` in its own Python virtual environment. Instructions for using `pipenv <https://pipenv.pypa.io/en/latest/#install-pipenv-today>`_ are given below, although any other virtual environment and package manager may be used instead.

* Create and activate a Python virtual environment in which to install ``mapmaker``.

* Within this environment, install the latest ``mapmaker`` wheel from https://github.com/dbrnz/flatmap-maker/releases/latest (currently ``mapmaker-1.4.1a2-py3-none-any.whl``).

Using pipenv
~~~~~~~~~~~~

* Create a directory in which to run ``mapmaker`` and change into it.

* Install ``mapmaker`` directly from GitHub with::

    $ pipenv install --python 3.8 https://github.com/dbrnz/flatmap-maker/releases/download/v1.4.1a2/mapmaker-1.4.1a2-py3-none-any.whl


Development
-----------

``mapmaker`` uses `poetry <https://python-poetry.org/docs/#installation>`_ for dependency management and packaging. To create a development environment:

* Clone this repository.
* Run ``$ poetry install`` in the top-level directory of the cloned repository.

Building documentation
~~~~~~~~~~~~~~~~~~~~~~

In development mode, and within the Python virtual environment::

    $ cd docs
    $ make html

Running
-------

* ``mapmaker`` must be run within its Python virtual environment. For instance, first run ``$ pipenv shell`` when using ``pipenv``.
* `SciCrunch <https://scicrunch.org/>`_ is used to lookup attributes (e.g. labels) of anatomical entities. In order to use these services a valid SciCrunch API key must be provided as the ``SCICRUNCH_API_KEY`` environment variable. (Keys are obtained by registering as a SciCrunch user).

Command line help
~~~~~~~~~~~~~~~~~

::

    $ mapmaker --help

.. code-block:: text

    usage: mapmaker [-h] [-v]
                    [--log LOG_FILE] [--show-deprecated] [--silent] [--verbose]
                    [--clean] [--background-tiles]
                    [--check-errors] [--debug] [--save-drawml] [--save-geojson] [--tippecanoe]
                    [--initialZoom N] [--max-zoom N] [--min-zoom N]
                    [--id ID] [--single-svg]
                    --output OUTPUT --source SOURCE

    Generate a flatmap from its source manifest.

    optional arguments:
      -h, --help            show this help message and exit
      -v, --version         show program's version number and exit

    Logging:
      --log LOG_FILE        append messages to a log file
      --show-deprecated     issue a warning for deprecated markup properties
      --silent              suppress all messages to screen
      --verbose             show progress bars

    Image tiling:
      --clean               Remove all files from generated map's directory before generating new map
      --background-tiles    generate image tiles of map's layers (may take a while...)

    Diagnostics:
      --check-errors        check for errors without generating a map
      --debug               show a traceback for error exceptions
      --save-drawml         save a slide's DrawML for debugging
      --save-geojson        Save GeoJSON files for each layer
      --tippecanoe          Show command used to run Tippecanoe

    Zoom level:
      --initialZoom N       initial zoom level (defaults to 4)
      --max-zoom N          maximum zoom level (defaults to 10)
      --min-zoom N          minimum zoom level (defaults to 2)

    miscellaneous:
      --id ID               Set explicit ID for flatmap, overriding manifest
      --single-svg          Source is a single SVG file, not a flatmap manifest

    Required arguments:
      --output OUTPUT       base directory for generated flatmaps
      --source SOURCE       URL or path of a flatmap manifest

An example run
~~~~~~~~~~~~~~

::

    $ mapmaker --output ./flatmaps --source ../PMR/rat --verbose

.. code-block:: text

    Mapmaker 1.4.1a2
    100%|█████████████████████████▉| 678/679
     98%|███████████████████████████▌| 65/66
    Adding details...
    Outputting GeoJson features...
    Layer: whole-rat
    100%|████████████████████████| 2477/2477
    Layer: whole-rat_details
    100%|██████████████████████████| 180/180
    Running tippecanoe...
    2657 features, 6439698 bytes of geometry, 25397 bytes of separate metadata, 485295 bytes of string pool
      99.9%  10/528/531
    Creating index and style files...
    Generated map for NCBITaxon:10114


Manifest files
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


Anatomical map file
-------------------

TODO...

Properties file
---------------

TODO...


Shape markup
------------

TODO...
