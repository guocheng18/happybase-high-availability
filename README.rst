HappyBase with High Availability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

HappyBase_ is a developer-friendly Python library to interact with Apache
HBase. However it limits the connection to only one Thrift Server, which 
may cause serious problems when the server is down. To solve it, this repo
implements high available connection for HappyBase, i.e. switching connection 
to other live Thrift Servers when the currently connected is down and 
periodically recovering failed connections.

The only changed api is ``happybase.Connection`` with two arguments added:

- *servers*: List of Thrift server addresses (If given, the *host* and *port* arguments will be ignored)
- *recovery_delay*: Cycle time of recovery of failed connections (60 seconds by default)

Example
-------
.. code-block:: python

    import happybase

    conn = happybase.Connection(
        servers=[
            {"host": "192.168.0.1", "port": 9090},
            {"host": "192.168.0.2", "port": 9090},
            {"host": "192.168.0.3", "port": 9090},
        ],
        recovery_delay=60,
    )


Installation
------------
.. code-block:: bash

    git clone https://github.com/guocheng2018/happybase.git
    cd happybase
    python -m pip install .


.. _HappyBase: https://github.com/wbolster/happybase

.. If you're reading this from the README.rst file in a source tree,
   you can generate the HTML documentation by running "make doc" and browsing
   to doc/build/html/index.html to see the result.
