.. highlight:: sh

========
Mapmaker
========

Overview
--------

Mapmaker is a Python application for generating `Mapbox <https://www.mapbox.com/>`_ compatible tilesets from
a range of sources, currently Powerpoint slides, SVG diagrams, and segmented image files from MBF Biosciences.

Documentation
-------------

* https://flatmap-maker.readthedocs.io/en/v1.5-release/

Installation
------------

We recommend that ``mapmaker`` is run in a Conda environment on a Linux or macOS system. This includes
`Windows Subsystem for Linux <https://learn.microsoft.com/en-us/windows/wsl/install>`_ (WSL) for Microsoft
Windows systems.

Prerequisites
~~~~~~~~~~~~~
Install a ``miniforge`` environment as descibed `here <https://github.com/conda-forge/miniforge>`_.

macOS
^^^^^

Apple macOS users may first have to install the ``XCode command line tools``. Check if the command line tools are installed by running::

    $  xcode-select -p

and if they are not, install them by running::

    $ xcode-select --install


Installation
~~~~~~~~~~~~

*   Use ``git`` to clone the latest release branch::

    $ git clone https://github.com/AnatomicMaps/flatmap-maker/tree/v1.5-release mapmaker


*   Install mapmaker's dependenies using Conda::

    $ cd mapmaker
    $ conda env create -f envs/mapmaker.yaml


Running
-------

*   Activate ``mapmaker``'s Conda environment::

    $ conda activate mapmaker

*   Run::

    $ python runmaker.py ARGUMENTS


*   `SciCrunch <https://scicrunch.org/>`_ is used to lookup attributes (e.g. labels) of anatomical entities. In order
    to use these services a valid SciCrunch API key must be provided as the ``SCICRUNCH_API_KEY`` environment variable.
    (Keys are obtained by registering as a SciCrunch user).


Updating
--------

From the checked-out directory and with the Conda environment active::

    $  git pull
    $  conda env update -f envs/mapmaker.yaml


Command line help
-----------------

::

    $ python runmaker.py --help

.. code-block:: text

    usage: mapmaker [-h] [-v]
                    [--log LOG_FILE] [--show-deprecated] [--silent] [--verbose]
                    [--clean] [--background-tiles] [--show-centrelines]
                    [--authoring] [--debug] [--only-networks]
                    [--save-drawml] [--save-geojson] [--tippecanoe]
                    [--initial-zoom N] [--max-zoom N] [--min-zoom N]
                    [--clean-connectivity] [--id ID] [--single-file {celldl,svg}]
                    --output OUTPUT --source SOURCE

    Generate a flatmap from its source manifest.

    options:
      -h, --help            show this help message and exit
      -v, --version         show program's version number and exit

    Logging:
      --log LOG_FILE        Append messages to a log file
      --show-deprecated     Issue a warning for deprecated markup properties
      --silent              Suppress all messages to screen
      --verbose             Show progress bars

    Map generation:
      --clean               Remove all files from generated map's directory before
                            generating new map
      --background-tiles    Generate image tiles of map's layers (may take a
                            while...)
      --show-centrelines    Show centrelines in generated map

    Diagnostics:
      --authoring           For use when checking a new map: highlight incomplete
                            features; show centreline network; no image tiles; no
                            neuron paths; etc
      --debug               Show a traceback for error exceptions
      --only-networks       Only output features that are part of a centreline
                            network
      --save-drawml         Save a slide's DrawML for debugging
      --save-geojson        Save GeoJSON files for each layer
      --tippecanoe          Show command used to run Tippecanoe

    Zoom level:
      --initial-zoom N      Initial zoom level (defaults to 4)
      --max-zoom N          Maximum zoom level (defaults to 10)
      --min-zoom N          Minimum zoom level (defaults to 2)

    Miscellaneous:
      --clean-connectivity  Refresh local connectivity knowledge from SciCrunch
      --id ID               Set explicit ID for flatmap, overriding manifest
      --single-file {celldl,svg}
                            Source is a single file of the designated type, not a
                            flatmap manifest

    Required arguments:
      --output OUTPUT       Base directory for generated flatmaps
      --source SOURCE       URL or path of a flatmap manifest


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


Integration
-----------

TODO...

*   Python wheel available.


Development
-----------

``mapmaker`` uses `poetry <https://python-poetry.org/docs/#installation>`_ for dependency management and packaging. To create a development environment::

    $ git clone https://github.com/AnatomicMaps/flatmap-maker.git mapmaker
    $ cd mapmaker
    $ poetry install


Building documentation
~~~~~~~~~~~~~~~~~~~~~~

In development mode, and within the Python virtual environment::

    $ cd docs
    $ make html

