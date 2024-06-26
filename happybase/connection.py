# coding: UTF-8

"""
HappyBase connection module.
"""

import logging
import socket
import threading
import time

import six
from thriftpy2.protocol import TBinaryProtocol, TCompactProtocol
from thriftpy2.thrift import TClient, TException
from thriftpy2.transport import (
    TBufferedTransport, TFramedTransport, TSocket, TTransportException)

from Hbase_thrift import ColumnDescriptor, Hbase

from .table import Table
from .util import ensure_bytes, pep8_to_camel_case

logger = logging.getLogger(__name__)

STRING_OR_BINARY = (six.binary_type, six.text_type)

COMPAT_MODES = ("0.90", "0.92", "0.94", "0.96", "0.98")
THRIFT_TRANSPORTS = dict(buffered=TBufferedTransport, framed=TFramedTransport,)
THRIFT_PROTOCOLS = dict(binary=TBinaryProtocol, compact=TCompactProtocol,)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9090
DEFAULT_TRANSPORT = "buffered"
DEFAULT_COMPAT = "0.98"
DEFAULT_PROTOCOL = "binary"
DEFAULT_RECOVERY_DELAY = 60  # seconds


class HAClient(object):
    """ Thrift client with high availability """

    def __init__(self, subconnections):
        self.subconnections = subconnections
        self.id = 0

    def __getattr__(self, _api):
        def _api_func(*args, **kwargs):
            fails = 0
            failed = True
            while failed:
                if self.subconnections[self.id].status:
                    host = self.subconnections[self.id].server["host"]
                    port = self.subconnections[self.id].server["port"]

                    result = None
                    try:
                        result = getattr(self.subconnections[self.id].client, _api)(
                            *args, **kwargs
                        )
                        failed = False
                        logger.debug(
                            "Send request [%s] to %s:%d successfully", _api, host, port
                        )

                    except (TTransportException, socket.error):
                        logger.debug(
                            "Send request [%s] to %s:%d failed, trying other servers",
                            _api, host, port,
                        )
                        self.subconnections[self.id].transport.close()
                        self.subconnections[self.id].status = 0

                self.id = (self.id + 1) % len(self.subconnections)
                if failed:
                    fails += 1
                    if fails == len(self.subconnections):
                        raise TTransportException(
                            message="Send request [%s] to any of thrift servers failed!" % _api
                        )
            return result

        return _api_func


class Subconnection(object):
    """ Maintains information about a specific connection"""

    def __init__(self, server, transport, client, status):
        self.server = server
        self.transport = transport
        self.client = client
        self.status = status


