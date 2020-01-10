==========
Deployment
==========

Put map directory into `~/flatmap-server/flatmaps` on `ubuntu@34.209.7.109`

::

    $ scp MAP.tar.gz ubuntu@34.209.7.109:
    $ ssh ubuntu@34.209.7.109
    $ cd ~/flatmap-server/flatmaps
    $ tar xzf ~/MAP.tar.gz
    $ rm ~/MAP.tar.gz
    $ ^D