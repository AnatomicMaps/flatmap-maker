===============================
For Ubuntu 18 running under WSL
===============================

**Update for Python 3.12 and Poetry with SVG sources...**

**Use AnatomicMaps urls...**


*   Installation directory::

        $ mkdir ~/Flatmaps


Flatmap Maker
=============

*   Installation:

    NB: **Conda install** -- see README.rst

*   Running::

        $ cd ~/Flatmaps/maker
        $ pipenv run python mapmaker.py --background-tiles --max-zoom 6 ../server/flatmaps demo /mnt/c/Users/Dave/build/maps/demo.pptx


Map Viewer
==========

*   Prerequisites:

    Is ``npm`` bundled with ``node``??

    ::

        $ sudo apt install nodejs
        $ sudo apt install npm

*   Installation::

        $ cd ~/Flatmaps/
        $ git clone https://github.com/dbrnz/flatmap-mvt-viewer.git viewer
        $ cd viewer
        $ npm install

*   Configure::

        $ vi src/endpoints.js

        const MAP_ENDPOINT = 'http://localhost:4329/';

        $ vi src/main.js

              // mapManager.loadMap('NCBITaxon:9606', 'map1');
              mapManager.loadMap('file://mnt/c/Users/Dave/build/maps/demo.pptx', 'map1', { annotatable: true, debug: true });

*   Running:

    In a new shell::

        $ cd ~/Flatmaps/viewer
        $ npm start


Map server
==========

*   Installation::

        $ cd ~/Flatmaps/
        $ git clone https://github.com/dbrnz/flatmap-server.git server
        $ cd server
        $ pipenv install
        $ mkdir flatmaps


*   Running:

    In a new shell::

            $ cd ~/Flatmaps/server
            $ pipenv run python bin/server.py --annotate