class Connection(object):
    """Connection to one or more HBase Thrift servers.

    The `host` and `port` arguments specify the host name and TCP port
    of the HBase Thrift server to connect to. If omitted or ``None``,
    a connection to the default port on ``localhost`` is made. If
    specified, the `timeout` argument specifies the socket timeout in
    milliseconds.

    If `servers` is not None, the `host` and `port` arguments will be
    ignored. And if more than one server address is given in `servers`,
    the connection to thrift servers is high available.

    If `autoconnect` is `True` (the default) the connection is made
    directly, otherwise :py:meth:`Connection.open` must be called
    explicitly before first use.

    The optional `table_prefix` and `table_prefix_separator` arguments
    specify a prefix and a separator string to be prepended to all table
    names, e.g. when :py:meth:`Connection.table` is invoked. For
    example, if `table_prefix` is ``myproject``, all tables will
    have names like ``myproject_XYZ``.

    The optional `compat` argument sets the compatibility level for
    this connection. Older HBase versions have slightly different Thrift
    interfaces, and using the wrong protocol can lead to crashes caused
    by communication errors, so make sure to use the correct one. This
    value can be either the string ``0.90``, ``0.92``, ``0.94``, or
    ``0.96`` (the default).

    The optional `transport` argument specifies the Thrift transport
    mode to use. Supported values for this argument are ``buffered``
    (the default) and ``framed``. Make sure to choose the right one,
    since otherwise you might see non-obvious connection errors or
    program hangs when making a connection. HBase versions before 0.94
    always use the buffered transport. Starting with HBase 0.94, the
    Thrift server optionally uses a framed transport, depending on the
    argument passed to the ``hbase-daemon.sh start thrift`` command.
    The default ``-threadpool`` mode uses the buffered transport; the
    ``-hsha``, ``-nonblocking``, and ``-threadedselector`` modes use the
    framed transport.

    The optional `protocol` argument specifies the Thrift transport
    protocol to use. Supported values for this argument are ``binary``
    (the default) and ``compact``. Make sure to choose the right one,
    since otherwise you might see non-obvious connection errors or
    program hangs when making a connection. ``TCompactProtocol`` is
    a more compact binary format that is  typically more efficient to
    process as well. ``TBinaryProtocol`` is the default protocol that
    Happybase uses.

    The optional `recovery_delay` argument specifies the delay that the
    daemon thread executes the recovery of failed connections.

    .. versionadded:: 0.9
       `protocol` argument

    .. versionadded:: 0.5
       `timeout` argument

    .. versionadded:: 0.4
       `table_prefix_separator` argument

    .. versionadded:: 0.4
       support for framed Thrift transports

    :param str host: The host to connect to
    :param int port: The port to connect to
    :param list servers: All thrift servers to enable HA, this will ignore 
        the `host` and `port` arguments (optional)
    :param int timeout: The socket timeout in milliseconds (optional)
    :param bool autoconnect: Whether the connection should be opened directly
    :param str table_prefix: Prefix used to construct table names (optional)
    :param str table_prefix_separator: Separator used for `table_prefix`
    :param str compat: Compatibility mode (optional)
    :param str transport: Thrift transport mode (optional)
    :param int recovery_delay: Seconds delay to execute recovery (optional)
    """

    def __init__(
        self,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        servers=None,
        timeout=None,
        autoconnect=True,
        table_prefix=None,
        table_prefix_separator=b"_",
        compat=DEFAULT_COMPAT,
        transport=DEFAULT_TRANSPORT,
        protocol=DEFAULT_PROTOCOL,
        recovery_delay=DEFAULT_RECOVERY_DELAY,
    ):

        if transport not in THRIFT_TRANSPORTS:
            raise ValueError(
                "'transport' must be one of %s" % ", ".join(THRIFT_TRANSPORTS.keys())
            )

        if table_prefix is not None:
            if not isinstance(table_prefix, STRING_OR_BINARY):
                raise TypeError("'table_prefix' must be a string")
            table_prefix = ensure_bytes(table_prefix)

        if not isinstance(table_prefix_separator, STRING_OR_BINARY):
            raise TypeError("'table_prefix_separator' must be a string")
        table_prefix_separator = ensure_bytes(table_prefix_separator)

        if compat not in COMPAT_MODES:
            raise ValueError("'compat' must be one of %s" % ", ".join(COMPAT_MODES))

        if protocol not in THRIFT_PROTOCOLS:
            raise ValueError(
                "'protocol' must be one of %s" % ", ".join(THRIFT_PROTOCOLS)
            )

        # Allow host and port to be None, which may be easier for
        # applications wrapping a Connection instance.
        if servers is None:
            self.servers = [
                {"host": host or DEFAULT_HOST, "port": port or DEFAULT_PORT}
            ]
        else:
            self.servers = servers

        self.timeout = timeout
        self.table_prefix = table_prefix
        self.table_prefix_separator = table_prefix_separator
        self.compat = compat

        self._transport_class = THRIFT_TRANSPORTS[transport]
        self._protocol_class = THRIFT_PROTOCOLS[protocol]
        self._refresh_thrift_client()

        self.recovery_thread = threading.Thread(
            target=self._recover_failed_connections, args=(recovery_delay,), daemon=True
        )

        if autoconnect:
            self.open()

        self._initialized = True

    def _refresh_thrift_client(self):
        """Refresh the Thrift sockets, transports, and clients."""
        self.subconnections = []

        for server in self.servers:
            socket = TSocket(
                host=server["host"], port=server["port"], socket_timeout=self.timeout
            )
            transport = self._transport_class(socket)
            protocol = self._protocol_class(transport, decode_response=False)
            client = TClient(Hbase, protocol)

            subconnection = Subconnection(
                server=server, transport=transport, client=client, status=0
            )
            self.subconnections.append(subconnection)

        self.client = HAClient(self.subconnections)

    def _table_name(self, name):
        """Construct a table name by optionally adding a table name prefix."""
        name = ensure_bytes(name)
        if self.table_prefix is None:
            return name
        return self.table_prefix + self.table_prefix_separator + name

    def _recover_failed_connections(self, delay):
        """ Try to reopen failed connections every specified seconds """
        while True:
            for subconn in self.subconnections:
                host = subconn.server["host"]
                port = subconn.server["port"]

                if subconn.status == 0:
                    try:
                        subconn.transport.open()
                        subconn.status = 1
                        logger.debug("Connection to %s:%d recovered", host, port)
                    except (TException, socket.error):
                        logger.debug("Recover connection to %s:%d failed", host, port)
            time.sleep(delay)

    def open(self):
        """Open the underlying transport to the HBase instance.

        This method opens the underlying Thrift transport (TCP connection).
        """
        for subconn in self.subconnections:
            host = subconn.server["host"]
            port = subconn.server["port"]

            if not subconn.transport.is_open():
                logger.debug("Opening Thrift transport to %s:%d", host, port)
                try:
                    subconn.transport.open()
                    subconn.status = 1
                except (TException, socket.error):
                    logger.warning("Connect to %s:%d failed", host, port)

        if sum([subconn.status for subconn in self.subconnections]) == 0:
            raise TTransportException(
                message="Failed to connect to any of thrift servers"
            )

        # Recovery
        if not self.recovery_thread.is_alive():
            self.recovery_thread.start()

    def close(self):
        """Close the underlying transport to the HBase instance.

        This method closes the underlying Thrift transport (TCP connection).
        """
        for subconn in self.subconnections:
            if subconn.transport.is_open():
                if logger is not None:
                    # If called from __del__(), module variables may no longer
                    # exist.
                    logger.debug(
                        "Closing Thrift transport to %s:%d",
                        subconn.server["host"],
                        subconn.server["port"],
                    )
                subconn.transport.close()
                subconn.status = 0

    def __del__(self):
        try:
            self._initialized
        except AttributeError:
            # Failure from constructor
            return
        else:
            self.close()

    def table(self, name, use_prefix=True):
        """Return a table object.

        Returns a :py:class:`happybase.Table` instance for the table
        named `name`. This does not result in a round-trip to the
        server, and the table is not checked for existence.

        The optional `use_prefix` argument specifies whether the table
        prefix (if any) is prepended to the specified `name`. Set this
        to `False` if you want to use a table that resides in another
        ‘prefix namespace’, e.g. a table from a ‘friendly’ application
        co-hosted on the same HBase instance. See the `table_prefix`
        argument to the :py:class:`Connection` constructor for more
        information.

        :param str name: the name of the table
        :param bool use_prefix: whether to use the table prefix (if any)
        :return: Table instance
        :rtype: :py:class:`Table`
        """
        name = ensure_bytes(name)
        if use_prefix:
            name = self._table_name(name)
        return Table(name, self)

    #
    # Table administration and maintenance
    #

    def tables(self):
        """Return a list of table names available in this HBase instance.

        If a `table_prefix` was set for this :py:class:`Connection`, only
        tables that have the specified prefix will be listed.

        :return: The table names
        :rtype: List of strings
        """
        names = self.client.getTableNames()

        # Filter using prefix, and strip prefix from names
        if self.table_prefix is not None:
            prefix = self._table_name(b"")
            offset = len(prefix)
            names = [n[offset:] for n in names if n.startswith(prefix)]

        return names

    def create_table(self, name, families):
        """Create a table.

        :param str name: The table name
        :param dict families: The name and options for each column family

        The `families` argument is a dictionary mapping column family
        names to a dictionary containing the options for this column
        family, e.g.

        ::

            families = {
                'cf1': dict(max_versions=10),
                'cf2': dict(max_versions=1, block_cache_enabled=False),
                'cf3': dict(),  # use defaults
            }
            connection.create_table('mytable', families)

        These options correspond to the ColumnDescriptor structure in
        the Thrift API, but note that the names should be provided in
        Python style, not in camel case notation, e.g. `time_to_live`,
        not `timeToLive`. The following options are supported:

        * ``max_versions`` (`int`)
        * ``compression`` (`str`)
        * ``in_memory`` (`bool`)
        * ``bloom_filter_type`` (`str`)
        * ``bloom_filter_vector_size`` (`int`)
        * ``bloom_filter_nb_hashes`` (`int`)
        * ``block_cache_enabled`` (`bool`)
        * ``time_to_live`` (`int`)
        """
        name = self._table_name(name)
        if not isinstance(families, dict):
            raise TypeError("'families' arg must be a dictionary")

        if not families:
            raise ValueError(
                "Cannot create table %r (no column families specified)" % name
            )

        column_descriptors = []
        for cf_name, options in six.iteritems(families):
            if options is None:
                options = dict()

            kwargs = dict()
            for option_name, value in six.iteritems(options):
                kwargs[pep8_to_camel_case(option_name)] = value

            if not cf_name.endswith(":"):
                cf_name += ":"
            kwargs["name"] = cf_name

            column_descriptors.append(ColumnDescriptor(**kwargs))

        self.client.createTable(name, column_descriptors)

    def delete_table(self, name, disable=False):
        """Delete the specified table.

        .. versionadded:: 0.5
           `disable` argument

        In HBase, a table always needs to be disabled before it can be
        deleted. If the `disable` argument is `True`, this method first
        disables the table if it wasn't already and then deletes it.

        :param str name: The table name
        :param bool disable: Whether to first disable the table if needed
        """
        if disable and self.is_table_enabled(name):
            self.disable_table(name)

        name = self._table_name(name)
        self.client.deleteTable(name)

    def enable_table(self, name):
        """Enable the specified table.

        :param str name: The table name
        """
        name = self._table_name(name)
        self.client.enableTable(name)

    def disable_table(self, name):
        """Disable the specified table.

        :param str name: The table name
        """
        name = self._table_name(name)
        self.client.disableTable(name)

    def is_table_enabled(self, name):
        """Return whether the specified table is enabled.

        :param str name: The table name

        :return: whether the table is enabled
        :rtype: bool
        """
        name = self._table_name(name)
        return self.client.isTableEnabled(name)

    def compact_table(self, name, major=False):
        """Compact the specified table.

        :param str name: The table name
        :param bool major: Whether to perform a major compaction.
        """
        name = self._table_name(name)
        if major:
            self.client.majorCompact(name)
        else:
            self.client.compact(name)
